"""
app/main.py
===========
Punto de entrada FastAPI para Cognia v3 - Fase 7A
"""

import os
import sys

# Asegurar que el root del repo esté en el path para que Cognia importe bien
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# config.env instalado ANTES de importar rutas que construyen Cognia()
# (fix auditoria 2026-07-15: uvicorn app.main:app no pasaba por
# cognia.__main__ y el backend corria sin la config de ~/.cognia)
try:
    from cognia.first_run import apply_config
    apply_config()
except Exception:
    pass

from app.routes.chat import router as chat_router
from app.routes.status import router as status_router
from app.routes.user_data import router as user_data_router

app = FastAPI(
    title="Cognia v3 API",
    description="API REST para el sistema de IA Cognia v3",
    version="7.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # localhost Y 127.0.0.1: los servers bindean 127.0.0.1 y el estandar
    # post-bug-CSP del repo es 127.0.0.1 — un front servido desde ahi tenia
    # el Origin bloqueado (cazado 2026-07-16).
    allow_origins=["http://localhost:3000", "http://localhost:8765",
                   "http://127.0.0.1:3000", "http://127.0.0.1:8765"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(status_router, prefix="/api")
app.include_router(user_data_router, prefix="/api")

# Servir frontend estático
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(static_dir, "index.html"))

try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app)
except ImportError:
    pass
