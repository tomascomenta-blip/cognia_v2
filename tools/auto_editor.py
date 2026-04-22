"""
auto_editor.py — Auto-edición segura para Cognia v3
=====================================================
Permite a Cognia proponer mejoras a su propio código
con validación, backup automático y funciones protegidas.

Endpoints que agrega a web_app.py:
  POST /api/propose_edit    — Cognia propone un cambio
  POST /api/apply_edit      — Tutor aprueba y aplica
  GET  /api/pending_edits   — Ver propuestas pendientes
  GET  /api/edit_history    — Historial de ediciones

Uso standalone:
  python auto_editor.py --listar
  python auto_editor.py --aplicar <id>
  python auto_editor.py --revertir
"""

import os
import sys
import json
import ast
import shutil
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COGNIA_PATH = os.path.join(BASE_DIR, "cognia_v3.py")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
EDITS_DB = os.path.join(BASE_DIR, "edits.db")

# ── Funciones que NUNCA pueden ser modificadas ─────────────────────────
PROTECTED = {
    "init_db", "DB_PATH", "text_to_vector", "cosine_similarity",
    "vec_dot", "vec_norm", "EpisodicMemory.store", "SemanticMemory.update_concept"
}

# ── Base de datos de propuestas ────────────────────────────────────────

def init_edits_db():
    conn = sqlite3.connect(EDITS_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS edit_proposals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            description TEXT NOT NULL,
            old_code    TEXT NOT NULL,
            new_code    TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            applied_at  TEXT,
            backup_file TEXT,
            justification TEXT
        )
    """)
    conn.commit()
    conn.close()


# ── Validación de seguridad ────────────────────────────────────────────

def validar_codigo(nuevo_codigo: str) -> dict:
    """
    Valida que el nuevo código sea seguro.
    Retorna {"ok": True} o {"ok": False, "reason": "..."}
    """
    # 1. Parseable como Python válido
    try:
        ast.parse(nuevo_codigo)
    except SyntaxError as e:
        return {"ok": False, "reason": f"SyntaxError: {e}"}

    # 2. No toca funciones protegidas
    for fn in PROTECTED:
        if fn in nuevo_codigo and f"def {fn}" in nuevo_codigo:
            return {"ok": False, "reason": f"Intenta redefinir función protegida: {fn}"}

    # 3. No tiene imports peligrosos
    peligrosos = ["subprocess", "os.system", "eval(", "exec(", "__import__"]
    for p in peligrosos:
        if p in nuevo_codigo:
            return {"ok": False, "reason": f"Contiene patrón peligroso: '{p}'"}

    # 4. Tamaño razonable (máx 3000 chars por edición)
    if len(nuevo_codigo) > 3000:
        return {"ok": False, "reason": f"Bloque demasiado grande ({len(nuevo_codigo)} chars, máx 3000)"}

    return {"ok": True}


# ── Backup ─────────────────────────────────────────────────────────────

def hacer_backup(razon: str = "pre_edit") -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"cognia_v3_{ts}_{razon}.py"
    destino = os.path.join(BACKUP_DIR, nombre)
    shutil.copy2(COGNIA_PATH, destino)
    return nombre


# ── API de propuestas ──────────────────────────────────────────────────

def proponer_edicion(
    descripcion: str,
    old_code: str,
    new_code: str,
    justificacion: str = ""
) -> dict:
    """
    Registra una propuesta de edición para revisión del tutor.
    NO aplica nada todavía.
    """
    init_edits_db()

    # Validar
    val = validar_codigo(new_code)
    if not val["ok"]:
        return {"error": val["reason"]}

    # Verificar que old_code existe en cognia_v3.py
    with open(COGNIA_PATH, "r", encoding="utf-8") as f:
        contenido_actual = f.read()

    if old_code not in contenido_actual:
        return {"error": "El código a reemplazar no se encontró en cognia_v3.py"}

    conn = sqlite3.connect(EDITS_DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO edit_proposals
        (timestamp, description, old_code, new_code, justification)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), descripcion, old_code, new_code, justificacion))
    edit_id = c.lastrowid
    conn.commit()
    conn.close()

    return {
        "id": edit_id,
        "status": "pending",
        "message": f"Propuesta #{edit_id} registrada. El tutor debe aprobarla con /api/apply_edit"
    }


def aplicar_edicion(edit_id: int) -> dict:
    """Aplica una propuesta aprobada por el tutor."""
    init_edits_db()
    conn = sqlite3.connect(EDITS_DB)
    c = conn.cursor()
    c.execute("SELECT * FROM edit_proposals WHERE id=?", (edit_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return {"error": f"Propuesta #{edit_id} no encontrada"}

    cols = ["id", "timestamp", "description", "old_code", "new_code",
            "status", "applied_at", "backup_file", "justification"]
    propuesta = dict(zip(cols, row))

    if propuesta["status"] != "pending":
        return {"error": f"Propuesta ya está en estado: {propuesta['status']}"}

    # Backup antes de aplicar
    backup = hacer_backup(f"pre_edit_{edit_id}")

    # Aplicar el cambio
    with open(COGNIA_PATH, "r", encoding="utf-8") as f:
        contenido = f.read()

    if propuesta["old_code"] not in contenido:
        return {"error": "El código a reemplazar ya no existe (¿ya fue aplicado?)"}

    nuevo_contenido = contenido.replace(propuesta["old_code"], propuesta["new_code"], 1)

    # Validar que el archivo completo sigue siendo Python válido
    try:
        ast.parse(nuevo_contenido)
    except SyntaxError as e:
        return {"error": f"El archivo resultante tiene SyntaxError: {e}"}

    with open(COGNIA_PATH, "w", encoding="utf-8") as f:
        f.write(nuevo_contenido)

    # Actualizar estado en DB
    conn = sqlite3.connect(EDITS_DB)
    c = conn.cursor()
    c.execute("""
        UPDATE edit_proposals
        SET status='applied', applied_at=?, backup_file=?
        WHERE id=?
    """, (datetime.now().isoformat(), backup, edit_id))
    conn.commit()
    conn.close()

    return {
        "status": "applied",
        "backup": backup,
        "message": f"✅ Edición #{edit_id} aplicada. Backup: {backup}. Reinicia Flask para activar."
    }


def listar_propuestas(status: str = None) -> list:
    init_edits_db()
    conn = sqlite3.connect(EDITS_DB)
    c = conn.cursor()
    if status:
        c.execute("SELECT id, timestamp, description, status FROM edit_proposals WHERE status=?", (status,))
    else:
        c.execute("SELECT id, timestamp, description, status FROM edit_proposals ORDER BY id DESC LIMIT 20")
    rows = [{"id": r[0], "timestamp": r[1], "description": r[2], "status": r[3]}
            for r in c.fetchall()]
    conn.close()
    return rows


def revertir_ultima() -> dict:
    """Revierte al backup más reciente."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = sorted([
        f for f in os.listdir(BACKUP_DIR)
        if f.startswith("cognia_v3_") and f.endswith(".py")
    ], reverse=True)

    if not backups:
        return {"error": "No hay backups disponibles"}

    ultimo = backups[0]
    hacer_backup("pre_revert")
    shutil.copy2(os.path.join(BACKUP_DIR, ultimo), COGNIA_PATH)
    return {"status": "revertido", "desde": ultimo,
            "message": f"✅ Revertido a {ultimo}. Reinicia Flask."}


# ── Flask endpoints (para agregar a web_app.py) ────────────────────────

def register_routes(app):
    """
    Llama esto desde web_app.py para registrar los endpoints de auto-edición.
    
    En web_app.py agrega:
        from auto_editor import register_routes
        register_routes(app)
    """
    from flask import request, jsonify, session

    @app.route("/api/propose_edit", methods=["POST"])
    def api_propose_edit():
        # Solo el tutor autenticado puede proponer
        data = request.get_json()
        password = data.get("password", "")
        try:
            from config import TUTOR_PASSWORD
        except ImportError:
            TUTOR_PASSWORD = os.environ.get("COGNIA_PASSWORD", "Samantha123")

        if password != TUTOR_PASSWORD:
            return jsonify({"error": "Autenticación requerida"})

        result = proponer_edicion(
            descripcion=data.get("description", "Sin descripción"),
            old_code=data.get("old_code", ""),
            new_code=data.get("new_code", ""),
            justificacion=data.get("justification", "")
        )
        return jsonify(result)

    @app.route("/api/apply_edit", methods=["POST"])
    def api_apply_edit():
        data = request.get_json()
        password = data.get("password", "")
        try:
            from config import TUTOR_PASSWORD
        except ImportError:
            TUTOR_PASSWORD = os.environ.get("COGNIA_PASSWORD", "Samantha123")

        if password != TUTOR_PASSWORD:
            return jsonify({"error": "Autenticación requerida"})

        edit_id = data.get("edit_id")
        if not edit_id:
            return jsonify({"error": "edit_id requerido"})

        result = aplicar_edicion(int(edit_id))
        return jsonify(result)

    @app.route("/api/pending_edits")
    def api_pending_edits():
        return jsonify(listar_propuestas("pending"))

    @app.route("/api/edit_history")
    def api_edit_history():
        return jsonify(listar_propuestas())

    @app.route("/api/revert_edit", methods=["POST"])
    def api_revert_edit():
        data = request.get_json()
        password = data.get("password", "")
        try:
            from config import TUTOR_PASSWORD
        except ImportError:
            TUTOR_PASSWORD = os.environ.get("COGNIA_PASSWORD", "Samantha123")

        if password != TUTOR_PASSWORD:
            return jsonify({"error": "Autenticación requerida"})

        return jsonify(revertir_ultima())


# ── CLI standalone ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Auto-editor de Cognia")
    parser.add_argument("--listar", action="store_true", help="Listar propuestas pendientes")
    parser.add_argument("--aplicar", type=int, metavar="ID", help="Aplicar propuesta por ID")
    parser.add_argument("--revertir", action="store_true", help="Revertir al último backup")
    parser.add_argument("--historial", action="store_true", help="Ver historial completo")

    args = parser.parse_args()

    if args.listar:
        props = listar_propuestas("pending")
        if not props:
            print("No hay propuestas pendientes.")
        for p in props:
            print(f"  #{p['id']} [{p['timestamp'][:19]}] {p['description']}")

    elif args.aplicar:
        resultado = aplicar_edicion(args.aplicar)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))

    elif args.revertir:
        resultado = revertir_ultima()
        print(json.dumps(resultado, indent=2, ensure_ascii=False))

    elif args.historial:
        props = listar_propuestas()
        for p in props:
            print(f"  #{p['id']} [{p['status']:8}] {p['description']}")

    else:
        parser.print_help()
