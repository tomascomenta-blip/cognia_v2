"""
sesiones.py — el corazon del control remoto: REPLs reales como subprocesos.

Cada sesion es `python -m cognia` corriendo con cwd en la carpeta del
proyecto. Un hilo lector bombea stdout a la transcripcion (jsonl en disco,
sobrevive reinicios del servidor) y a las colas de los WebSockets suscritos.
Escribir un mensaje = escribir una linea al stdin del REPL — exactamente lo
que hace el teclado en la terminal, incluidas las respuestas a formularios
(un input() pendiente del REPL consume la siguiente linea).
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_DATOS = Path.home() / ".cognia" / "remoto"
RAIZ_DATOS.mkdir(parents=True, exist_ok=True)
FICHERO_PROYECTOS = RAIZ_DATOS / "proyectos.json"

# Lineas de ruido del arranque que no aportan en el movil.
_RUIDO = ("[OK]", "[WARN]", "[cognia_embedding]", "[>>]",
          "Warning: You are sending unauthenticated", "Loading weights:")

# Escapes ANSI (el REPL colorea el prompt aunque NO_COLOR) y el propio
# "cognia>" que en el movil es redundante.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PROMPT = re.compile(r"^(cognia>\s*)+")


def _limpiar(linea: str) -> str:
    linea = _ANSI.sub("", linea)
    linea = _PROMPT.sub("", linea)
    # lineas que son solo dibujo de caja del banner
    if linea and all(c in "─│┌┐└┘├┤┬┴╭╮╰╯═║ •·" for c in linea.strip()):
        return ""
    return linea.rstrip()


def _python_cognia() -> list[str]:
    """El interprete que corre el REPL: el mismo venv del servidor."""
    return [sys.executable, "-m", "cognia"]


# ── Proyectos: carpetas donde se abre el CLI ───────────────────────────────

def cargar_proyectos() -> list[dict]:
    try:
        return json.loads(FICHERO_PROYECTOS.read_text(encoding="utf-8"))
    except Exception:
        return []


def guardar_proyectos(proyectos: list[dict]) -> None:
    FICHERO_PROYECTOS.write_text(
        json.dumps(proyectos, indent=2, ensure_ascii=False), encoding="utf-8")


def registrar_proyecto(ruta: str) -> dict:
    """Alta (o reuso) de un proyecto por su carpeta. Nombre = la carpeta."""
    p = Path(ruta).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"No es una carpeta: {p}")
    proyectos = cargar_proyectos()
    for pr in proyectos:
        if Path(pr["ruta"]).resolve() == p:
            return pr
    pr = {"id": uuid.uuid4().hex[:8], "nombre": p.name or str(p),
          "ruta": str(p), "creado": time.strftime("%Y-%m-%d %H:%M")}
    proyectos.append(pr)
    guardar_proyectos(proyectos)
    (RAIZ_DATOS / pr["id"]).mkdir(exist_ok=True)
    return pr


# ── Sesiones ───────────────────────────────────────────────────────────────

@dataclass
class Sesion:
    id: str
    proyecto_id: str
    ruta_proyecto: str
    titulo: str
    proc: subprocess.Popen | None = None
    suscriptores: list = field(default_factory=list)   # [queue.Queue]
    lock: threading.Lock = field(default_factory=threading.Lock)

    # ── persistencia ──
    @property
    def fichero(self) -> Path:
        d = RAIZ_DATOS / self.proyecto_id
        d.mkdir(exist_ok=True)
        return d / f"{self.id}.jsonl"

    def anotar(self, quien: str, texto: str) -> dict:
        evento = {"t": time.strftime("%H:%M:%S"), "quien": quien,
                  "texto": texto}
        with self.fichero.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        with self.lock:
            for q in list(self.suscriptores):
                try:
                    q.put_nowait(evento)
                except Exception:
                    pass
        return evento

    def transcripcion(self, limite: int = 400) -> list[dict]:
        try:
            lineas = self.fichero.read_text(encoding="utf-8").splitlines()
            return [json.loads(l) for l in lineas[-limite:]]
        except Exception:
            return []

    # ── el subproceso REPL ──
    def viva(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def arrancar(self) -> None:
        if self.viva():
            return
        # PYTHONPATH al repo: el cwd del REPL es la carpeta del PROYECTO, no
        # el repo, y en modo desarrollo `python -m cognia` no resolveria el
        # paquete (medido: "No module named cognia" en la primera sesion).
        raiz_repo = str(Path(__file__).resolve().parent.parent.parent)
        pp = os.environ.get("PYTHONPATH", "")
        env = dict(os.environ,
                   PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                   NO_COLOR="1", TERM="dumb",
                   PYTHONPATH=(raiz_repo + (os.pathsep + pp if pp else "")))
        self.proc = subprocess.Popen(
            _python_cognia(), cwd=self.ruta_proyecto,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=env)
        threading.Thread(target=self._bombear, daemon=True,
                         name=f"remoto-{self.id}").start()
        self.anotar("sistema", f"sesion arrancada en {self.ruta_proyecto}")

    def _bombear(self) -> None:
        """Hilo lector: stdout del REPL -> transcripcion + suscriptores."""
        try:
            for linea in self.proc.stdout:      # type: ignore[union-attr]
                linea = _limpiar(linea.rstrip("\n"))
                if not linea.strip():
                    continue
                if any(linea.startswith(r) for r in _RUIDO):
                    continue
                self.anotar("cognia", linea)
        except Exception:
            pass
        finally:
            self.anotar("sistema", "sesion terminada")

    def enviar(self, texto: str) -> None:
        """Una linea al stdin del REPL: mensaje, /comando o respuesta a un
        formulario (input() pendiente) — igual que teclear en la terminal."""
        if not self.viva():
            self.arrancar()
            # darle un momento al arranque antes del primer mensaje
            time.sleep(1.0)
        self.anotar("usuario", texto)
        try:
            self.proc.stdin.write(texto + "\n")   # type: ignore[union-attr]
            self.proc.stdin.flush()               # type: ignore[union-attr]
        except Exception as e:
            self.anotar("sistema", f"no pude enviar: {e}")

    def parar(self) -> None:
        if self.viva():
            try:
                self.enviar("/salir")
                self.proc.wait(timeout=8)         # type: ignore[union-attr]
            except Exception:
                try:
                    self.proc.kill()              # type: ignore[union-attr]
                except Exception:
                    pass


class GestorSesiones:
    """Registro en memoria de sesiones vivas + indice en disco."""

    def __init__(self):
        self._sesiones: dict[str, Sesion] = {}
        self._lock = threading.Lock()

    def indice(self, proyecto_id: str) -> list[dict]:
        d = RAIZ_DATOS / proyecto_id
        salida = []
        if d.is_dir():
            for f in sorted(d.glob("*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True):
                sid = f.stem
                s = self._sesiones.get(sid)
                titulo = sid
                try:
                    primera = json.loads(
                        f.read_text(encoding="utf-8").splitlines()[0])
                    titulo = primera.get("titulo") or sid
                except Exception:
                    pass
                salida.append({
                    "id": sid, "titulo": titulo,
                    "viva": bool(s and s.viva()),
                    "modificada": time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.localtime(f.stat().st_mtime)),
                })
        return salida

    def crear(self, proyecto: dict, titulo: str = "") -> Sesion:
        sid = time.strftime("%Y%m%d-%H%M%S")
        s = Sesion(id=sid, proyecto_id=proyecto["id"],
                   ruta_proyecto=proyecto["ruta"],
                   titulo=titulo or f"Sesion {sid}")
        with self._lock:
            self._sesiones[sid] = s
        # primera linea del jsonl lleva el titulo (lo lee el indice)
        with s.fichero.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M:%S"),
                                "quien": "meta", "texto": "",
                                "titulo": s.titulo},
                               ensure_ascii=False) + "\n")
        s.arrancar()
        return s

    def obtener(self, proyecto: dict, sid: str) -> Sesion:
        with self._lock:
            s = self._sesiones.get(sid)
            if s is None:
                s = Sesion(id=sid, proyecto_id=proyecto["id"],
                           ruta_proyecto=proyecto["ruta"], titulo=sid)
                self._sesiones[sid] = s
        return s

    def borrar(self, proyecto_id: str, sid: str) -> bool:
        with self._lock:
            s = self._sesiones.pop(sid, None)
        if s:
            s.parar()
        f = RAIZ_DATOS / proyecto_id / f"{sid}.jsonl"
        try:
            f.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def vivas(self) -> list[dict]:
        """Los 'monitores': que REPLs corren ahora mismo y donde."""
        with self._lock:
            return [{"sesion": s.id, "proyecto": s.proyecto_id,
                     "ruta": s.ruta_proyecto, "pid": s.proc.pid}
                    for s in self._sesiones.values() if s.viva()]
