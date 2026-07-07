"""Estado compartido de la oficina: tareas jerárquicas + control externo.

Una sola fuente de verdad, thread-safe, persistida a JSON con escritura
atómica (temp + os.replace, mismo patrón que tool_synthesis._save_manifest).
El motor la muta; el server la lee y le inyecta solicitudes de control
(detener / pausar / reanudar / editar) que el motor honra entre pasos.
"""
import json
import os
import threading
import time
import uuid

NIVELES = ("jefe", "director", "trabajador")
ESTADOS = ("pendiente", "en_curso", "pausada", "detenida", "hecha", "fallida")
_MAX_EVENTOS = 200


def _ahora() -> str:
    return time.strftime("%H:%M:%S")


class Oficina:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self.data = {"metas": [], "tareas": {}, "orden": []}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # estado corrupto -> se arranca limpio (queda el .json viejo)

    # ── persistencia ──
    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ── creación ──
    def nueva_meta(self, texto: str) -> str:
        """Registra una meta del usuario; el motor la levanta y crea al jefe."""
        with self._lock:
            mid = "meta-" + uuid.uuid4().hex[:8]
            self.data["metas"].append({"id": mid, "texto": texto.strip(),
                                       "estado": "pendiente", "creada": _ahora()})
            self._save()
            return mid

    def meta_pendiente(self):
        with self._lock:
            for m in self.data["metas"]:
                if m["estado"] == "pendiente":
                    return dict(m)
            return None

    def set_meta_estado(self, mid: str, estado: str, resultado: str = None) -> None:
        with self._lock:
            for m in self.data["metas"]:
                if m["id"] == mid:
                    m["estado"] = estado
                    if resultado is not None:
                        m["resultado"] = resultado[:2000]
            self._save()

    def crear_tarea(self, nivel: str, titulo: str, detalle: str,
                    padre: str = None, rol: str = None, meta: str = None) -> str:
        assert nivel in NIVELES, nivel
        with self._lock:
            tid = f"{nivel[:4]}-{uuid.uuid4().hex[:6]}"
            self.data["tareas"][tid] = {
                "id": tid, "nivel": nivel, "titulo": titulo[:120],
                "detalle": detalle, "padre": padre, "rol": rol, "meta": meta,
                "estado": "pendiente", "solicitud": None, "resultado": None,
                "creada": _ahora(), "eventos": []}
            self.data["orden"].append(tid)
            self._save()
            return tid

    # ── mutación (motor) ──
    def set_estado(self, tid: str, estado: str, resultado: str = None) -> None:
        assert estado in ESTADOS, estado
        with self._lock:
            t = self.data["tareas"][tid]
            t["estado"] = estado
            if resultado is not None:
                t["resultado"] = str(resultado)[:2000]
            self._save()

    def evento(self, tid: str, msg: str) -> None:
        with self._lock:
            ev = self.data["tareas"][tid]["eventos"]
            ev.append({"t": _ahora(), "msg": str(msg)[:300]})
            del ev[:-_MAX_EVENTOS]
            self._save()

    # ── control externo (server -> motor) ──
    def solicitar(self, tid: str, accion: str) -> bool:
        """detener|pausar|reanudar sobre una tarea. El motor la honra en el
        próximo chequeo (y a mitad de trabajo vía el hook de print)."""
        if accion not in ("detener", "pausar", "reanudar"):
            return False
        with self._lock:
            t = self.data["tareas"].get(tid)
            if t is None or t["estado"] in ("hecha", "fallida", "detenida"):
                return False
            if accion == "reanudar":
                if t["estado"] == "pausada":
                    t["estado"] = "pendiente"
                t["solicitud"] = None
            else:
                t["solicitud"] = accion
                if t["estado"] == "pendiente" and accion == "pausar":
                    t["estado"] = "pausada"
                    t["solicitud"] = None
                if t["estado"] == "pendiente" and accion == "detener":
                    t["estado"] = "detenida"
                    t["solicitud"] = None
            self._save()
            return True

    def editar(self, tid: str, detalle: str) -> bool:
        """Editar el detalle de una tarea que aún no corrió."""
        with self._lock:
            t = self.data["tareas"].get(tid)
            if t is None or t["estado"] not in ("pendiente", "pausada"):
                return False
            t["detalle"] = detalle.strip()
            t["eventos"].append({"t": _ahora(), "msg": "[editada por el usuario]"})
            self._save()
            return True

    def control(self, tid: str) -> str:
        """Qué pide el usuario para esta tarea: '' | 'detener' | 'pausar'."""
        with self._lock:
            t = self.data["tareas"].get(tid) or {}
            if t.get("estado") in ("detenida", "pausada"):
                return t["estado"][:7] if t["estado"] == "detenida" else "pausar"
            return t.get("solicitud") or ""

    def consumir_solicitud(self, tid: str) -> None:
        with self._lock:
            if tid in self.data["tareas"]:
                self.data["tareas"][tid]["solicitud"] = None
                self._save()

    # ── lectura (server) ──
    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self.data))

    def hijos(self, tid: str) -> list:
        with self._lock:
            return [dict(t) for k in self.data["orden"]
                    for t in [self.data["tareas"][k]] if t["padre"] == tid]
