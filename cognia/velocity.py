"""
cognia/velocity.py
==================
Selector del MECANISMO de decodificacion del backend llama.cpp (/velocidad).

Cuatro modos registrados en MODOS (el registro es honesto: los modos que
dependen del BDraft entrenado se listan pero reportan no-disponible con la
razon exacta, y resolve_mode() degrada a 'clasico' CON AVISO, jamas en
silencio):

  clasico          generacion normal token a token; conserva las
                   optimizaciones actuales del backend. Default.
  dspark           speculative decoding con el draft coder-0.5b + corte por
                   confianza (--spec-draft-p-min): la parte barata de DSpark.
  gemma            difusion de bloques estilo DiffusionGemma. REQUIERE el
                   BDraft entrenado (bdraft/, gates G0-G5; run v0 pendiente).
  difusion-dspark  maxima velocidad: difusion + verificacion adaptativa.
                   REQUIERE el BDraft entrenado, igual que 'gemma'.

Persistencia (patron cognia/perf_profiles.py): set_mode()/set_hybrid()
escriben COGNIA_VELOCIDAD / COGNIA_VELOCIDAD_HIBRIDO en ~/.cognia/config.env
via first_run.set_config_value (que tambien refleja en os.environ). El modo
'dspark' ademas setea LLAMA_DRAFT_GGUF_PATH, que node/llama_backend.py lee a
CALL-time al armar el cmd del server; 'clasico' la limpia. Un llama-server ya
corriendo no se entera: set_mode() devuelve restart_backend_hint().

Hibrido: politica POR ENCIMA del modo. Con COGNIA_VELOCIDAD_HIBRIDO on,
resolve_mode(operation_kind, texto) decide por operacion: pensamiento
profundo -> 'clasico'; el resto -> el modo rapido mas capaz DISPONIBLE.

Ortogonalidad con /esfuerzo: /velocidad elige el MECANISMO de decode (como
se generan los tokens); /esfuerzo (senal COGNIA_ESFUERZO del ecosistema
historico, si existe) elige CUANTO computo/calidad se invierte. Cero
conflicto de claves: /velocidad escribe COGNIA_VELOCIDAD,
COGNIA_VELOCIDAD_HIBRIDO y LLAMA_DRAFT_GGUF_PATH; jamas toca
COGNIA_ESFUERZO. Con COGNIA_ESFUERZO en ('alto', 'max'), resolve_mode()
devuelve SIEMPRE 'clasico': bajo esfuerzo alto no se sacrifica calidad de
decode por velocidad.

Numeros medidos (2026-07-18, RTX 5060 Ti 16GB, llama-server b10066 CUDA,
chat-7b Q4_K_M, mediana de 3 corridas, n_predict=128, T=0):
  B0 sin draft:                 87.5 tok/s (codigo y prosa por igual)
  dspark (n-max 8, p-min 0.75): codigo 142.9 tok/s (1.63x)
                                prosa chat 72.3 tok/s (0.83x)
El draft coder-0.5b ACELERA codigo y FRENA prosa: dspark rinde en flujos de
codigo. CRITICO b10066: --model-draft SIN --spec-type draft-simple es un
no-op SILENCIOSO (el server ni carga el draft); eso explica el 1.00x
historico medido en GPU.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from . import first_run
from . import perf_profiles

logger = logging.getLogger(__name__)

DEFAULT_MODE = "clasico"

MODE_ENV = "COGNIA_VELOCIDAD"
HYBRID_ENV = "COGNIA_VELOCIDAD_HIBRIDO"
DRAFT_PATH_ENV = "LLAMA_DRAFT_GGUF_PATH"

# -- Probe empirico por-request (2026-07-18, llama-server b10066 en :8095) ----
# Se probo POST /completion contra un server real arrancado con --model-draft
# + --spec-type draft-simple, mandando el campo speculative de TODAS las
# formas plausibles: anidado {"speculative": {"n_max": N}} y plano
# "speculative.n_max" / "speculative.n_min" / "speculative.types" (asi los
# lista /props en default_generation_settings). Resultado: el server acepta
# los campos (HTTP 200, sin error) pero los IGNORA: draft_n identico (137) y
# ~135 tok/s identicos con n_max 0, 2, 8, 16 y hasta con types="none".
# Conclusion: NO hay control speculative por request en b10066; el hibrido
# solo puede conmutar dspark/clasico via restart del server (limitacion
# declarada). Si un build futuro lo soporta, poner aqui el nombre del campo
# y completar build_request_overrides().
PER_REQUEST_SPEC_FIELD = None


# -- Draft GGUF ----------------------------------------------------------------

def draft_gguf_path() -> Path:
    """Ruta del draft GGUF clasico para el modo dspark: COGNIA_DRAFT_PATH si
    esta seteada (tests/override), sino el coder-0.5b Q8_0 de la flota
    (node/fleet.py, ~/.cognia/models)."""
    override = os.environ.get("COGNIA_DRAFT_PATH", "").strip()
    if override:
        return Path(override)
    from node.fleet import FLEET, models_dir
    for m in FLEET:
        if m["key"] == "coder-0.5b":
            return models_dir() / m["files"][0]
    raise LookupError("la flota (node/fleet.py) no tiene el modelo 'coder-0.5b'")


# -- Disponibilidad por modo ---------------------------------------------------

def _clasico_disponible() -> tuple[bool, str]:
    """El modo clasico siempre esta disponible."""
    return True, ""


def _dspark_disponible() -> tuple[bool, str]:
    """dspark necesita el draft GGUF en disco; el resto lo arma llama_backend."""
    p = draft_gguf_path()
    if p.is_file():
        return True, ""
    return False, (f"falta el draft GGUF en {p} "
                   "(bajar 'coder-0.5b' de la flota, node/fleet.py)")


def _bdraft_disponible() -> tuple[bool, str]:
    """Los modos de difusion requieren el BDraft ENTRENADO (bdraft/ es solo el
    esqueleto; run v0 pendiente, ver planes/DSPARK_GEMMA_DRAFT_MODEL.md).
    COGNIA_BDRAFT_CKPT es el gancho futuro al checkpoint; aun con checkpoint
    falta integrar el pipeline de inferencia v0 (seccion 2.4 del plan), asi
    que hoy esto NUNCA devuelve disponible: honestidad antes que promesas."""
    ckpt = os.environ.get("COGNIA_BDRAFT_CKPT", "").strip()
    if not (ckpt and Path(ckpt).is_file()):
        return False, ("requiere el BDraft entrenado: gates G0+v0 del plan "
                       "DSPARK pendientes (planes/DSPARK_GEMMA_DRAFT_MODEL.md); "
                       "no hay checkpoint (COGNIA_BDRAFT_CKPT sin setear o el "
                       "archivo no existe)")
    return False, ("hay checkpoint BDraft (COGNIA_BDRAFT_CKPT) pero la "
                   "integracion del pipeline de difusion v0 (seccion 2.4 del "
                   "plan DSPARK) todavia no esta implementada")


MODOS = {
    "clasico": {
        "descripcion": ("generacion token a token, conserva las "
                        "optimizaciones actuales (default)"),
        "disponible_fn": _clasico_disponible,
        "requisito": "ninguno",
    },
    "dspark": {
        "descripcion": ("speculative con draft coder-0.5b + corte por "
                        "confianza (parte barata de DSpark; medido: 1.63x "
                        "codigo, 0.83x prosa)"),
        "disponible_fn": _dspark_disponible,
        "requisito": "draft GGUF coder-0.5b presente en la flota",
    },
    "gemma": {
        "descripcion": "difusion de bloques estilo DiffusionGemma",
        "disponible_fn": _bdraft_disponible,
        "requisito": "BDraft entrenado (plan DSPARK, gates G0-G5)",
    },
    "difusion-dspark": {
        "descripcion": ("maxima velocidad: difusion + verificacion "
                        "adaptativa (DSpark completo)"),
        "disponible_fn": _bdraft_disponible,
        "requisito": "BDraft entrenado (plan DSPARK, gates G0-G5)",
    },
}


def _disponible(name: str) -> tuple[bool, str]:
    """(disponible, razon) del modo; razon vacia cuando esta disponible."""
    return MODOS[name]["disponible_fn"]()


# -- Modo fijo: get/set --------------------------------------------------------

def get_mode() -> str:
    """Modo persistido en COGNIA_VELOCIDAD (config.env ya cargada en
    os.environ por first_run.apply_config al arranque). Default 'clasico';
    un valor basura tambien cae a 'clasico'."""
    name = os.environ.get(MODE_ENV, "").strip().lower()
    return name if name in MODOS else DEFAULT_MODE


def set_mode(name: str) -> str:
    """Valida y persiste el modo. Lanza ValueError si el modo no existe o no
    esta disponible (con la razon exacta de que falta). 'dspark' ademas
    persiste LLAMA_DRAFT_GGUF_PATH -> draft coder-0.5b; cualquier otro modo
    la limpia (valor vacio en config.env + pop de os.environ). Devuelve el
    aviso de restart_backend_hint() ('' si no hay server corriendo)."""
    if name not in MODOS:
        raise ValueError(
            f"Modo desconocido: {name!r}. Validos: {', '.join(MODOS)}"
        )
    ok, razon = _disponible(name)
    if not ok:
        raise ValueError(f"'{name}' no esta disponible: {razon}")
    first_run.set_config_value(MODE_ENV, name)
    if name == "dspark":
        first_run.set_config_value(DRAFT_PATH_ENV, str(draft_gguf_path()))
    else:
        first_run.set_config_value(DRAFT_PATH_ENV, "")
        os.environ.pop(DRAFT_PATH_ENV, None)
    logger.info("[velocity] modo '%s' aplicado", name)
    return perf_profiles.restart_backend_hint()


# -- Hibrido: get/set ----------------------------------------------------------

def hybrid_enabled() -> bool:
    """True si COGNIA_VELOCIDAD_HIBRIDO esta en on/1/true/si. Default off."""
    return os.environ.get(HYBRID_ENV, "").strip().lower() in (
        "1", "on", "true", "si")


def set_hybrid(enabled: bool) -> None:
    """Persiste el hibrido como COGNIA_VELOCIDAD_HIBRIDO=on|off."""
    first_run.set_config_value(HYBRID_ENV, "on" if enabled else "off")
    logger.info("[velocity] hibrido %s", "on" if enabled else "off")


# -- Resolucion por operacion --------------------------------------------------

# Tipos de operacion que siempre son pensamiento profundo (decode conservador)
_OPERACIONES_PROFUNDAS = ("agente", "razonamiento", "codigo_complejo")

# Senales lexicas de pensamiento profundo o codigo no trivial en el texto
_SENALES_PROFUNDAS = (
    "analiza", "analisis", "demuestra", "demostra", "paso a paso",
    "arquitectura", "debug", "razona", "refactoriza", "implementa",
    "algoritmo", "optimiza", "teorema",
)

# Umbral de longitud: un pedido largo suele requerir pensamiento profundo
_LARGO_PROFUNDO = 800


def _pide_pensamiento_profundo(texto: str) -> bool:
    """Heuristica lexica: senales de analisis/razonamiento/codigo no trivial
    (_SENALES_PROFUNDAS, en minusculas) o texto mas largo que 800 chars."""
    t = (texto or "").lower()
    if len(t) > _LARGO_PROFUNDO:
        return True
    return any(s in t for s in _SENALES_PROFUNDAS)


def resolve_mode(operation_kind: str, texto: str = "") -> str:
    """Modo de decode para UNA operacion.

    Reglas, en orden:
      1. COGNIA_ESFUERZO en ('alto', 'max') -> 'clasico' SIEMPRE (esfuerzo
         alto no sacrifica calidad de decode por velocidad; ver docstring
         del modulo sobre la ortogonalidad /velocidad vs /esfuerzo).
      2. Hibrido OFF -> el modo fijo de get_mode(); si ese modo no esta
         disponible (p.ej. config vieja apuntando a 'gemma' sin BDraft),
         degrada a 'clasico' CON AVISO en el log, jamas en silencio.
      3. Hibrido ON -> por operacion: operation_kind en ('agente',
         'razonamiento', 'codigo_complejo') o texto con senales de
         pensamiento profundo (_pide_pensamiento_profundo: palabras tipo
         analiza/demuestra/paso a paso/arquitectura/debug/razona, longitud
         >800, pedido de codigo no trivial) -> 'clasico'; si no, el modo
         rapido MAS capaz disponible: difusion-dspark > gemma > dspark >
         clasico.

    Nota de mecanica: con PER_REQUEST_SPEC_FIELD=None (probe b10066) el
    server NO conmuta speculative por request; esta funcion expresa la
    POLITICA y el cambio real de mecanismo requiere reiniciar el backend.
    """
    esfuerzo = os.environ.get("COGNIA_ESFUERZO", "").strip().lower()
    if esfuerzo in ("alto", "max"):
        return "clasico"
    if not hybrid_enabled():
        modo = get_mode()
        ok, razon = _disponible(modo)
        if ok:
            return modo
        logger.warning("[velocity] modo fijo '%s' no disponible (%s); "
                       "degrado a 'clasico'", modo, razon)
        return DEFAULT_MODE
    kind = (operation_kind or "").strip().lower()
    if kind in _OPERACIONES_PROFUNDAS or _pide_pensamiento_profundo(texto):
        return "clasico"
    for name in ("difusion-dspark", "gemma", "dspark"):
        ok, _razon = _disponible(name)
        if ok:
            return name
    return DEFAULT_MODE


def build_request_overrides(mode: str) -> dict:
    """Campos extra a inyectar en el payload de POST /completion segun el
    modo resuelto. Con PER_REQUEST_SPEC_FIELD=None (resultado del probe
    contra b10066: los campos speculative por request son aceptados pero
    ignorados) devuelve {} siempre: no hay nada util que inyectar y el
    hibrido dspark/clasico solo conmuta via restart del server."""
    if PER_REQUEST_SPEC_FIELD is None:
        return {}
    return {}   # (rama futura: armar el campo documentado en la constante)


# -- Resumen para el CLI -------------------------------------------------------

def velocity_summary() -> str:
    """Tabla imprimible: cada modo con [ACTIVO]/[disponible]/[no disponible:
    razon], estado del hibrido y nota de ortogonalidad con /esfuerzo."""
    activo = get_mode()
    lines = ["Modos de velocidad (/velocidad <modo>):"]
    for name, spec in MODOS.items():
        ok, razon = _disponible(name)
        if name == activo:
            marca = "[ACTIVO]" if ok else f"[ACTIVO, no disponible: {razon}]"
        elif ok:
            marca = "[disponible]"
        else:
            marca = f"[no disponible: {razon}]"
        lines.append(f"  {name:<16} {marca}")
        lines.append(f"                   {spec['descripcion']}")
    hib = "ON" if hybrid_enabled() else "OFF"
    lines.append(f"Hibrido (/hibrido): {hib} -- con ON, cada operacion elige "
                 "modo: pensamiento profundo -> clasico; el resto -> el modo "
                 "rapido mas capaz disponible.")
    lines.append("Nota: /velocidad elige el MECANISMO de decode; /esfuerzo "
                 "elige CUANTO computo. Con COGNIA_ESFUERZO alto/max se "
                 "decodifica siempre en clasico.")
    return "\n".join(lines)
