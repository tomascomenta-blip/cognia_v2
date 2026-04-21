"""
backup_manager.py — ZONA PROTEGIDA
====================================
Gestiona copias de seguridad de cognia.py.
Cognia no tiene acceso directo a este módulo.
Solo web_app.py lo llama.
"""

import os
import shutil
import glob
from datetime import datetime
import config


def save_backup(reason: str = "manual") -> dict:
    """
    Crea un backup de cognia.py con timestamp.
    Retorna info del backup creado.
    """
    os.makedirs(config.BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"cognia_{timestamp}_{reason}.py"
    dest = os.path.join(config.BACKUP_DIR, filename)

    src = os.path.join(os.path.dirname(__file__), "cognia.py")
    shutil.copy2(src, dest)

    # Rotar backups si excede el máximo
    _rotate_backups()

    return {
        "backup": filename,
        "timestamp": timestamp,
        "reason": reason,
        "size_kb": round(os.path.getsize(dest) / 1024, 1)
    }


def list_backups() -> list:
    """Lista todos los backups disponibles, del más nuevo al más viejo."""
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    pattern = os.path.join(config.BACKUP_DIR, "cognia_*.py")
    files = sorted(glob.glob(pattern), reverse=True)

    result = []
    for f in files:
        name = os.path.basename(f)
        stat = os.stat(f)
        result.append({
            "filename": name,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        })
    return result


def restore_backup(filename: str) -> dict:
    """
    Restaura un backup específico a cognia.py.
    Primero hace un backup del estado actual como 'pre_restore'.
    """
    backup_path = os.path.join(config.BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
        return {"error": f"Backup '{filename}' no encontrado"}

    # Seguridad: verificar que el filename no tiene path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return {"error": "Nombre de archivo inválido"}

    # Backup del estado actual antes de restaurar
    save_backup(reason="pre_restore")

    src = os.path.join(os.path.dirname(__file__), "cognia.py")
    shutil.copy2(backup_path, src)

    return {"status": "restaurado", "from": filename}


def _rotate_backups():
    """Elimina backups más viejos si se supera MAX_BACKUPS."""
    pattern = os.path.join(config.BACKUP_DIR, "cognia_*.py")
    files = sorted(glob.glob(pattern))
    while len(files) > config.MAX_BACKUPS:
        os.remove(files.pop(0))
