"""Aplikasi FastAPI Natural Decor Prospecting API."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import BASE_DIR
from .db import initialize_database
from .executor import create_executor
from .routes import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    _app.state.executor = create_executor()
    yield
    _app.state.executor.shutdown(wait=False, cancel_futures=True)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Natural Decor Prospecting API",
        description=(
            "API MVP untuk membuat pencarian bisnis melalui Apify, memeriksa status "
            "job, dan mengambil prospek dalam JSON atau CSV."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    cors_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key", "X-Apify-Token"],
        )

    app.include_router(router, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "natural-decor-prospecting-api"}

    # Sajikan dashboard statis agar cukup satu server.
    # Jangan mount seluruh folder proyek: .env dan leads.db akan ikut terekspos.
    @app.get("/", include_in_schema=False)
    def frontend():
        return _serve_static(Path("static") / "index.html")

    @app.get("/dashboard", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def dashboard():
        return _serve_static(Path("index.html"))

    @app.get("/leads.csv", include_in_schema=False)
    def dashboard_data():
        return _serve_static(Path("leads.csv"))

    return app


def _serve_static(relative_path: Path):
    path = (Path(BASE_DIR) / relative_path).resolve()
    # Tolak path yang keluar dari folder proyek.
    if BASE_DIR not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="File tidak ditemukan.")
    return FileResponse(path)


app = create_app()
