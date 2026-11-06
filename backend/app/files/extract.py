"""
Извлечение «сырого» текста из файлов. Без LLM.
"""

import logging
import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from app.config import settings
from app.errors import AppError
from app.models import FileType

logger = logging.getLogger("app.files")


@dataclass
class Page:
    """Страница документа."""

    number: int | None
    text: str
    # PDF: строки, набранные крупным или жирным шрифтом -> уровень заголовка (1 — самый крупный)
    headings: dict[str, int] = field(default_factory=dict)


class ExtractError(AppError):
    """Из файла не удалось достать текст."""

    def __init__(self, message: str, code: str = "extract_failed") -> None:
        super().__init__(message, status_code=422, code=code)


def norm_line(text: str) -> str:
    """Строка для сравнения."""
    return re.sub(r"\s+", " ", text).strip()


def clean_text(raw: str) -> str:
    """Минимальная нормализация."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# PDF

_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)


Fragment = tuple[str, float, bool, float, float]  # текст, размер, жирный, x, y


def body_size_of(chars_by_size: Counter) -> float:
    """Размер основного текста."""
    total = sum(chars_by_size.values())
    if not total:
        return 0.0
    covered, body = 0, []
    for size, n in chars_by_size.most_common():
        body.append(size)
        covered += n
        if covered >= 0.75 * total:
            break
    return max(body)


def _body_size(fragments_by_page: list[list[Fragment]]) -> float:
    chars: Counter = Counter()
    for fragments in fragments_by_page:
        for text, size, *_ in fragments:
            chars[size] += len(text.strip())
    return body_size_of(chars)


def _heading_hints(fragments_by_page: list[list[Fragment]]) -> list[dict[str, int]]:
    """По шрифтам определить, какие строки PDF — заголовки."""
    chars: Counter = Counter()
    bold_chars = total = 0
    for fragments in fragments_by_page:
        for text, size, bold, *_ in fragments:
            n = len(text.strip())
            chars[size] += n
            total += n
            if bold:
                bold_chars += n
    if not chars or not total:
        return [{} for _ in fragments_by_page]

    body_size = body_size_of(chars)
    bold_allowed = bold_chars / total < 0.4  # если жирным набрано полдокумента, жирность ничего не значит

    def is_heading_style(size: float, bold: bool) -> bool:
        if size >= body_size * 1.12:
            return True
        return bold_allowed and bold and size >= body_size * 0.95

    styles = sorted(
        {(size, bold) for fr in fragments_by_page for _, size, bold, *_ in fr if is_heading_style(size, bold)},
        key=lambda s: (-s[0], not s[1]),
    )
    level_of = {style: min(i + 1, 4) for i, style in enumerate(styles)}

    result: list[dict[str, int]] = []
    for fragments in fragments_by_page:
        hints: dict[str, int] = {}
        run_text, run_style = "", None

        def flush_run() -> None:
            nonlocal run_text, run_style
            if run_style in level_of:
                for line in run_text.split("\n"):
                    line = norm_line(line)
                    if line and len(line) <= 150:
                        if run_style[1] and run_style[0] < body_size * 1.12 and re.search(r"[.,;:!?]$", line):
                            continue
                        hints.setdefault(line, level_of[run_style])
            run_text, run_style = "", None

        for text, size, bold, *_ in fragments:
            style = (size, bold)
            if style != run_style:
                flush_run()
                run_style = style
            run_text += text
        flush_run()
        result.append(hints)
    return result


def _insert_paragraph_breaks(text: str, fragments: list[Fragment], body_size: float) -> str:
    """Вставить пустую строку там, где между строками PDF заметно больший интервал."""
    starts: list[list] = []  # [начало строки, y, размер, нужен ли пропуск перед строкой]
    prev_y = None
    for frag_text, size, _bold, _x, y in fragments:
        lines = frag_text.split("\n")
        first = norm_line(lines[0])
        if first and (prev_y is None or abs(y - prev_y) > 0.3 * max(size, 1)):
            starts.append([first, y, size, False])
        prev_y = y
        for extra in lines[1:]:
            if norm_line(extra):
                starts.append([norm_line(extra), None, size, False])

    gaps = []
    for a, b in zip(starts, starts[1:]):
        if a[1] is not None and b[1] is not None:
            gap = a[1] - b[1]
            if 0.8 * body_size < gap < 2.5 * max(body_size, 1):
                heading_continuation = a[2] == b[2] and a[2] > 1.12 * body_size
                gaps.append((gap, b, heading_continuation))
    if len(gaps) < 4:
        return text
    typical = sorted(g for g, _, _ in gaps)[len(gaps) // 2]
    for gap, b, heading_continuation in gaps:
        if gap > 1.35 * typical and not heading_continuation:
            b[3] = True

    out: list[str] = []
    k = 0
    for line in text.split("\n"):
        key = norm_line(line)
        for j in range(k, min(k + 3, len(starts))):
            prefix = starts[j][0]
            if key and min(len(key), len(prefix)) >= 3 and (key.startswith(prefix) or prefix.startswith(key)):
                if starts[j][3] and out and out[-1] != "":
                    out.append("")
                k = j + 1
                break
        out.append(line)
    return "\n".join(out)


def _extract_pdf_pypdf(path: Path) -> list[Page]:
    """Запасной вариант: pypdf."""
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise ExtractError(f"Не удалось открыть PDF: {exc}", "bad_pdf") from exc

    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")
        except Exception:
            decrypted = 0
        if not decrypted:
            raise ExtractError(
                "PDF защищён паролем. Снимите защиту и загрузите файл снова", "encrypted_pdf"
            )

    texts: list[str] = []
    fragments_by_page: list[list[Fragment]] = []
    for number, page in enumerate(reader.pages, start=1):
        fragments: list[Fragment] = []

        def visitor(text, cm, tm, font_dict, font_size, _out=fragments):  # noqa: ANN001
            if not text or not text.strip():
                return
            try:
                scale = math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1]) or 1.0
                size = round(float(font_size or 0) * scale, 1)
                x = float(cm[4] + tm[4] * cm[0])
                y = float(cm[5] + tm[5] * cm[3])
            except Exception:
                size, x, y = 0.0, 0.0, 0.0
            name = str((font_dict or {}).get("/BaseFont", ""))
            _out.append((text, size, bool(_BOLD_FONT.search(name)), x, y))

        try:
            texts.append(page.extract_text(visitor_text=visitor) or "")
        except Exception:
            logger.warning("Страница %s не прочиталась: %s", number, path.name)
            texts.append("")
            fragments = []
        fragments_by_page.append(fragments)

    try:
        hints = _heading_hints(fragments_by_page)
    except Exception:  
        logger.warning("Не удалось определить заголовки по шрифтам: %s", path.name, exc_info=True)
        hints = [{} for _ in texts]
    try:
        body = _body_size(fragments_by_page)
        texts = [_insert_paragraph_breaks(t, f, body) for t, f in zip(texts, fragments_by_page)]
    except Exception:
        logger.warning("Не удалось определить абзацы по интервалам: %s", path.name, exc_info=True)
    return [Page(i, text, hints[i - 1]) for i, text in enumerate(texts, start=1)]


_XHTML = "{http://www.w3.org/1999/xhtml}"


def _fix_punctuation_spaces(line: str) -> str:
    line = re.sub(r"\s+([,.;:!?%)»\]])", r"\1", line)
    line = re.sub(r"([(«\[])\s+", r"\1", line)
    return re.sub(r" {2,}", " ", line).strip()


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass
class _Line:
    text: str
    height: float
    x0: float
    x1: float
    y0: float
    y1: float
    block: int
    merged: bool = False


_CODE_STRICT = re.compile(
    r"^(#include\b|#define\b|\s*[{}]\s*(//.*)?$|\s*(else|do|try)\s*\{?\s*(//.*)?$|\s*(if|else|for|while|switch|return|using|std::)\b.*[;{()]\s*(//.*)?$"
    r"|.*;\s*(//.*)?$)"
)
_MARKER = re.compile(r"[\ue000-\uf8ff•·▪◦●○■□\-–—*]|\d{1,3}[.)]")
_CODE_SOFT = re.compile(r"[;{}=]|//|\w\(.*\)")


def _merge_rows(blocks: list[list[_Line]]) -> list[list[_Line]]:
    """Короткие блоки на одной строке страницы склеить в одну строку."""
    flat = [ln for b in blocks for ln in b]
    sizes: dict[int, int] = Counter(ln.block for ln in flat)
    plan: list[tuple[_Line, _Line]] = []
    taken: set[int] = set()
    for right in flat:
        if sizes[right.block] > 12:
            continue
        for left in flat:
            if left is right or left.block == right.block or sizes[left.block] > 12 or id(left) in taken:
                continue
            same_row = abs((left.y0 + left.y1) / 2 - (right.y0 + right.y1) / 2) < 0.4 * max(left.y1 - left.y0, 1)
            if same_row and left.x1 + 4 < right.x0 and left.y0 <= right.y0 + 3:
                plan.append((left, right))
                taken.add(id(left))
                break
    if not plan or len(plan) > 0.25 * len(flat):  
        return blocks
    gone = set()
    for left, right in plan:
        if _MARKER.fullmatch(left.text):  
            right.text = left.text + " " + right.text
            right.x0 = left.x0
            gone.add(id(left))
            continue
        left.text += ("  " if right.text.startswith("//") else " | ") + right.text
        left.x1 = right.x1
        gone.add(id(right))
    return [[ln for ln in b if id(ln) not in gone] for b in blocks if any(id(ln) not in gone for ln in b)]


def _is_code_line(line: _Line, body_height: float) -> bool:
    text = line.text.strip()
    if text.startswith("//"):
        return True
    code = text.split("//", 1)[0].strip()
    if not code or re.search(r"[А-Яа-яЁё]", code):
        return False
    if _CODE_STRICT.match(code):
        return True
    return line.height <= 0.88 * body_height and bool(_CODE_SOFT.search(code))


def _mark_code(blocks: list[list[_Line]], body_height: float) -> list[list[tuple[str, float]]]:
    """Подряд идущие строки кода оформить одним блоком."""
    flat: list[_Line] = [ln for b in blocks for ln in b]
    merged_flat: list[_Line] = []
    for idx, ln in enumerate(flat):
        prev = merged_flat[-1] if merged_flat else None
        nxt = flat[idx + 1] if idx + 1 < len(flat) else None
        if (
            prev and nxt and "//" in prev.text and ln.text[:1].islower() and len(ln.text.split()) <= 6
            and not _is_code_line(ln, body_height) and _is_code_line(prev, body_height) and _is_code_line(nxt, body_height)
        ):
            prev.text += " " + ln.text
            continue
        merged_flat.append(ln)
    flat = merged_flat
    result: list[list[tuple[str, float]]] = []
    i = 0
    while i < len(flat):
        if _is_code_line(flat[i], body_height):
            j = i
            while j < len(flat) and _is_code_line(flat[j], body_height):
                j += 1
            run = flat[i:j]
            if len(run) >= 2:
                left = min(ln.x0 for ln in run)
                widths = [(ln.x1 - ln.x0) / max(len(ln.text), 1) for ln in run]
                char_w = max(sorted(widths)[len(widths) // 2], 1.0)
                lines = []
                for ln in run:
                    indent = 4 * round((ln.x0 - left) / (4 * char_w))
                    lines.append(" " * indent + ln.text)
                result.append([("```\n" + "\n".join(lines) + "\n```", 0.0)])
                i = j
                continue
        k = i
        while k < len(flat) and flat[k].block == flat[i].block and not (k > i and _is_code_line(flat[k], body_height)):
            k += 1
        k = max(k, i + 1)
        result.append([(ln.text, ln.height) for ln in flat[i:k]])
        i = k
    return result


def _merge_number_columns(blocks: list[list[tuple[str, float]]]) -> list[list[tuple[str, float]]]:
    """Нумерация, вынесенная в отдельную колонку."""
    result: list[list[tuple[str, float]]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        numbers_only = all(re.fullmatch(r"\d{1,3}[.)]", text) for text, _ in block)
        if numbers_only and i + 1 < len(blocks) and len(blocks[i + 1]) == len(block):
            result.append([(f"{n[0]} {t[0]}", t[1]) for n, t in zip(block, blocks[i + 1])])
            i += 2
            continue
        result.append(block)
        i += 1
    return result


def _extract_pdf_poppler(path: Path) -> list[Page] | None:
    """Основной вариант: pdftotext (poppler)."""
    exe = shutil.which("pdftotext")
    if not exe:
        logger.warning("pdftotext не установлен, текст PDF читается через pypdf (качество ниже)")
        return None
    try:
        proc = subprocess.run(
            [exe, "-bbox-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True, timeout=180, check=False,
        )
        if proc.returncode != 0:
            logger.warning("pdftotext завершился с ошибкой: %s", proc.stderr[:200])
            return None
        root = ET.fromstring(proc.stdout.decode("utf-8", "replace"))
    except Exception:
        logger.warning("pdftotext не сработал, используем pypdf", exc_info=True)
        return None

    raw_pages: list[list[list[_Line]]] = []
    for page in root.iter(_XHTML + "page"):
        blocks = []
        for bi, block in enumerate(page.iter(_XHTML + "block")):
            lines = []
            for line in block.iter(_XHTML + "line"):
                words = [w.text or "" for w in line.iter(_XHTML + "word")]
                text = _fix_punctuation_spaces(" ".join(words))
                if text:
                    y0, y1 = float(line.get("yMin", 0)), float(line.get("yMax", 0))
                    lines.append(_Line(text, round(y1 - y0, 1), float(line.get("xMin", 0)),
                                       float(line.get("xMax", 0)), y0, y1, bi))
            if lines:
                blocks.append(lines)
        raw_pages.append(blocks)

    chars: Counter = Counter()
    for blocks in raw_pages:
        for block in blocks:
            for ln in block:
                chars[round(ln.height)] += len(ln.text)
    if not chars:
        return None
    body = body_size_of(chars)

    pages_blocks: list[list[list[tuple[str, float]]]] = []
    for blocks in raw_pages:
        blocks = _merge_rows(blocks)
        pages_blocks.append(_merge_number_columns(_mark_code(blocks, body)))

    heights = sorted(
        {round(h) for blocks in pages_blocks for b in blocks if len(b) <= 3 for _, h in b if h > 0 and round(h) >= body * 1.12},
        reverse=True,
    )
    level_of = {h: min(i + 1, 4) for i, h in enumerate(heights)}

    pages = []
    for number, blocks in enumerate(pages_blocks, start=1):
        hints: dict[str, int] = {}
        parts = []
        for block in blocks:
            parts.append("\n".join(text for text, _ in block))
            if len(block) <= 3:
                for text, height in block:
                    if round(height) in level_of and len(text) <= 150:
                        hints[norm_line(text)] = level_of[round(height)]
        pages.append(Page(number, "\n\n".join(parts), hints))
    return pages


def extract_pdf(path: Path) -> list[Page]:
    """Достать текст из PDF постранично."""
    fallback = _extract_pdf_pypdf(path) 
    primary = _extract_pdf_poppler(path)
    if primary is None or len(primary) != len(fallback):
        return fallback

    got = sum(len(_squeeze(p.text)) for p in primary)
    base = sum(len(_squeeze(p.text)) for p in fallback)
    if base and got < 0.6 * base:
        logger.warning("pdftotext вернул заметно меньше текста, используем pypdf")
        return fallback

    top_level = max((lvl for p in primary for lvl in p.headings.values()), default=0)
    for page, alt in zip(primary, fallback):
        single = {}
        for block in page.text.split("\n\n"):
            block_lines = [ln for ln in block.split("\n") if ln.strip()]
            if len(block_lines) == 1:
                single[_squeeze(block_lines[0])] = block_lines[0]
        for hint, level in alt.headings.items():
            line = single.get(_squeeze(hint))
            if line is None or norm_line(line) in page.headings:
                continue
            words = line.split()
            if (
                len(line) >= 6 and len(words) <= 10 and not re.search(r"[.,;:!?]$", line)
                and line[0].isalnum() and (line[0].isupper() or line[0].isdigit())
            ):
                page.headings[norm_line(line)] = min(max(level, top_level + 1), 4)
    return primary


# DOCX

_HEADING_STYLE = re.compile(r"^(?:heading|заголовок)\s*(\d)", re.IGNORECASE)
_TITLE_STYLE = re.compile(r"^(?:title|название|заголовок)$", re.IGNORECASE)
_TOC_STYLE = re.compile(r"^(?:toc\b|toc\s*\d|оглавление|содержание|table of contents)", re.IGNORECASE)
_LIST_STYLE = re.compile(r"^(?:list|список)", re.IGNORECASE)


def _paragraph_line(paragraph: Paragraph) -> str | None:
    """Одна строка текста для абзаца DOCX."""
    text = paragraph.text.replace("\n", " ").replace("\v", " ").strip()
    if not text:
        return None
    try:
        style_name = paragraph.style.name or ""
    except Exception:
        style_name = ""

    if _TOC_STYLE.match(style_name):
        return None 

    match = _HEADING_STYLE.match(style_name)
    if match:
        return "#" * max(1, min(int(match.group(1)), 4)) + " " + text
    if _TITLE_STYLE.match(style_name):
        return "# " + text
    outline = paragraph._p.xpath("./w:pPr/w:outlineLvl/@w:val")
    if outline and str(outline[0]).isdigit() and int(outline[0]) < 4:
        return "#" * (int(outline[0]) + 1) + " " + text

    is_list = bool(_LIST_STYLE.match(style_name) or paragraph._p.xpath("./w:pPr/w:numPr"))
    line = "- " + text if is_list else text
    if line.startswith("#"):
        line = "\\" + line  
    return line


def _table_lines(table: Table) -> list[str]:
    lines = []
    for row in table.rows:
        cells: list[str] = []
        seen: set[int] = set()
        for cell in row.cells:
            if id(cell._tc) in seen:  
                continue
            seen.add(id(cell._tc))
            cells.append(cell.text.replace("\n", " ").strip())
        if any(cells):
            lines.append(" | ".join(cells))
    return lines


def extract_docx(path: Path) -> list[Page]:
    """Достать текст из DOCX."""
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ExtractError(
            "Не удалось открыть DOCX. Возможно, это файл другого формата "
            "с расширением .docx",
            "bad_docx",
        ) from exc

    lines: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            line = _paragraph_line(Paragraph(child, document))
            if line:
                lines.append(line)
        elif tag == "tbl":
            lines.extend(_table_lines(Table(child, document)))
    return [Page(None, "\n".join(lines))]


# ---------------------------------------------------------------- TXT

_BOMS = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)
_LEGACY_ENCODINGS = ("cp1251", "cp866", "koi8-r")
_COMMON_RU = set("оеаинтсрвлкмдпуяыьгзбчйхжшюцщэфё")


def _russian_score(text: str) -> float:
    sample = text[:20000]
    if not sample:
        return 0.0
    lower = sum(1 for ch in sample if ch in _COMMON_RU)
    upper = sum(1 for ch in sample if "А" <= ch <= "Я" or ch == "Ё")
    return (lower - upper) / len(sample)


def _letters_score(text: str) -> float:
    sample = text[:5000]
    if not sample:
        return 0.0
    good = sum(1 for ch in sample if ch.isspace() or ("а" <= ch.lower() <= "я") or ch in "ёЁ" or ("a" <= ch.lower() <= "z") or ch.isdigit() or ch in ".,;:!?-—()\"'«»")
    return good / len(sample)


def _looks_like_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in data


def decode_text(data: bytes) -> str:
    """Расшифровать байты TXT."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                break

    if len(data) >= 4 and len(data) % 2 == 0 and not _looks_like_utf8(data):
        best, best_score = None, 0.0
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                candidate = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            score = _letters_score(candidate)
            if score > best_score:
                best, best_score = candidate, score
        if best is not None and best_score > 0.5:
            return best
    if len(data) >= 4 and b"\x00" in data[:200]:
        raise ExtractError(
            "Это не текстовый файл: внутри двоичные данные. "
            "Сохраните документ как обычный .txt (кодировка UTF-8)",
            "not_text",
        )

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    candidates = []
    for encoding in _LEGACY_ENCODINGS:
        try:
            candidates.append((_russian_score(text := data.decode(encoding)), encoding, text))
        except UnicodeDecodeError:
            continue
    if candidates:
        return max(candidates)[2]
    raise ExtractError(
        "Не удалось определить кодировку файла. Пересохраните его в UTF-8",
        "bad_encoding",
    )


def extract_txt(path: Path) -> list[Page]:
    return [Page(None, decode_text(path.read_bytes()))]


EXTRACTORS: dict = {
    FileType.PDF: extract_pdf,
    FileType.DOCX: extract_docx,
    FileType.TXT: extract_txt,
}


def extract_pages(path: Path, file_type: FileType) -> list[Page]:
    """Текст документа по страницам."""
    pages = []
    for page in EXTRACTORS[file_type](path):
        text = clean_text(page.text)
        if text:
            pages.append(Page(page.number, text, page.headings))

    total = sum(len(page.text) for page in pages)
    if total < settings.min_text_chars:
        if file_type == FileType.PDF:
            message = (
                "В файле не нашлось текста. Скорее всего, это скан или фотографии "
                "страниц: внутри такого файла только картинки. "
                "Загрузите документ с текстовым слоем"
            )
            code = "no_text_layer"
        else:
            message = (
                f"В файле слишком мало текста: {total} симв., нужно не меньше "
                f"{settings.min_text_chars}. Для курса нужен документ с содержанием"
            )
            code = "too_short"
        raise ExtractError(message, code)
    logger.info("Извлечено %s символов (%s стр.) из %s", total, len(pages), path.name)
    return pages


def extract_text(path: Path, file_type: FileType) -> str:
    return "\n\n".join(page.text for page in extract_pages(path, file_type))
