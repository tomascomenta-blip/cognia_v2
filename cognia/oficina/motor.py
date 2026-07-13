"""Motor de la oficina: jefe → directores → trabajadores, sobre la maquinaria real.

- El JEFE toma la meta y la descompone en directivas (orch.infer, el mismo
  orquestador del CLI). Una directiva por director.
- Cada DIRECTOR descompone su directiva en subtareas de trabajador con rol
  (investigador | implementador, los roles reales de ROLE_TOOLS).
- Cada TRABAJADOR ejecuta su subtarea con cli._run_agent_task (el agent loop
  ReAct real, tools acotadas por rol).

Control externo REAL: el hook de print del agent loop se llama en cada paso;
si el usuario pidió detener/pausar la tarea desde el dashboard, el hook lanza
Detenida/Pausada y el trabajo corta a mitad de ejecución (no solo entre tareas).
Sin modelo cargable no hay planificación ni trabajo: se registra el fallo
honestamente (nada de resultados simulados).
"""
import threading
import time
import traceback

from cognia.oficina.estado import Oficina
from cognia.oficina.identidad import modelo_por_rol as _modelo_por_rol


class Detenida(Exception):
    pass


class Pausada(Exception):
    pass


# Leccion MEDIDA del repo (memoria cognia-mom-agente-andamiaje, +62pp):
# el 3B necesita EJEMPLOS CONCRETOS, no formatos abstractos ("ROL: subtarea"
# hizo que el modelo escribiera literalmente "ROL: ..." en el e2e v1).
PLAN_JEFE = (
    "Sos el JEFE de una oficina de agentes. Descompone la META en 1 a 3 "
    "directivas concretas e independientes, una por director. Responde SOLO "
    "una lista numerada, una directiva por linea, sin explicaciones.\n"
    "Ejemplo de respuesta:\n"
    "1. Crear el archivo notas.txt con el resumen pedido\n"
    "2. Verificar que el archivo quedo bien escrito\n\n"
    "META: {meta}"
)
PLAN_DIRECTOR = (
    "Sos un DIRECTOR de una oficina de agentes. Descompone tu DIRECTIVA en 1 "
    "a 3 subtareas para trabajadores. Cada linea empieza con el rol en "
    "minusculas y dos puntos. Roles: investigador (solo lee/busca/responde) "
    "o implementador (escribe archivos y ejecuta codigo). Responde SOLO las "
    "lineas, nada mas.\n"
    "Ejemplo de respuesta:\n"
    "implementador: crea el archivo notas.txt con el texto 'hola'\n"
    "investigador: verifica que notas.txt existe y di su contenido\n\n"
    "DIRECTIVA: {directiva}"
)

# Guard-rail: si el rol no se parsea, inferirlo de la subtarea (crear/escribir/
# ejecutar => implementador). Evita mandar un "crear archivo" a un rol sin
# permisos de escritura (fallo real del e2e v1).
_RE_IMPLEMENTADOR = __import__("re").compile(
    r"(?i)\b(crea|crear|escrib|guarda|apend|ejecut|modific|genera|corre)\w*")


def _parse_numerada(texto: str) -> list:
    items = []
    for linea in (texto or "").splitlines():
        linea = linea.strip().lstrip("0123456789.-) ").strip()
        if len(linea) > 8:
            items.append(linea)
    return items[:3]


def _parse_roles(texto: str) -> list:
    """Lineas 'rol: subtarea' -> [(rol, subtarea)].

    Robusto a los tics reales del 3B (e2e v1): prefijo literal 'ROL:' copiado
    del formato, y rol ausente/desconocido -> se infiere de la subtarea
    (verbos de escritura/ejecucion => implementador, si no investigador)."""
    out = []
    for linea in _parse_numerada(texto):
        rol, _, resto = linea.partition(":")
        rol = rol.strip().lower()
        if rol == "rol" and resto.strip():          # "ROL: investigador. tarea"
            resto2 = resto.strip()
            for candidato in ("investigador", "implementador"):
                if resto2.lower().startswith(candidato):
                    rol = candidato
                    resto = resto2[len(candidato):].lstrip(".:,- ")
                    break
        if rol in ("investigador", "implementador") and resto.strip():
            out.append((rol, resto.strip()))
        else:
            inferido = ("implementador" if _RE_IMPLEMENTADOR.search(linea)
                        else "investigador")
            out.append((inferido, linea))
    return out[:3]


class Motor(threading.Thread):
    """Procesa metas de a una (secuencial: la máquina local corre UN 3B)."""

    def __init__(self, oficina: Oficina, ai=None, poll_s: float = 1.5):
        super().__init__(daemon=True, name="oficina-motor")
        self.of = oficina
        self.ai = ai
        self.poll_s = poll_s
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    # ── acceso al modelo real ──
    def _orch(self):
        from shattering.orchestrator import ShatteringOrchestrator
        orch = getattr(self.ai, "_orchestrator", None)
        if orch is None:
            orch = ShatteringOrchestrator(mode="local")
            if self.ai is not None:
                try:
                    self.ai._orchestrator = orch
                except Exception:
                    pass
        return orch

    def _infer(self, prompt: str) -> str:
        return self._orch().infer(prompt, max_tokens=220, temperature=0.0).text.strip()

    # ── hooks de control ──
    def _chequea(self, tid: str) -> None:
        c = self.of.control(tid)
        if c == "detener":
            self.of.consumir_solicitud(tid)
            raise Detenida(tid)
        if c == "pausar":
            self.of.consumir_solicitud(tid)
            raise Pausada(tid)

    def _espera_si_pausada(self, tid: str) -> None:
        """Bloquea mientras la tarea esté pausada; detener la libera."""
        while not self._stop.is_set():
            t = self.of.snapshot()["tareas"].get(tid) or {}
            if t.get("estado") == "detenida":
                raise Detenida(tid)
            if t.get("estado") != "pausada":
                return
            time.sleep(self.poll_s)

    # ── niveles ──
    def _trabajador(self, tarea: dict) -> str:
        from cognia.cli import _run_agent_task
        from cognia.agent.tools import ROLE_TOOLS
        tid = tarea["id"]

        def print_hook(linea):
            self.of.evento(tid, linea)
            self._chequea(tid)          # detención REAL a mitad de tarea

        self.of.set_estado(tid, "en_curso")
        self.of.evento(tid, f"[trabajador:{tarea['rol']}] arranca")
        resultado = _run_agent_task(
            self.ai, tarea["detalle"], print_hook, max_steps=8,
            allowed_tools=ROLE_TOOLS.get(tarea["rol"]), delegation_depth=1)
        self.of.set_estado(tid, "hecha", resultado=resultado)
        return str(resultado)

    def _procesa_meta(self, meta: dict) -> None:
        mid = meta["id"]
        self.of.set_meta_estado(mid, "en_curso")
        # meta PROGRAMADA: el jefe ya existe (durmió en su cama hasta ahora)
        jefe_id = self.of.jefe_de_meta(mid) or self.of.crear_tarea(
            "jefe", f"META: {meta['texto'][:80]}", meta["texto"], meta=mid,
            modelo=_modelo_por_rol("jefe"))
        try:
            self.of.set_estado(jefe_id, "en_curso")
            self.of.evento(jefe_id, "jefe planificando (orch.infer)...")
            directivas = _parse_numerada(
                self._infer(PLAN_JEFE.format(meta=meta["texto"])))
            if not directivas:
                directivas = [meta["texto"]]
                self.of.evento(jefe_id, "plan no parseable -> 1 directiva = meta entera")
            self.of.evento(jefe_id, f"{len(directivas)} directiva(s)")

            resultados = []
            for i, directiva in enumerate(directivas, 1):
                self._chequea(jefe_id)
                dir_id = self.of.crear_tarea("director", f"D{i}: {directiva[:80]}",
                                             directiva, padre=jefe_id, meta=mid,
                                             modelo=_modelo_por_rol("director"))
                try:
                    self._espera_si_pausada(dir_id)
                    self.of.set_estado(dir_id, "en_curso")
                    self.of.evento(dir_id, "director desglosando...")
                    subtareas = _parse_roles(
                        self._infer(PLAN_DIRECTOR.format(directiva=directiva)))
                    if not subtareas:
                        subtareas = [("investigador", directiva)]
                    parciales = []
                    for rol, sub in subtareas:
                        self._chequea(dir_id)
                        tid = self.of.crear_tarea("trabajador", sub[:80], sub,
                                                  padre=dir_id, rol=rol, meta=mid,
                                                  modelo=_modelo_por_rol(rol))
                        try:
                            self._espera_si_pausada(tid)
                            parciales.append(self._trabajador(
                                self.of.snapshot()["tareas"][tid]))
                        except Detenida:
                            self.of.set_estado(tid, "detenida")
                            self.of.evento(tid, "[detenida por el usuario]")
                        except Pausada:
                            self.of.set_estado(tid, "pausada")
                            self.of.evento(tid, "[pausada por el usuario]")
                            self._espera_si_pausada(tid)
                        except Exception as exc:
                            self.of.set_estado(tid, "fallida", resultado=str(exc)[:400])
                    self.of.set_estado(dir_id, "hecha",
                                       resultado=" | ".join(p[:200] for p in parciales))
                    resultados.extend(parciales)
                except Detenida:
                    self.of.set_estado(dir_id, "detenida")
            resumen = "\n".join(r[:300] for r in resultados) or "(sin resultados)"
            self.of.set_estado(jefe_id, "hecha", resultado=resumen)
            self.of.set_meta_estado(mid, "hecha", resultado=resumen)
        except Detenida:
            self.of.set_estado(jefe_id, "detenida")
            self.of.set_meta_estado(mid, "detenida")
        except Exception:
            err = traceback.format_exc()[-800:]
            self.of.set_estado(jefe_id, "fallida", resultado=err)
            self.of.set_meta_estado(mid, "fallida", resultado=err)

    def run(self) -> None:
        while not self._stop.is_set():
            meta = self.of.meta_pendiente()
            if meta:
                self._procesa_meta(meta)
            else:
                time.sleep(self.poll_s)
