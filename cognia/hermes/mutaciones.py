# -*- coding: utf-8 -*-
"""Registro de mutaciones de fichero del turno y footer de las que FALLARON.

Que resuelve
------------
El modelo cierra el turno con "edite los 5 ficheros" cuando 3 patches fallaron.
El usuario solo lo descubre corriendo `git status` a mano. Este modulo lleva la
cuenta MEDIDA de cada intento de escritura del turno y devuelve un bloque de
texto que se anexa a la respuesta final SOLO cuando hubo fallos, de modo que
sobre-declarar sea estructuralmente imposible mas alla del modelo.

Es la version operativa de dos lecciones del dueno: "el CONTRAFACTUAL es la
unica defensa" (no se confia en el resumen, se contrasta con el hecho) y
"contar bien no es medir lo que importa" (el gate decia PASS con el contenido
inventado; aca el hecho es "el fichero cambio", no "la tool se llamo").

De donde se destilo (leido, no imaginado)
-----------------------------------------
Hermes Agent, C:/Users/usuario/AppData/Local/hermes/hermes-agent:
  - agent/turn_finalizer.py:459-482 -- el gancho: si `_turn_failed_file_mutations`
    no esta vacio y el verificador esta activo, se anexa el footer a
    `final_response` (solo si hay respuesta real y el usuario no interrumpio).
  - run_agent.py:3399-3437 -- `_format_file_mutation_failure_footer`: cabecera
    con el conteo, hasta 10 bullets `path -- [tool] error`, y "… and N more".
  - run_agent.py:3298-3340 -- `_record_file_mutation_result`: en fallo guarda el
    PRIMER error por ruta; en exito hace `state.pop(path)` (el modelo se
    recupero dentro del mismo turno) y suma la ruta a `_turn_file_mutation_paths`.
  - agent/tool_result_classification.py:26 -- `file_mutation_result_landed`: el
    exito se prueba mirando el PAYLOAD (bytes_written / success=True), no la
    ausencia de excepcion.
  - agent/turn_context.py:1128-1129 -- ambos estados se resetean POR TURNO.
  - agent/conversation_loop.py:6853 y 6909 -- `_turn_file_mutation_paths` es lo
    que alimenta la parada verificada (verify-on-stop / pre_verify): sin la
    lista de ficheros que SI cambiaron no hay nada que verificar.

Diferencias deliberadas con Hermes
----------------------------------
1. En Cognia el fallo tipico NO es una excepcion ni un JSON: las tools devuelven
   un string ("RESULTADO editar_archivo ERROR: ..." -- cognia/agent/tools.py:1061).
   Por eso `resultado()` recibe `ok: bool` + `detalle` textual y el modulo no
   intenta adivinar nada; `clasificar_resultado()` traduce el string del repo a
   ese par usando el MISMO criterio que ya usa el loop (`\\bERROR\\b` sobre la
   cabeza del resultado, cli.py:12310) para no inventar una segunda convencion.
2. Hermes borra la ruta del dict al primer exito posterior. Aca la ruta sigue
   listada como fallida pero el bullet dice que una escritura posterior SI
   landeo: "3 de 5 bloques fallaron y el fichero quedo a medias" es informacion,
   no ruido. La recuperacion limpia se ve igual (el footer distingue).
3. Hermes envuelve las rutas en backticks para que el gateway no auto-adjunte
   ficheros protegidos a un canal de mensajeria (#35584). Cognia no tiene ese
   extractor: aca los backticks son solo legibilidad.

Contrato duro: NADA en este modulo lanza. Es instrumentacion del camino
caliente; un registro que revienta el turno seria peor que no medir.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Tools de cognia/agent/tools.py que TOCAN el disco. Solo se usa como ayuda al
# cableado (`es_operacion_de_fichero`): el registro acepta cualquier nombre de
# operacion, porque una tool sintetizada o un plugin tambien puede escribir.
OPERACIONES_FICHERO = frozenset({
    "escribir_archivo", "editar_archivo", "apendar_archivo",
    "borrar_archivo", "mover_archivo",
})

# Topes. Un turno con 200 patches fallidos no puede ahogar la respuesta: el
# footer es un AVISO, no un informe. 10 bullets es el mismo tope que Hermes
# (run_agent.py:3418) y 180 chars el mismo recorte de `_extract_error_preview`
# (agent/tool_dispatch_helpers.py:484).
MAX_RUTAS_FOOTER = 10
MAX_DETALLE = 180
MAX_CHARS_FOOTER = 1200

_RE_ERROR = re.compile(r"\bERROR\b")
_RE_ERROR_DOS_PUNTOS = re.compile(r"\bERROR\b\s*:?\s*(.*)", re.DOTALL)


def es_operacion_de_fichero(operacion: str) -> bool:
    """True si el nombre de tool es una de las que mutan ficheros en el repo."""
    return str(operacion or "").strip() in OPERACIONES_FICHERO


def ruta_de_args(args: str) -> str:
    """Primera parte de los args de una tool de fichero ('ruta | contenido').

    Las tools del repo parsean con `re.split(r"\\s*\\|\\s*", args, maxsplit=1)`
    (tools.py:999), asi que la ruta es todo lo anterior al primer '|'; las que
    reciben solo una ruta (borrar_archivo) caen en el mismo caso. Devuelve ""
    si no hay nada util -- decidir que hacer con eso es del que cablea.
    """
    try:
        texto = str(args or "")
    except Exception:
        return ""
    return texto.split("|", 1)[0].strip().strip('"').strip("'")


def clasificar_resultado(texto: Any, max_detalle: int = MAX_DETALLE) -> Tuple[bool, str]:
    """Traduce el string de RESULTADO de una tool a (ok, detalle).

    Criterio IDENTICO al que el loop ya usa para marcar un paso como fallido
    (cli.py:12310: `re.search(r"\\bERROR\\b", result[:120])`): borde de palabra
    y solo la cabeza, para que un 'ERROR_LOG.txt' mencionado en un resultado
    exitoso no se cuente como fallo. Si hay fallo, el detalle es lo que sigue a
    'ERROR:'; si no, se devuelve ok=True y detalle vacio.

    OJO: 'sin cambios (el REPLACE es igual)' (tools.py:1089) NO es un fallo --
    la tool hizo lo que se le pidio. No hay mentira que denunciar ahi.
    """
    try:
        cabeza = str(texto or "")[:120]
    except Exception:
        return True, ""
    if not _RE_ERROR.search(cabeza):
        return True, ""
    m = _RE_ERROR_DOS_PUNTOS.search(str(texto or ""))
    detalle = m.group(1) if m else str(texto or "")
    return False, _recortar(detalle, max_detalle)


def _recortar(texto: Any, tope: int) -> str:
    """Colapsa espacios y recorta a `tope` chars (mismo shape que Hermes)."""
    try:
        plano = " ".join(str(texto or "").split())
    except Exception:
        return ""
    if tope > 0 and len(plano) > tope:
        return plano[: max(1, tope - 3)] + "..."
    return plano


def _clave(ruta: Any) -> str:
    """Clave de deduplicacion por ruta.

    normpath+normcase: en Windows 'a\\b.py', 'a/b.py' y 'A/B.PY' son el MISMO
    fichero, y contarlos como tres fallos distintos volveria a hacer que el
    footer 'cuente bien' lo que no importa. El TEXTO que se muestra es el
    primero que se vio (no se le devuelve al usuario una ruta en minusculas
    que el nunca escribio).
    """
    try:
        crudo = str(ruta or "").strip()
        if not crudo:
            return ""
        return os.path.normcase(os.path.normpath(crudo))
    except Exception:
        return str(ruta or "").strip()


class RegistroMutaciones:
    """Cuenta los intentos de mutacion de fichero de UN turno.

    Uso (el cableado lo hace el orquestador; ver el informe del modulo):

        reg = RegistroMutaciones()
        mid = reg.intento(ruta, "editar_archivo")   # antes de correr la tool
        ok, detalle = clasificar_resultado(result)  # el string que devolvio
        reg.resultado(mid, ok, detalle)
        ...
        pie = reg.footer()
        if pie:
            respuesta_final = respuesta_final.rstrip() + "\\n\\n" + pie

    Un registro por turno (Hermes lo resetea en turn_context.py:1128). En una
    corrida anidada (delegar_subtarea) el sub-agente tiene el SUYO: el footer
    describe el turno que lo emite, no el arbol entero.
    """

    def __init__(self,
                 max_rutas: int = MAX_RUTAS_FOOTER,
                 max_detalle: int = MAX_DETALLE,
                 max_chars: int = MAX_CHARS_FOOTER) -> None:
        self.max_rutas = max(1, int(max_rutas or 1))
        self.max_detalle = max(0, int(max_detalle or 0))
        self.max_chars = max(0, int(max_chars or 0))
        # id -> {ruta, clave, operacion, cerrado, ok}
        self._intentos: Dict[int, Dict[str, Any]] = {}
        # clave -> {ruta, operacion, detalle, n}  (PRIMER error por ruta)
        self._fallos: Dict[str, Dict[str, Any]] = {}
        # clave -> ruta mostrable, en orden de primera escritura exitosa
        self._escritos: Dict[str, str] = {}
        self._n_ok = 0
        self._n_fallos = 0
        self._siguiente = 1

    # -- registro -------------------------------------------------------

    def intento(self, ruta: Any, operacion: Any = "") -> int:
        """Declara que se va a intentar mutar `ruta` con `operacion`. Devuelve el id.

        Se llama ANTES de correr la tool a proposito: si la tool se cuelga, mata
        el proceso o el loop corta por presupuesto, el intento queda registrado
        como PENDIENTE en `resumen()` en vez de desaparecer. Un intento que
        desaparece es exactamente el fallo silencioso que este modulo persigue.
        """
        idm = self._siguiente
        self._siguiente += 1
        try:
            texto_ruta = str(ruta or "").strip()
        except Exception:
            texto_ruta = ""
        self._intentos[idm] = {
            "ruta": texto_ruta or "(ruta desconocida)",
            "clave": _clave(texto_ruta) or f"__sin_ruta_{idm}",
            "operacion": (str(operacion or "").strip() or "escritura"),
            "cerrado": False,
            "ok": None,
        }
        return idm

    def resultado(self, idm: Any, ok: bool, detalle: Any = "") -> bool:
        """Cierra un intento con su veredicto MEDIDO. Devuelve False si el id no existe.

        `ok` es un bool explicito porque en este repo el fallo llega como STRING
        ("RESULTADO x ERROR: ..."), no como excepcion: quien cablea usa
        `clasificar_resultado()` o su propio criterio, y aca no se adivina.
        Un id repetido o desconocido no lanza -- devuelve False y se ignora.
        """
        try:
            info = self._intentos.get(idm)
        except Exception:
            info = None
        if info is None or info.get("cerrado"):
            return False
        info["cerrado"] = True
        info["ok"] = bool(ok)
        clave = info["clave"]
        if ok:
            self._n_ok += 1
            self._escritos.setdefault(clave, info["ruta"])
            return True
        self._n_fallos += 1
        prev = self._fallos.get(clave)
        if prev is None:
            # PRIMER error de esa ruta, como Hermes (run_agent.py:3330): un
            # segundo intento con otro mensaje no debe tapar la causa original.
            self._fallos[clave] = {
                "ruta": info["ruta"],
                "operacion": info["operacion"],
                "detalle": _recortar(detalle, self.max_detalle),
                "n": 1,
            }
        else:
            prev["n"] += 1
        return True

    # -- lectura --------------------------------------------------------

    def ficheros_escritos(self) -> List[str]:
        """Rutas que SI cambiaron (al menos un resultado ok), en orden y deduplicadas.

        Es el equivalente de `_turn_file_mutation_paths` de Hermes
        (conversation_loop.py:6853/6909) y lo que necesita la parada verificada:
        sin la lista de lo que cambio no hay nada concreto que mandar a verificar.
        """
        return list(self._escritos.values())

    def rutas_fallidas(self) -> List[str]:
        """Rutas con al menos un fallo NO recuperado por otra escritura ok."""
        return [d["ruta"] for d in self._fallos.values()]

    def resumen(self) -> Dict[str, Any]:
        """Conteo plano del turno.

        `intentos` cuenta LLAMADAS (no rutas); `ok`/`fallos` cuentan resultados
        cerrados; `rutas_fallidas` esta deduplicada por ruta. `pendientes` son
        los intentos que nunca reportaron (tool colgada, corte por presupuesto):
        no son exitos ni fallos y mentir en cualquiera de los dos lados seria
        justamente el defecto que este modulo viene a cerrar.
        """
        pendientes = sum(1 for i in self._intentos.values() if not i.get("cerrado"))
        return {
            "intentos": len(self._intentos),
            "ok": self._n_ok,
            "fallos": self._n_fallos,
            "rutas_fallidas": self.rutas_fallidas(),
            "rutas_escritas": self.ficheros_escritos(),
            "pendientes": pendientes,
        }

    # -- footer ---------------------------------------------------------

    def footer(self) -> Optional[str]:
        """Bloque a anexar a la respuesta final, o None si no hubo NINGUN fallo.

        None (no "") a proposito: el que cablea hace `if pie:` y un turno limpio
        no toca la respuesta del modelo ni con un salto de linea.
        """
        if not self._fallos:
            return None
        n_rutas = len(self._fallos)
        cabecera = (
            "AVISO (verificador de mutaciones): {n} fichero(s) NO quedaron "
            "escritos en este turno, diga lo que diga el texto de arriba. "
            "Comprobalo con git_diff o leer_archivo.".format(n=n_rutas)
        )
        bullets: List[str] = []
        for clave, datos in list(self._fallos.items())[: self.max_rutas]:
            linea = "  - `{ruta}` [{op}] {detalle}".format(
                ruta=datos["ruta"],
                op=datos["operacion"],
                detalle=datos["detalle"] or "fallo sin detalle",
            )
            if datos["n"] > 1:
                linea += " (fallo {n} veces)".format(n=datos["n"])
            # Marca de escritura PARCIAL: la ruta fallo y ademas alguna
            # escritura suya SI landeo (p.ej. 2 de 5 bloques SEARCH/REPLACE).
            # Un fichero a medias es peor que uno intacto, no mejor.
            if clave in self._escritos:
                linea += " -- ojo: otra escritura sobre este fichero SI se aplico"
            bullets.append(linea)
        restantes = n_rutas - len(bullets)
        if restantes > 0:
            bullets.append("  - ... y {n} fichero(s) mas".format(n=restantes))

        lineas = [cabecera] + bullets
        escritos = self.ficheros_escritos()
        if escritos:
            muestra = ["`{0}`".format(r) for r in escritos[: self.max_rutas]]
            cola = ""
            if len(escritos) > self.max_rutas:
                cola = " (+{n} mas)".format(n=len(escritos) - self.max_rutas)
            lineas.append("  SI se escribieron ({n}): {lista}{cola}".format(
                n=len(escritos), lista=", ".join(muestra), cola=cola))

        return self._capar("\n".join(lineas), cabecera)

    def _capar(self, texto: str, cabecera: str) -> str:
        """Tope duro de longitud: se sacrifican bullets, nunca la cabecera.

        La cabecera es el HECHO (cuantos ficheros no se escribieron); los
        bullets son el detalle. Un turno patologico degrada a "N ficheros no se
        escribieron" en vez de sepultar la respuesta del modelo.
        """
        if self.max_chars <= 0 or len(texto) <= self.max_chars:
            return texto
        lineas = texto.split("\n")
        while len(lineas) > 1:
            lineas.pop()
            cortado = "\n".join(lineas) + "\n  - ... (aviso recortado)"
            if len(cortado) <= self.max_chars:
                return cortado
        return cabecera[: self.max_chars] if len(cabecera) > self.max_chars else cabecera
