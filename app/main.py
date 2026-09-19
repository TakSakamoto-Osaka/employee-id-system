from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import Base, engine
from .errors import register_exception_handlers
from .routers import auth, batches, companies, employees, imports, reviews

settings = get_settings()

app = FastAPI(title="統一社員番号管理アプリケーション API", version="1.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(employees.router)
app.include_router(reviews.router)
app.include_router(imports.router)
app.include_router(batches.router)


@app.on_event("startup")
def on_startup() -> None:
    # Dev convenience: create tables if they don't exist yet. Production
    # schema changes are managed via Alembic migrations (spec 9.4, backend/alembic).
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
