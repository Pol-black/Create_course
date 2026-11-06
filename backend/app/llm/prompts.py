"""
Промпты лежат в app/llm/prompts/<имя>.system.txt и <имя>.user.txt.
Переменные подставляются через string.Template: $text, $chunks и т. д.
Не через {text}: в промптах есть примеры JSON с фигурными скобками.
"""

from pathlib import Path
from string import Template

from app.llm.errors import LLMError

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str, **variables: object) -> tuple[str, str]:
    """Вернуть (system, user) для промпта с подставленными переменными."""
    parts = []
    for kind in ("system", "user"):
        path = PROMPTS_DIR / f"{name}.{kind}.txt"
        if not path.is_file():
            raise LLMError(f"Не найден промпт {path.name}", code="llm_prompt_missing", status_code=500)
        template = Template(path.read_text(encoding="utf-8"))
        try:
            parts.append(template.substitute(**{k: str(v) for k, v in variables.items()}))
        except KeyError as exc:
            raise LLMError(
                f"В промпт {path.name} не передана переменная {exc}",
                code="llm_prompt_variable",
                status_code=500,
            ) from exc
    return parts[0], parts[1]
