# Create_course

Backend на FastAPI + PostgreSQL (`pgvector`), фронтенд на Vue 3 + Vite, миграции через Flyway, запуск через Docker Compose.
Сервис, который превращает документы (PDF, DOCX, TXT) в обучающий курс с помощью LLM (через RAG и семантический поиск).

## Требования

* Docker и Docker Compose
* Python 3.12 — только для локального запуска backend без Docker
* Node.js (LTS) — только для локального запуска frontend без Docker

## Запуск

```bash
git clone https://github.com/Pol-black/Create_course.git && cd Create_course
cp .env.example .env        # поменять пароль БД и вписать ключ Groq в LLM_API_KEY
docker compose up -d --build
docker compose ps

```

`postgres`, `backend` и `frontend` должны быть `healthy`, `flyway` — `exited (0)`.
*Примечание: при первом запуске бэкенд может скачивать локальную модель для эмбеддингов (около 100-300 МБ), поэтому старт может занять чуть больше времени.*

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

Логи: `docker compose logs -f backend` (или `frontend`)

## Обработка документа

Загрузка только сохраняет файл (статус `UPLOADED`). Обработка запускается кнопкой «Обработать»
(`POST /api/documents/{id}/process`, ответ 202) и идёт в фоне, страница опрашивает статус.

Алгоритм:

1. **Извлечение.** PDF: `pdftotext` из poppler-utils, размер и жирность шрифта через pypdf как подсказки для заголовков; если poppler нет, используется pypdf. DOCX: абзацы, списки и таблицы, стили заголовков. TXT: определение кодировки.
2. **Очистка.** Удаляются колонтитулы и номера страниц, оглавление, соединяются переносы слов и строки, нормализуются пробелы.
3. **Заголовки.** По шрифту, стилям DOCX, `#` в TXT, нумерации, словам «Глава», ЗАГЛАВНЫМ.
4. **Деление на фрагменты** по заголовкам (`CHUNK_TARGET_WORDS`, `CHUNK_MAX_WORDS`, `CHUNK_MIN_WORDS`). Результат хранится в таблице `chunks`.
5. **Векторизация (Эмбеддинги).** Текст фрагментов переводится в векторы с помощью локальной модели (`fastembed`) и сохраняется в PostgreSQL с использованием расширения `pgvector` для семантического поиска (RAG).
6. Каждый этап пишется в журнал (`GET /api/documents/{id}/log`).

## Курс: просмотр, редактирование, версии

Курс хранится в БД: `course` → `section` → `section_version` (каждая версия раздела — отдельная запись, строгие проверки схемы на NOT NULL и JSONB). Вкладка «Курсы» на сайте открывает курс по адресу `#/courses/<id>`.

Что можно делать:

* читать разделы (текст в Markdown, термины, выводы, вопросы для самопроверки);
* менять название, описание и цели курса;
* править название и содержимое раздела: каждое сохранение создаёт **новую версию** (`author = USER`), старые остаются;
* смотреть историю версий и возвращаться к любой (копия становится новой текущей версией);
* менять порядок разделов (↑ ↓), добавлять и удалять разделы;
* скачать весь курс одним файлом Markdown;
* «Сгенерировать заново» один раздел через LLM (нужен `LLM_API_KEY`), база данных подберет релевантные куски текста (RAG), остальной курс не меняется. Бэкенд проверяет ответы на галлюцинации (наличие терминов/ссылок на несуществующие `chunk_id`).

| Метод | Адрес | Действие |
| --- | --- | --- |
| GET | `/api/courses`, `/api/courses/{id}` | список курсов, курс целиком |
| PATCH / DELETE | `/api/courses/{id}` | править описание / удалить курс |
| PUT | `/api/courses/{id}/order` | новый порядок разделов |
| POST | `/api/courses/{id}/sections` | добавить раздел |
| GET | `/api/courses/{id}/export.md` | скачать курс в Markdown |
| PATCH / DELETE | `/api/sections/{id}` | править раздел (новая версия) / удалить |
| GET | `/api/sections/{id}/versions` | история версий |
| POST | `/api/sections/{id}/versions/{vid}/restore` | вернуть версию |
| POST | `/api/sections/{id}/regenerate` | заново сгенерировать раздел (LLM) |

## Языковая модель и Эмбеддинги

Работа с генеративной моделью настроена на **Groq** для максимальной скорости (или любой другой OpenAI-совместимый API). Эмбеддинги (векторы) генерируются **локально** на CPU с помощью библиотеки `fastembed`, что экономит внешние токены и не требует ключей.

Всё меняется в `.env`:

| Переменная | Назначение |
| --- | --- |
| `LLM_BASE_URL` | адрес API (для Groq: `[https://api.groq.com/openai/v1](https://api.groq.com/openai/v1)`) |
| `LLM_API_KEY` | ключ от провайдера LLM |
| `LLM_MODEL` | имя модели (например: `llama3-70b-8192` или `mixtral-8x7b-32768`) |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT_S` | параметры генерации |
| `LLM_JSON_ATTEMPTS` | сколько раз просить модель исправить неверный JSON |
| `LLM_JSON_MODE` | просить у API режим «только JSON» |

Тексты промптов лежат в `backend/app/llm/prompts/*.txt`. В коде реализована логика повторных попыток (retries) на случай исчерпания лимитов API (Rate Limits).

## Тесты

Тесты API интегрированы с базой данных для проверки реального поведения сервисного слоя, транзакций и ограничений ORM.

```bash
# Запуск всех тестов
docker compose exec backend pytest

# Запуск тестов конкретного файла (например, БД и роуты курсов)
docker compose exec backend pytest tests/test_courses_db.py

# Запуск одного конкретного теста
docker compose exec backend pytest tests/test_courses_db.py::test_course_survives_reload

```

*Примечание: Ответы внешней LLM в тестах подменяются заглушкой (mock), но для корректного прогона требуется работающий контейнер PostgreSQL.*

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