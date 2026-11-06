# Create_course

Backend на FastAPI + PostgreSQL, фронтенд на Vue 3 + Vite, миграции через Flyway, запуск через Docker Compose.
Сервис, который превращает документы (PDF, DOCX, TXT) в обучающий курс с помощью LLM.
Backend: FastAPI + PostgreSQL (миграции Flyway), frontend: Vue 3, запуск через Docker Compose.

## Требования

- Docker и Docker Compose
- Python 3.12 — только для локального запуска backend без Docker
- Node.js (LTS) — только для локального запуска frontend без Docker

## Запуск

```bash
git clone <url> && cd Prototype
cp .env.example .env        # при необходимости поменять пароль, порты, LOG_LEVEL, FRONTEND_PORT
git clone https://github.com/Pol-black/Create_course.git && cd Create_course
cp .env.example .env        # поменять пароль БД и вписать ключ OpenRouter в LLM_API_KEY
docker compose up -d --build
docker compose ps

```

`postgres`, `backend` и `frontend` должны быть `healthy`, `flyway` — `exited (0)`.

После изменений в `backend/` или `frontend/` пересобрать соответствующий образ:

```bash
docker compose up -d --build backend
# или
docker compose up -d --build frontend

```

## Проверка

| Адрес | Назначение |
| --- | --- |
| http://localhost:5173 | Веб-интерфейс (Vue 3 + Vite) |
| http://localhost:8000/api/health | Состояние сервиса и БД |
| http://localhost:8000/api/health/live, /api/health/ready | Процесс жив / готов (есть связь с БД) |
| http://localhost:8000/api/llm/check | Связь с моделью: короткий вопрос и ответ |
| http://localhost:8000/docs | Swagger UI |

Скрипты проверки моделей, журнала обработки и загрузки файлов:

```bash
docker compose exec backend python -m app.scripts.check_models
docker compose exec backend python -m app.scripts.check_logging
docker compose exec backend python -m app.scripts.check_upload

```

Логи: `docker compose logs -f backend` (или `frontend`)

## Обработка документа

Загрузка только сохраняет файл (статус `UPLOADED`). Обработка запускается кнопкой «Обработать»
(`POST /api/documents/{id}/process`, ответ 202) и идёт в фоне, страница опрашивает статус.

Алгоритм (без LLM, только правила):

1. **Извлечение.** PDF: `pdftotext` из poppler-utils (слова, строки, координаты), размер и жирность шрифта
   через pypdf как подсказки для заголовков; если poppler нет, используется pypdf. DOCX: абзацы, списки
   и таблицы в исходном порядке, стили заголовков. TXT: определение кодировки (UTF-8, UTF-16, cp1251,
   cp866, koi8-r).
2. **Очистка.** Удаляются колонтитулы и номера страниц, оглавление, соединяются переносы слов и строки,
   нормализуются пробелы и спецсимволы.
3. **Заголовки.** По шрифту, стилям DOCX, `#` в TXT, нумерации («1.2»), словам «Глава», ЗАГЛАВНЫМ.
4. **Деление на фрагменты** по заголовкам (`CHUNK_TARGET_WORDS`, `CHUNK_MAX_WORDS`, `CHUNK_MIN_WORDS`)
   с номерами страниц `page_from`–`page_to`. Результат хранится в таблице `chunks`.
5. Каждый этап пишется в журнал (`GET /api/documents/{id}/log`).

Ограничения: таблицы в PDF превращаются в обычные строки, сноски не выделяются, сканы без текстового
слоя не поддерживаются (нужен OCR).

## Курс: просмотр, редактирование, версии

Курс хранится в БД: `course` → `section` → `section_version` (каждая версия раздела — отдельная запись).
Вкладка «Курсы» на сайте открывает курс по адресу `#/courses/<id>`, он доступен после перезапуска.

Что можно делать:

- читать разделы (текст в Markdown, термины, выводы, вопросы для самопроверки с кнопкой «Показать ответ»);
- менять название, описание и цели курса;
- править название и содержимое раздела: каждое сохранение создаёт **новую версию** (`author = USER`), старые остаются;
- смотреть историю версий и возвращаться к любой (копия становится новой текущей версией);
- менять порядок разделов (↑ ↓), добавлять и удалять разделы;
- скачать весь курс одним файлом Markdown;
- «Сгенерировать заново» один раздел через LLM (нужен `LLM_API_KEY`), остальной курс не меняется.

Как получить курс без LLM:

- кнопка **«Создать пример курса»** на вкладке «Курсы»: готовый курс по `MPI.pdf` (файлы `backend/app/courses/example/`);
- кнопка **«Создать курс»** у обработанного документа: черновик по правилам (`app/courses/draft.py`), по одному разделу на фрагмент.

| Метод | Адрес | Действие |
| --- | --- | --- |
| GET | `/api/courses`, `/api/courses/{id}` | список курсов, курс целиком |
| POST | `/api/courses/example` | создать пример курса |
| POST | `/api/documents/{id}/course/draft` | черновик курса из фрагментов |
| PATCH / DELETE | `/api/courses/{id}` | править описание / удалить курс |
| PUT | `/api/courses/{id}/order` | новый порядок разделов |
| POST | `/api/courses/{id}/sections` | добавить раздел |
| GET | `/api/courses/{id}/export.md` | скачать курс в Markdown |
| PATCH / DELETE | `/api/sections/{id}` | править раздел (новая версия) / удалить |
| GET | `/api/sections/{id}/versions` | история версий |
| POST | `/api/sections/{id}/versions/{vid}/restore` | вернуть версию |
| POST | `/api/sections/{id}/regenerate` | заново сгенерировать раздел (LLM) |

## Языковая модель

Работа с моделью целиком в `backend/app/llm/`. Используется любой OpenAI-совместимый API;
по умолчанию OpenRouter с бесплатной моделью. Всё меняется в `.env`, без правки кода:

| Переменная | Назначение |
|---|---|
| `LLM_BASE_URL` | адрес API (`https://openrouter.ai/api/v1`) |
| `LLM_API_KEY` | ключ (`sk-or-...`), в git не попадает |
| `LLM_MODEL` | имя модели, у бесплатных оканчивается на `:free` |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT_S` | параметры генерации |
| `LLM_JSON_ATTEMPTS` | сколько раз просить модель исправить неверный JSON |
| `LLM_JSON_MODE` | просить у API режим «только JSON» (`false`, если модель его не поддерживает) |

Тексты промптов лежат в `backend/app/llm/prompts/*.txt` и правятся отдельно от кода.
Ответ модели разбирается и проверяется по схемам из `backend/app/llm/schemas.py`.
Данные уходят во внешний сервис, поэтому для конфиденциальных документов нужна локальная модель
(поменять `LLM_BASE_URL`, например, на адрес Ollama).

## Тесты

```bash
docker compose up -d --build backend
docker compose exec backend pytest
```

Для тестов настоящая модель и база не нужны: ответы модели подменяются заглушкой.

## Локальная разработка backend

```bash
docker compose up -d postgres flyway
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

```

Запускать из папки `backend/` — настройки читаются из `../.env`.

## Миграции

SQL-файлы лежат в `db/migrations/`, формат имени — `V<номер>__<описание>.sql`.
Уже применённые миграции не изменять — добавлять новую. Применить:

```bash
docker compose run --rm flyway migrate

```

## Остановка

```bash
docker compose down        # остановить
docker compose down -v     # остановить и удалить данные БД

```

