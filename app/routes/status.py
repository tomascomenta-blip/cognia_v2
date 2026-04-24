"""
app/routes/status.py
=====================
Endpoints GET /api/health, /api/status, /api/conceptos
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter
from app.routes.chat import get_cognia

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "cognia-v3"}


@router.get("/status")
def status():
    try:
        ai = get_cognia()
        result = {
            "status": "ok",
            "episodios": 0,
            "conceptos": 0,
            "escala": {},
            "usuarios": [],
        }
        # Episodios
        try:
            from storage.db_pool import db_connect_pooled as db_connect
            with db_connect(ai.db) as conn:
                cur = conn.execute("SELECT COUNT(*) FROM episodic_memory")
                result["episodios"] = cur.fetchone()[0]
                cur2 = conn.execute("SELECT COUNT(DISTINCT label) FROM episodic_memory")
                result["conceptos"] = cur2.fetchone()[0]
        except Exception:
            pass
        # Escala
        try:
            from cognia.scale_manager import get_scale_manager
            st = get_scale_manager().status()
            result["escala"] = {
                "nivel": st.get("level"),
                "nombre": st.get("name"),
                "modelo": st.get("model"),
                "ram_gb": st.get("ram_gb"),
            }
        except Exception:
            pass
        return result
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/conceptos")
def conceptos():
    try:
        ai = get_cognia()
        lista = ai.list_concepts()
        # list_concepts() devuelve string; si hay un metodo mejor lo usamos
        return {"conceptos": lista}
    except Exception as e:
        return {"error": str(e)}
