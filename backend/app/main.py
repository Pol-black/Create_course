from fastapi import FastAPI

from app.api import health

app = FastAPI(title="Прототип API")
app.include_router(health.router)
