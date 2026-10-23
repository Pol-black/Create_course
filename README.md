# Prototype

Backend на FastAPI + PostgreSQL, миграции через Flyway, запуск через Docker Compose.

## Требования

- Docker и Docker Compose
- Python 3.12 - только для локального запуска backend без Docker

## Запуск

```bash
git clone <url> && cd Prototype
cp .env.example .env        # при необходимости поменять пароль, порты, LOG_LEVEL
docker compose up -d --build
docker compose ps
```

`postgres` и `backend` должны быть `healthy`, `flyway` — `exited (0)`.

После изменений в `backend/` пересобрать образ:

```bash
docker compose up -d --build backend
```

## Проверка

| Адрес | Назначение |
|---|---|
| http://localhost:8000/api/health | Состояние сервиса и БД |
| http://localhost:8000/docs | Swagger UI |

Скрипты проверки моделей и журнала обработки:

```bash
docker compose exec backend python -m app.scripts.check_models
docker compose exec backend python -m app.scripts.check_logging
```

Логи: `docker compose logs -f backend`

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
