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
        self.seq = 0  # monótono en memoria: sube en cada _save (el SSE lo pollea)
        self.data = {"metas": [], "tareas": {}, "orden": []}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # estado corrupto -> se arranca limpio (queda el .json viejo)

    # ── persistencia ──
    def _save(self) -> None:
        self.seq += 1
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ── creación ──
    def nueva_meta(self, texto: str, despierta_ts: float = None) -> str:
        """Registra una meta del usuario; el motor la levanta y crea al jefe.
        Con despierta_ts (epoch s futuro) la meta queda PROGRAMADA: el motor
        no la toma hasta esa hora, y se crea YA el jefe dormido (visible en
        la oficina 3D durmiendo en su cama hasta que se despierte)."""
        with self._lock:
            mid = "meta-" + uuid.uuid4().hex[:8]
            meta = {"id": mid, "texto": texto.strip(),
                    "estado": "pendiente", "creada": _ahora()}
            if despierta_ts and despierta_ts > time.time():
                meta["despierta_ts"] = float(despierta_ts)
            self.data["metas"].append(meta)
            self._save()
        if meta.get("despierta_ts"):
            self.crear_tarea("jefe", f"META programada: {texto.strip()[:70]}",
                             texto.strip(), meta=mid,
                             despierta_ts=meta["despierta_ts"])
        return mid

    def meta_pendiente(self):
        """La próxima meta lista para correr (las programadas a futuro NO)."""
        with self._lock:
            ahora = time.time()
            for m in self.data["metas"]:
                if m["estado"] != "pendiente":
                    continue
                if m.get("despierta_ts") and m["despierta_ts"] > ahora:
                    continue
                return dict(m)
            return None

    def jefe_de_meta(self, mid: str):
        """Id del jefe pre-creado (meta programada) aún pendiente, o None."""
        with self._lock:
            for tid in self.data["orden"]:
                t = self.data["tareas"][tid]
                if (t["nivel"] == "jefe" and t.get("meta") == mid
                        and t["estado"] == "pendiente"):
                    return tid
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
                    padre: str = None, rol: str = None, meta: str = None,
                    despierta_ts: float = None) -> str:
        assert nivel in NIVELES, nivel
        with self._lock:
            tid = f"{nivel[:4]}-{uuid.uuid4().hex[:6]}"
            self.data["tareas"][tid] = {
                "id": tid, "nivel": nivel, "titulo": titulo[:120],
                "detalle": detalle, "padre": padre, "rol": rol, "meta": meta,
                "estado": "pendiente", "solicitud": None, "resultado": None,
                "despierta_ts": float(despierta_ts) if despierta_ts else None,
                "creada": _ahora(), "creada_ts": time.time(), "eventos": []}
            self.data["orden"].append(tid)
            self._save()
            return tid

    # ── mutación (motor) ──
    def set_estado(self, tid: str, estado: str, resultado: str = None) -> None:
        assert estado in ESTADOS, estado
        with self._lock:
            t = self.data["tareas"][tid]
            t["estado"] = estado
            if estado == "en_curso":
                t["inicio_ts"] = time.time()
            elif estado in ("hecha", "fallida", "detenida"):
                t["fin_ts"] = time.time()
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
                    t["fin_ts"] = time.time()
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

    def prioridad(self, tid: str, delta: int) -> bool:
        """Mueve el tid un lugar en data.orden (-1 sube, +1 baja). Solo pendientes."""
        if delta not in (-1, 1):
            return False
        with self._lock:
            t = self.data["tareas"].get(tid)
            if t is None or t["estado"] != "pendiente":
                return False
            orden = self.data["orden"]
            i = orden.index(tid)
            j = i + delta
            if j < 0 or j >= len(orden):
                return False
            orden[i], orden[j] = orden[j], orden[i]
            self._save()
            return True

    def despertar(self, oid: str, despierta_ts=None) -> bool:
        """Edita la hora de despertar de una meta programada o una tarea
        dormida (el hover de la oficina 3D la muestra; acá se cambia).
        despierta_ts None o en el pasado = despertar AHORA. Sobre una meta
        ('meta-...') actualiza también su jefe pre-creado."""
        ts = float(despierta_ts) if despierta_ts else None
        if ts is not None and ts <= time.time():
            ts = None
        with self._lock:
            if oid.startswith("meta-"):
                meta = next((m for m in self.data["metas"] if m["id"] == oid), None)
                if meta is None or meta["estado"] != "pendiente":
                    return False
                if ts is None:
                    meta.pop("despierta_ts", None)
                else:
                    meta["despierta_ts"] = ts
                for t in self.data["tareas"].values():
                    if (t["nivel"] == "jefe" and t.get("meta") == oid
                            and t["estado"] == "pendiente"):
                        t["despierta_ts"] = ts
                        t["eventos"].append({"t": _ahora(), "msg":
                                             f"[despertar editado: {ts or 'ahora'}]"})
                self._save()
                return True
            t = self.data["tareas"].get(oid)
            if t is None or t["estado"] not in ("pendiente", "pausada"):
                return False
            t["despierta_ts"] = ts
            t["eventos"].append({"t": _ahora(),
                                 "msg": f"[despertar editado: {ts or 'ahora'}]"})
            # si la tarea dormida pertenece a una meta programada, la meta
            # sigue el mismo reloj (una sola fuente de verdad del despertar)
            mid = t.get("meta")
            if t["nivel"] == "jefe" and mid:
                for m in self.data["metas"]:
                    if m["id"] == mid and m["estado"] == "pendiente":
                        if ts is None:
                            m.pop("despierta_ts", None)
                        else:
                            m["despierta_ts"] = ts
            self._save()
            return True

    def reasignar(self, tid: str, rol: str) -> bool:
        """Cambia el rol de una tarea trabajador que aún no corrió."""
        if rol not in ("investigador", "implementador"):
            return False
        with self._lock:
            t = self.data["tareas"].get(tid)
            if (t is None or t["nivel"] != "trabajador"
                    or t["estado"] not in ("pendiente", "pausada")):
                return False
            t["rol"] = rol
            t["eventos"].append({"t": _ahora(), "msg": f"[reasignada a {rol}]"})
            self._save()
            return True

    def reiniciar(self, tid: str):
        """Clona una tarea fallida/detenida como nueva pendiente (mismo padre/
        rol/detalle). Devuelve el id nuevo, o None si no aplica."""
        with self._lock:
            t = self.data["tareas"].get(tid)
            if t is None or t["estado"] not in ("fallida", "detenida"):
                return None
            nuevo = self.crear_tarea(t["nivel"], t["titulo"], t["detalle"],
                                     padre=t["padre"], rol=t["rol"], meta=t["meta"])
            self.data["tareas"][nuevo]["eventos"].append(
                {"t": _ahora(), "msg": f"[reinicio de {tid}]"})
            t["eventos"].append({"t": _ahora(), "msg": f"[reiniciada como {nuevo}]"})
            self._save()
            return nuevo

    def mensaje(self, de: str, para: str, texto: str) -> bool:
        """Mensaje de un agente/usuario a una tarea: queda como evento visible."""
        texto = str(texto).strip()
        with self._lock:
            if para not in self.data["tareas"] or not texto:
                return False
            self.evento(para, f"[mensaje de {de}]: {texto}")
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
            snap = json.loads(json.dumps(self.data))
            snap["_seq"] = self.seq
            return snap

    def hijos(self, tid: str) -> list:
        with self._lock:
            return [dict(t) for k in self.data["orden"]
                    for t in [self.data["tareas"][k]] if t["padre"] == tid]
