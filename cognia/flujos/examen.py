"""
cognia/flujos/examen.py
=======================
LA COMPUERTA de los flujos aprendidos.

QUE RESUELVE: un flujo grabado de una tarea que "salio bien" NO queda
disponible por haber salido bien. Antes de que el sistema pueda sugerirlo,
tiene que APROBAR UN EXAMEN EJECUTABLE sobre juegos de parametros NUEVOS, en
workspaces temporales aislados, juzgado por POSTCONDICIONES (ficheros, JSON,
codigos de salida), nunca por el texto que el propio flujo produjo. El
veredicto se guarda con su evidencia y ES lo que habilita al flujo.

POR QUE EXISTE (incidente medido en este repo, 2026-07/08): las skills
auto-capturadas ENVENENARON tareas ajenas — una traza de ATASCO se ascendio a
"procedimiento verificado" y el camino feliz cayo de 5/5 a 2-4/5. La leccion
en prosa ("no persistir sin evidencia") no impidio nada; lo unico que impide
es un chequeo que corre y puede decir NO. Este modulo es ese chequeo.

Las cuatro decisiones duras, cada una tapando un agujero conocido:

1. CASOS NUEVOS, y al menos uno DISTINTO EN ESTRUCTURA. Un flujo que solo
   funciona con los valores de su grabacion no aprendio: memorizo. Un caso
   identico a la grabacion se IGNORA en la tasa (aprobar sobre los valores
   originales no es evidencia de nada); si todos lo son, el examen es un
   espejo y el veredicto es 'no_examinable', no 'verificado'.

2. POSTCONDICIONES EJECUTABLES, no texto. Sin postcondiciones -> el veredicto
   es 'no_examinable'. Con postcondiciones SOLO de texto ('salida_contiene')
   tambien: juzgar por lo que el flujo dice de si mismo es exactamente el
   fallo del contrato interno (medido: al nivel del azar). Un tipo de check
   desconocido NO se ignora en silencio — invalida el examen; ignorarlo es
   como pasa un gate por el motivo equivocado.

3. LA CUARENTENA ES CODIGO, NO UNA CARPETA. Este repo ya se quemo con un
   `_cuarentena/` que funcionaba "por accidente" porque el glob no lo miraba.
   Aca la autoridad es el INDICE (indice.json) y `aptos_para_sugerir()` es
   FAIL-CLOSED: un fichero suelto en verificado/ sin entrada de indice que lo
   declare verificado NO es apto, y una entrada en cuarentena excluye al
   flujo aunque el fichero siga fisicamente en verificado/.

4. LA FIRMA ATA EL VEREDICTO AL FLUJO EXAMINADO. El veredicto lleva el sha256
   de la sustancia del flujo (pasos/postcondiciones/parametros/fixture).
   `promover()` la recalcula y RECHAZA si el flujo cambio despues del examen;
   `aptos_para_sugerir()` la recalcula sobre el fichero en disco y descarta el
   que fue editado despues de aprobar. Sin esto, "verificado" solo significa
   "hubo un examen alguna vez, de algo".

Contrato de datos (todo dict JSON-serializable; estilo del repo: funciones
planas, dicts, solo stdlib):

    flujo = {
      "nombre": "generar_informe",
      "tarea": "...",                       # opcional, para el contrafactual
      "pasos": [{"tool": "escribir_archivo", "args": "{ruta} | {texto}"}, ...],
      "parametros": {"ruta": "salida/informe.md", "texto": "hola"},
      "postcondiciones": [{"tipo": "existe", "ruta": "{ruta}"}, ...],
      "fixture": {"datos/entrada.txt": "1\n2\n"},   # opcional
    }

    veredicto = {"estado": "verificado"|"rechazado"|"no_examinable",
                 "casos": [...], "tasa_exito": float, "motivo": str,
                 "ts": float, "evidencia": {...}}

DEPENDENCIAS INYECTADAS (regla del repo: nada de mocks de la funcionalidad —
el modulo entero se prueba en seco):
    reproducir_fn(flujo, params, workspace) -> {"ok", "pasos", "salida", ...}
    agente_fn(tarea, params, workspace)     -> {"ok", "pasos", "salida", ...}
    ejecutar_fn(cmd, workspace)             -> {"codigo": int, "salida": str}
    completar_fn(flujo, caso_base, i)       -> dict (enriquece un caso)

Ninguna funcion publica LANZA: todas devuelven dicts (instrumentacion y
politica devuelven valores; el camino caliente no se rompe por la compuerta).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# ── Estados. Conjunto CERRADO: cualquier otro valor en el indice se trata
# como no-apto (fail-closed). ────────────────────────────────────────────────
BORRADOR = "borrador"
VERIFICADO = "verificado"
CUARENTENA = "cuarentena"
ESTADOS = (BORRADOR, VERIFICADO, CUARENTENA)

# Veredictos posibles del examen.
V_VERIFICADO = "verificado"
V_RECHAZADO = "rechazado"
V_NO_EXAMINABLE = "no_examinable"

# Tipos de postcondicion que el examen sabe EJECUTAR. Cerrado a proposito:
# un tipo fuera de esta lista invalida el examen en vez de ignorarse.
TIPOS_CHECK = (
    "existe", "no_existe", "contiene", "no_contiene",
    "json_clave", "lineas_min", "bytes_min", "comando", "salida_contiene",
)

# Checks DEBILES: juzgan el TEXTO que el flujo escupio, no el mundo. Sirven
# como complemento, jamas como unica evidencia (ver decision 2 del docstring).
TIPOS_DEBILES = ("salida_contiene",)

# ALIASES del vocabulario que emite el generalizador (cognia/flujos/
# generalizador.py) y verifica cognia/flujos/reproductor.py. Sin esto, la
# compuerta declararia 'no_examinable' TODO flujo generalizado por el
# subsistema —tipo desconocido— y la pieza no serviria para lo unico que
# tiene que hacer. Se traducen los NOMBRES, no la semantica: 'comando_exit0'
# es 'comando' con codigo esperado 0, que es exactamente lo que significa.
TIPOS_ALIAS = {
    "fichero_existe": "existe",
    "fichero_no_existe": "no_existe",
    "fichero_contiene": "contiene",
    "fichero_no_contiene": "no_contiene",
    "comando_exit0": "comando",
}

# Decay en produccion. 3 fallos SEGUIDOS podan; con >=5 usos, una tasa por
# debajo de 0.6 tambien. Los dos criterios existen porque cazan cosas
# distintas: el primero, la regresion brusca (algo del entorno cambio); el
# segundo, el flujo que siempre fue mediocre y aprobo el examen por suerte.
MAX_FALLOS_SEGUIDOS = 3
MIN_USOS_PARA_TASA = 5
TASA_MINIMA_PRODUCCION = 0.6

# Caducidad del veredicto en dias. 0 = sin caducidad. POR QUE caduca: el
# examen se corrio contra un entorno (tools, rutas, modelos) que se mueve; un
# 'verificado' de hace meses es una afirmacion sobre un mundo que ya no esta.
TTL_DIAS_DEFECTO = 30

# Umbral del examen: TODOS los casos juzgados tienen que pasar. No es
# arbitrario — con 3 casos, aceptar 2/3 (0.66) es aceptar un flujo que falla
# uno de cada tres usos, que es peor que no tenerlo (el usuario paga el paso
# en falso Y la correccion).
UMBRAL_DEFECTO = 1.0

_LOCK = threading.RLock()   # RLock: cuarentena() se llama DENTRO de registrar_uso()


# ═══════════════════════════════════════════════════════════════════════════
# Rutas y estado en disco
# ═══════════════════════════════════════════════════════════════════════════

def _home() -> Path:
    """~/.cognia, o COGNIA_HOME si el entorno lo redirige (misma convencion
    que arranque.py y capacidad.py). Se resuelve EN CADA LLAMADA, no en el
    import: los tests redirigen el home despues de importar el modulo."""
    crudo = os.environ.get("COGNIA_HOME", "").strip()
    return Path(crudo) if crudo else Path.home() / ".cognia"


def dir_flujos() -> Path:
    """Raiz del almacen de flujos. COGNIA_FLUJOS_DIR la redirige entera."""
    crudo = os.environ.get("COGNIA_FLUJOS_DIR", "").strip()
    return Path(crudo) if crudo else _home() / "flujos"


def _dir_estado(estado: str) -> Path:
    return dir_flujos() / estado


def _ruta_indice() -> Path:
    return dir_flujos() / "indice.json"


def _slug(nombre: str) -> str:
    """Nombre de fichero SEGURO. Un flujo llamado '../../id_rsa' escribiendo
    fuera del almacen no es teorico: el nombre lo propone quien graba."""
    limpio = re.sub(r"[^A-Za-z0-9_\-]+", "-", str(nombre or "").strip())
    limpio = limpio.strip("-")[:60]
    return limpio or "flujo-sin-nombre"


def _nombre_de(flujo) -> str:
    if isinstance(flujo, dict):
        return str(flujo.get("nombre") or "")
    return str(flujo or "")


def _leer_json(ruta: Path) -> Optional[dict]:
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else None
    except Exception:
        return None


def _escribir_json(ruta: Path, datos: dict) -> bool:
    """Escritura ATOMICA (tmp + replace). Un indice a medio escribir por un
    corte deja el almacen entero sin autoridad, y fail-closed significa que
    NADA queda apto: peor que perder la escritura."""
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(ruta.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(str(tmp), str(ruta))
        return True
    except Exception:
        return False


def leer_indice() -> dict:
    """El indice completo. Ilegible/corrupto -> {} (fail-closed: sin indice no
    hay nada apto, en vez de caer a 'lo que haya en la carpeta')."""
    datos = _leer_json(_ruta_indice()) or {}
    flujos = datos.get("flujos")
    return flujos if isinstance(flujos, dict) else {}


def _guardar_indice(flujos: dict) -> bool:
    return _escribir_json(_ruta_indice(), {"flujos": flujos, "ts": time.time()})


def _actualizar_entrada(nombre: str, cambios: dict) -> dict:
    """Read-modify-write del indice bajo candado. Devuelve la entrada final."""
    with _LOCK:
        flujos = leer_indice()
        entrada = dict(flujos.get(nombre) or {})
        entrada.update(cambios)
        flujos[nombre] = entrada
        _guardar_indice(flujos)
        return entrada


# ═══════════════════════════════════════════════════════════════════════════
# Firma: ata un veredicto al flujo EXACTO que se examino
# ═══════════════════════════════════════════════════════════════════════════

def firma_flujo(flujo: dict) -> str:
    """sha256 de la SUSTANCIA del flujo (lo que el examen realmente probo).

    Excluye estado/veredicto/uso/firma: esos cambian por el ciclo de vida y
    no alteran lo que el flujo HACE. Si esto incluyera 'usos_ok', registrar un
    uso invalidaria el veredicto y todo flujo usado caeria de apto."""
    if not isinstance(flujo, dict):
        return ""
    sustancia = {
        "nombre": flujo.get("nombre") or "",
        "pasos": flujo.get("pasos") or [],
        "parametros": flujo.get("parametros") or {},
        "params": flujo.get("params") or [],
        "postcondiciones": flujo.get("postcondiciones") or [],
        "fixture": flujo.get("fixture") or {},
        "tarea": flujo.get("tarea") or "",
    }
    try:
        crudo = json.dumps(sustancia, ensure_ascii=False, sort_keys=True)
    except Exception:
        crudo = repr(sustancia)
    return hashlib.sha256(crudo.encode("utf-8", "replace")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# Sustitucion de parametros
# ═══════════════════════════════════════════════════════════════════════════

_MARCA = re.compile(r"\{([A-Za-z0-9_]+)\}")


def sustituir(texto: str, params: dict) -> str:
    """Reemplaza {clave} por su valor. NO se usa str.format a proposito: los
    args de las tools y los contenidos llevan llaves literales (JSON, f-string
    de codigo generado) y format() revienta o come llaves ajenas."""
    if not isinstance(texto, str) or not texto:
        return texto if isinstance(texto, str) else ""
    params = params if isinstance(params, dict) else {}

    def _rep(m):
        clave = m.group(1)
        if clave in params:
            return str(params[clave])
        return m.group(0)        # marca desconocida: se deja tal cual, visible

    return _MARCA.sub(_rep, texto)


# ═══════════════════════════════════════════════════════════════════════════
# generar_casos: juegos de parametros NUEVOS, deterministicos
# ═══════════════════════════════════════════════════════════════════════════

def _es_ruta(valor: str) -> bool:
    if "/" in valor or "\\" in valor:
        return True
    return bool(re.match(r"^[\w\-. ]+\.[A-Za-z0-9]{1,6}$", valor))


def _variar_ruta(valor: str, semilla: int, estructural: bool) -> str:
    """Renombra el ultimo segmento preservando la extension. En el caso
    ESTRUCTURAL ademas ANIDA un nivel: cambia la profundidad de la ruta, que
    es lo que rompe a un flujo que asume 'el fichero cuelga de la raiz'."""
    sep = "\\" if ("\\" in valor and "/" not in valor) else "/"
    partes = [p for p in re.split(r"[\\/]", valor)]
    ultimo = partes[-1]
    base, punto, ext = ultimo.rpartition(".")
    nuevo = f"{base}_c{semilla}.{ext}" if punto else f"{ultimo}_c{semilla}"
    if estructural:
        partes = partes[:-1] + [f"sub_c{semilla}", nuevo]
    else:
        partes = partes[:-1] + [nuevo]
    return sep.join(partes)


def _variar_valor(valor, semilla: int, estructural: bool):
    """Variacion MECANICA y deterministica de un valor.

    El caso estructural no renombra: cambia la FORMA (profundidad de ruta,
    orden de magnitud, numero de tokens, longitud de lista, claves de dict).
    Un examen que solo renombra es un espejo con otro nombre."""
    if isinstance(valor, bool):
        return (not valor) if (estructural or semilla % 2 == 1) else valor
    if isinstance(valor, int):
        return valor * 10 + 7 if estructural else valor + semilla
    if isinstance(valor, float):
        return round(valor * 10 + 7, 6) if estructural else round(valor + semilla, 6)
    if isinstance(valor, str):
        if _es_ruta(valor):
            return _variar_ruta(valor, semilla, estructural)
        if estructural:
            # de 1 token a 3: cambia longitud y estructura del texto
            return f"{valor} {valor} c{semilla}"
        return f"{valor}_c{semilla}"
    if isinstance(valor, list):
        if estructural:
            # cambiar la LONGITUD es el cambio estructural de una lista
            if valor:
                return [_variar_valor(v, semilla, False) for v in valor] + \
                       [_variar_valor(valor[0], semilla + 1, False)]
            return [f"c{semilla}"]
        return [_variar_valor(v, semilla, False) for v in valor]
    if isinstance(valor, dict):
        nuevo = {k: _variar_valor(v, semilla, False) for k, v in valor.items()}
        if estructural:
            nuevo[f"extra_c{semilla}"] = f"c{semilla}"
        return nuevo
    if valor is None:
        return f"c{semilla}"
    return valor


def parametros_grabacion(flujo: dict) -> dict:
    """Los valores con los que el flujo se GRABO — el juego que hay que NO
    repetir en el examen. Acepta las dos formas que existen en el subsistema:

      * ``{"parametros": {clave: valor}}`` — la forma corta;
      * ``{"params": [{"nombre","tipo","ejemplo","obligatorio"}, ...]}`` — la
        que emite cognia/flujos/generalizador.py, donde el valor de la
        grabacion es el campo ``ejemplo``.

    Sin este adaptador la compuerta no generaria casos para NINGUN flujo
    generalizado por el subsistema (veria 'parametros' vacio y devolveria []),
    y el examen quedaria en 'no_examinable' para el caso real."""
    if not isinstance(flujo, dict):
        return {}
    cortos = flujo.get("parametros")
    if isinstance(cortos, dict) and cortos:
        return dict(cortos)
    largos = flujo.get("params")
    if isinstance(largos, list):
        fuera = {}
        for p in largos:
            if isinstance(p, dict) and p.get("nombre"):
                fuera[str(p["nombre"])] = p.get("ejemplo")
        return fuera
    return {}


def _difiere(params: dict, originales: dict) -> bool:
    try:
        return json.dumps(params, sort_keys=True, default=str) != \
               json.dumps(originales, sort_keys=True, default=str)
    except Exception:
        return params != originales


def generar_casos(flujo: dict, n: int = 3,
                  completar_fn: Optional[Callable] = None) -> list:
    """Deriva `n` juegos de parametros NUEVOS a partir de los de la grabacion.

    Deterministico por defecto (misma entrada -> misma salida): la semilla es
    el indice del caso, nada de random. El ULTIMO caso es siempre el
    ESTRUCTURAL — si todos fueran renombrados, el examen no distinguiria un
    flujo que aprendio de uno que memorizo con las etiquetas cambiadas.

    `completar_fn(flujo, caso_base, i) -> dict` enriquece un caso (p.ej. con
    un LLM que inventa valores realistas). Es OPT-IN y NO PUEDE DEBILITAR el
    examen: si lo que devuelve coincide con los parametros de la grabacion,
    se descarta y se conserva el caso mecanico. Si lanza, se ignora.

    Devuelve [] si el flujo no declara parametros: sin parametros no hay
    casos NUEVOS que construir, y examinar() lo dira ('no_examinable') en vez
    de aprobar un espejo.
    """
    if not isinstance(flujo, dict):
        return []
    originales = parametros_grabacion(flujo)
    if not originales:
        return []
    try:
        n = max(1, int(n))
    except Exception:
        n = 3

    casos = []
    for i in range(n):
        semilla = i + 1
        estructural = (i == n - 1)      # el ultimo SIEMPRE cambia la forma
        params = {k: _variar_valor(v, semilla, estructural)
                  for k, v in originales.items()}
        if estructural:
            # una clave de mas: el flujo no puede asumir el juego exacto
            params[f"extra_c{semilla}"] = f"c{semilla}"
        caso = {
            "nombre": f"caso{semilla}",
            "params": params,
            "estructural": estructural,
            "variacion": "estructural" if estructural else "renombrado",
            "enriquecido": False,
        }
        if completar_fn is not None:
            try:
                extra = completar_fn(flujo, dict(caso), i)
                if isinstance(extra, dict) and extra:
                    candidato = dict(params)
                    candidato.update(extra.get("params") if isinstance(
                        extra.get("params"), dict) else extra)
                    # El enriquecimiento NO puede devolver la grabacion. Se
                    # compara SOLO sobre las claves originales: si no, una
                    # clave decorativa de mas (la que el caso estructural
                    # agrega) hace pasar por "nuevo" un juego que devolvio
                    # todos los valores de la grabacion — el espejo entra por
                    # la puerta de atras.
                    nucleo = {k: candidato[k] for k in originales
                              if k in candidato}
                    if _difiere(nucleo, originales):
                        caso["params"] = candidato
                        caso["enriquecido"] = True
                    else:
                        caso["enriquecido"] = False
                        caso["aviso"] = ("completar_fn devolvio los parametros "
                                         "de la grabacion: descartado")
            except Exception as exc:
                caso["aviso"] = f"completar_fn fallo: {type(exc).__name__}"
        casos.append(caso)
    return casos


# ═══════════════════════════════════════════════════════════════════════════
# Postcondiciones: el juicio EJECUTABLE
# ═══════════════════════════════════════════════════════════════════════════

def _params_de(caso) -> dict:
    """Acepta el caso envuelto de generar_casos o un dict de params pelado."""
    if isinstance(caso, dict) and isinstance(caso.get("params"), dict):
        return caso["params"]
    return caso if isinstance(caso, dict) else {}


def _ruta_segura(workspace: Path, relativa: str):
    """Resuelve una ruta DENTRO del workspace. Fuera -> None.

    POR QUE: una postcondicion que mira un fichero de fuera del sandbox deja
    pasar al flujo por los restos de la grabacion (o de otro caso). El examen
    dejaria de medir lo que el flujo hizo AHORA."""
    try:
        base = workspace.resolve()
        destino = (base / str(relativa)).resolve()
        if destino == base or base in destino.parents:
            return destino
        return None
    except Exception:
        return None


def _leer_texto(ruta: Path) -> Optional[str]:
    try:
        return ruta.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _bajar_clave(datos, clave: str):
    """Camino con puntos: 'a.b.0.c'. Devuelve (encontrado, valor)."""
    actual = datos
    for parte in str(clave).split("."):
        if isinstance(actual, dict) and parte in actual:
            actual = actual[parte]
        elif isinstance(actual, list) and parte.isdigit() and int(parte) < len(actual):
            actual = actual[int(parte)]
        else:
            return False, None
    return True, actual


def _evaluar_check(chk, workspace: Path, params: dict, salida: str,
                   ejecutar_fn: Optional[Callable]) -> dict:
    """Evalua UNA postcondicion. Devuelve
    {tipo, ok, detalle, debil, falta_capacidad, desconocido}.
    NUNCA lanza: un check roto es un check que falla, con su motivo."""
    res = {"tipo": "", "ok": False, "detalle": "", "debil": False,
           "falta_capacidad": False, "desconocido": False}
    if not isinstance(chk, dict):
        res["detalle"] = f"postcondicion no es un dict: {type(chk).__name__}"
        res["desconocido"] = True
        return res
    # 'check' como sinonimo de 'tipo': es la clave que usa reproductor.py al
    # devolver sus verificaciones, y un flujo puede llegar con ese nombre.
    crudo = str(chk.get("tipo") or chk.get("check") or "").strip()
    tipo = TIPOS_ALIAS.get(crudo, crudo)
    res["tipo"] = tipo
    if crudo != tipo:
        res["alias_de"] = crudo
    if tipo not in TIPOS_CHECK:
        # NO se ignora: un tipo desconocido invalida el examen. Ignorarlo es
        # como aprueba un gate por el motivo equivocado (el fallo de 5
        # instrumentos en una noche de este repo).
        res["detalle"] = f"tipo de postcondicion desconocido: '{crudo}'"
        res["desconocido"] = True
        return res
    res["debil"] = tipo in TIPOS_DEBILES

    try:
        if tipo == "salida_contiene":
            texto = sustituir(str(chk.get("texto") or ""), params)
            res["ok"] = texto in (salida or "")
            res["detalle"] = ("texto presente en la salida" if res["ok"]
                              else f"la salida no contiene '{texto[:60]}'")
            return res

        if tipo == "comando":
            cmd = sustituir(str(chk.get("cmd") or chk.get("comando") or ""),
                            params)
            esperado = int(chk.get("codigo", 0))
            if ejecutar_fn is None:
                # honesto: no se puede juzgar, y eso NO es aprobar
                res["falta_capacidad"] = True
                res["detalle"] = ("postcondicion 'comando' sin ejecutar_fn "
                                  "inyectado: no se puede juzgar")
                return res
            crudo = ejecutar_fn(cmd, str(workspace))
            if isinstance(crudo, tuple) and len(crudo) >= 2:
                codigo, texto = int(crudo[0]), str(crudo[1])
            elif isinstance(crudo, dict):
                codigo, texto = int(crudo.get("codigo", 1)), str(crudo.get("salida", ""))
            else:
                codigo, texto = 1, str(crudo)
            res["ok"] = (codigo == esperado)
            res["detalle"] = f"'{cmd[:60]}' -> codigo {codigo} (esperado {esperado}); {texto[:80]}"
            return res

        # los demas tipos miran el WORKSPACE
        rel = sustituir(str(chk.get("ruta") or ""), params)
        destino = _ruta_segura(workspace, rel)
        if destino is None:
            res["detalle"] = f"ruta fuera del workspace o invalida: '{rel}'"
            return res

        if tipo == "existe":
            res["ok"] = destino.exists()
            res["detalle"] = f"{rel}: {'existe' if res['ok'] else 'NO existe'}"
            return res
        if tipo == "no_existe":
            res["ok"] = not destino.exists()
            res["detalle"] = f"{rel}: {'ausente (ok)' if res['ok'] else 'existe y no deberia'}"
            return res

        if not destino.exists():
            res["detalle"] = f"{rel}: no existe (requerido por '{tipo}')"
            return res

        if tipo in ("contiene", "no_contiene"):
            # 'contiene'/'patron': los nombres que usa el generalizador
            texto = sustituir(str(chk.get("texto") or chk.get("contiene")
                                  or chk.get("patron") or ""), params)
            cuerpo = _leer_texto(destino)
            if cuerpo is None:
                res["detalle"] = f"{rel}: ilegible"
                return res
            if chk.get("regex"):
                try:
                    dentro = re.search(texto, cuerpo) is not None
                except re.error as err:
                    # un patron invalido NO aprueba: es un check que no se
                    # puede correr, y aca eso siempre significa que no
                    res["detalle"] = f"{rel}: patron regex invalido ({err})"
                    return res
            else:
                dentro = texto in cuerpo
            res["ok"] = dentro if tipo == "contiene" else (not dentro)
            res["detalle"] = f"{rel}: '{texto[:40]}' {'presente' if dentro else 'ausente'}"
            return res

        if tipo == "lineas_min":
            cuerpo = _leer_texto(destino) or ""
            n = int(chk.get("n", 1))
            reales = len([x for x in cuerpo.splitlines() if x.strip()])
            res["ok"] = reales >= n
            res["detalle"] = f"{rel}: {reales} lineas no vacias (min {n})"
            return res

        if tipo == "bytes_min":
            n = int(chk.get("n", 1))
            reales = destino.stat().st_size
            res["ok"] = reales >= n
            res["detalle"] = f"{rel}: {reales} bytes (min {n})"
            return res

        if tipo == "json_clave":
            datos = _leer_json(destino)
            if datos is None:
                try:
                    datos = json.loads(_leer_texto(destino) or "")
                except Exception:
                    datos = None
            if datos is None:
                res["detalle"] = f"{rel}: no es JSON valido"
                return res
            clave = sustituir(str(chk.get("clave") or ""), params)
            hallado, valor = _bajar_clave(datos, clave)
            if not hallado:
                res["detalle"] = f"{rel}: falta la clave '{clave}'"
                return res
            if "valor" in chk:
                esperado = chk["valor"]
                if isinstance(esperado, str):
                    esperado = sustituir(esperado, params)
                res["ok"] = (valor == esperado)
                res["detalle"] = f"{rel}:{clave} = {valor!r} (esperado {esperado!r})"
            else:
                res["ok"] = True
                res["detalle"] = f"{rel}: clave '{clave}' presente"
            return res

    except Exception as exc:
        res["detalle"] = f"check '{tipo}' revento: {type(exc).__name__}: {exc}"
        return res

    res["detalle"] = f"tipo '{tipo}' sin implementacion"
    res["desconocido"] = True
    return res


def verificar_postcondiciones(postcondiciones, workspace, caso,
                              *, salida: str = "",
                              ejecutar_fn: Optional[Callable] = None) -> dict:
    """Evalua TODAS las postcondiciones (no corta en la primera que falla: la
    evidencia sirve para arreglar el flujo, no solo para reprobarlo).

    Devuelve {ok, checks, fallados, desconocidos, falta_capacidad, solo_debiles}."""
    params = _params_de(caso)
    ws = Path(str(workspace))
    checks = []
    for chk in (postcondiciones or []):
        checks.append(_evaluar_check(chk, ws, params, salida, ejecutar_fn))
    duros = [c for c in checks if not c["debil"] and not c["desconocido"]]
    return {
        "ok": bool(checks) and all(c["ok"] for c in checks),
        "checks": checks,
        "fallados": [c for c in checks if not c["ok"]],
        "desconocidos": [c for c in checks if c["desconocido"]],
        "falta_capacidad": any(c["falta_capacidad"] for c in checks),
        "solo_debiles": bool(checks) and not duros,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Workspace temporal aislado
# ═══════════════════════════════════════════════════════════════════════════

def _preparar_workspace(base: Optional[str], etiqueta: str, flujo: dict,
                        params: dict) -> Path:
    """Crea un directorio VACIO para un caso y siembra el fixture del flujo.

    Aislado por caso (no por examen): si dos casos comparten directorio, el
    segundo puede aprobar por los ficheros que dejo el primero — el estado
    INDUCIDO por un brazo no compara."""
    if base:
        raiz = Path(str(base))
        raiz.mkdir(parents=True, exist_ok=True)
        ws = Path(tempfile.mkdtemp(prefix=f"{etiqueta}_", dir=str(raiz)))
    else:
        ws = Path(tempfile.mkdtemp(prefix=f"cognia_examen_{etiqueta}_"))
    fixture = flujo.get("fixture") if isinstance(flujo, dict) else None
    if isinstance(fixture, dict):
        for rel, contenido in fixture.items():
            destino = _ruta_segura(ws, sustituir(str(rel), params))
            if destino is None:
                continue
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(sustituir(str(contenido), params),
                                   encoding="utf-8")
            except Exception:
                pass    # un fixture que no se puede sembrar hara fallar el check
    return ws


def _borrar(ws: Path) -> None:
    try:
        shutil.rmtree(str(ws), ignore_errors=True)
    except Exception:
        pass


def _correr_brazo(fn: Callable, args: tuple) -> dict:
    """Llama a reproducir_fn/agente_fn midiendo pared y sin dejar que una
    excepcion suya rompa el examen (un brazo que revienta es un brazo que
    falla, con su motivo — 'fallo' y 'no habia nada' piden decisiones
    distintas y las dos tienen que quedar escritas)."""
    t0 = time.perf_counter()
    try:
        crudo = fn(*args)
        pared = time.perf_counter() - t0
        if not isinstance(crudo, dict):
            crudo = {"ok": bool(crudo), "salida": str(crudo)}
        return {
            "ok": bool(crudo.get("ok", False)),
            "pasos": int(crudo.get("pasos", 0) or 0),
            "salida": str(crudo.get("salida", "") or ""),
            "error": str(crudo.get("error", "") or ""),
            "pared_s": round(pared, 6),
            "reventado": False,
        }
    except Exception as exc:
        return {"ok": False, "pasos": 0, "salida": "",
                "error": f"{type(exc).__name__}: {exc}",
                "pared_s": round(time.perf_counter() - t0, 6),
                "reventado": True}


# ═══════════════════════════════════════════════════════════════════════════
# examinar: LA COMPUERTA
# ═══════════════════════════════════════════════════════════════════════════

def examinar(flujo: dict, casos, reproducir_fn: Callable, *,
             workspace_tmp: Optional[str] = None,
             ejecutar_fn: Optional[Callable] = None,
             umbral: float = UMBRAL_DEFECTO,
             conservar_workspace: bool = False) -> dict:
    """Corre el examen y devuelve el VEREDICTO. No lanza y no toca el disco
    del almacen: decidir y GUARDAR la decision estan separados a proposito
    (promover/cuarentena hacen lo segundo, y solo con un veredicto en mano).

    Cada caso corre en su propio workspace temporal y se juzga por las
    postcondiciones del flujo. Un caso identico a los parametros de la
    grabacion se IGNORA (no suma ni resta): aprobar sobre los valores
    originales no distingue aprender de memorizar.

    'no_examinable' es un veredicto de PRIMERA CLASE, no un error: sin
    postcondiciones, con postcondiciones solo de texto, con un tipo de check
    desconocido, sin casos nuevos o sin la capacidad de correr un check, la
    respuesta honesta es "no se puede juzgar" — jamas 'verificado'.
    """
    ts = time.time()
    nombre = _nombre_de(flujo) or "sin-nombre"
    evidencia = {
        "flujo": nombre,
        "firma_flujo": firma_flujo(flujo) if isinstance(flujo, dict) else "",
        "pasos_declarados": len((flujo or {}).get("pasos") or []) if isinstance(flujo, dict) else 0,
        "umbral": umbral,
        "casos_total": 0, "casos_ok": 0, "casos_ignorados": 0,
        "estructurales": 0, "checks_totales": 0, "checks_fallados": 0,
        "ejecutar_fn": bool(ejecutar_fn),
        "reproducir_fn": getattr(reproducir_fn, "__name__", str(reproducir_fn))[:60],
    }

    def _veredicto(estado, casos_res, tasa, motivo):
        return {"estado": estado, "casos": casos_res, "tasa_exito": tasa,
                "motivo": motivo, "ts": ts, "evidencia": evidencia,
                "firma_flujo": evidencia["firma_flujo"], "nombre": nombre}

    if not isinstance(flujo, dict):
        return _veredicto(V_NO_EXAMINABLE, [], 0.0,
                          "el flujo no es un dict")
    if not callable(reproducir_fn):
        return _veredicto(V_NO_EXAMINABLE, [], 0.0,
                          "no se inyecto reproducir_fn")

    post = flujo.get("postcondiciones") or []
    if not isinstance(post, list) or not post:
        # el agujero de las skills: "salio bien" no es una postcondicion
        return _veredicto(V_NO_EXAMINABLE, [], 0.0,
                          "el flujo no declara postcondiciones: no hay nada "
                          "ejecutable que juzgar (salir bien una vez no es "
                          "evidencia)")
    evidencia["postcondiciones"] = len(post)
    if all(isinstance(c, dict) and str(c.get("tipo") or "") in TIPOS_DEBILES
           for c in post):
        return _veredicto(V_NO_EXAMINABLE, [], 0.0,
                          "todas las postcondiciones juzgan TEXTO "
                          f"({', '.join(TIPOS_DEBILES)}): hace falta al menos "
                          "una que mire el mundo (fichero, JSON, codigo de "
                          "salida)")

    casos = list(casos or [])
    if not casos:
        return _veredicto(V_NO_EXAMINABLE, [], 0.0,
                          "sin casos nuevos que probar")

    originales = parametros_grabacion(flujo)
    resultados = []
    juzgados = 0
    aprobados = 0
    falta_capacidad = False
    desconocidos = False

    for i, caso in enumerate(casos):
        params = _params_de(caso)
        etiqueta = _slug(f"{nombre}-{(caso or {}).get('nombre', i) if isinstance(caso, dict) else i}")
        estructural = bool(caso.get("estructural")) if isinstance(caso, dict) else False
        if estructural:
            evidencia["estructurales"] += 1

        fila = {
            "nombre": (caso.get("nombre") if isinstance(caso, dict) else "") or f"caso{i + 1}",
            "params": params,
            "estructural": estructural,
            "ok": False, "ignorado": False, "motivo": "",
            "checks": [], "pasos": 0, "pared_s": 0.0, "workspace": "",
        }

        # Mirar SOLO las claves de la grabacion: un caso que repite todos sus
        # valores y agrega una clave decorativa sigue siendo un espejo.
        nucleo = {k: params[k] for k in originales if k in params} \
            if isinstance(originales, dict) else {}
        if isinstance(originales, dict) and originales and not _difiere(nucleo, originales):
            # ESPEJO: los parametros de la grabacion. No prueba nada.
            fila["ignorado"] = True
            fila["motivo"] = ("mismo juego de parametros que la grabacion: "
                              "no distingue aprender de memorizar")
            resultados.append(fila)
            evidencia["casos_ignorados"] += 1
            continue

        ws = _preparar_workspace(workspace_tmp, etiqueta, flujo, params)
        fila["workspace"] = str(ws)
        brazo = _correr_brazo(reproducir_fn, (flujo, params, str(ws)))
        fila["pasos"] = brazo["pasos"]
        fila["pared_s"] = brazo["pared_s"]

        juicio = verificar_postcondiciones(post, ws, params,
                                           salida=brazo["salida"],
                                           ejecutar_fn=ejecutar_fn)
        fila["checks"] = juicio["checks"]
        evidencia["checks_totales"] += len(juicio["checks"])
        evidencia["checks_fallados"] += len(juicio["fallados"])
        if juicio["falta_capacidad"]:
            falta_capacidad = True
        if juicio["desconocidos"]:
            desconocidos = True

        # El veredicto lo dan las POSTCONDICIONES. `ok` del reproducir_fn solo
        # entra para explicar el motivo: un flujo que "dice" que fallo pero
        # dejo el mundo correcto sigue aprobando, y al reves NO aprueba.
        fila["ok"] = bool(juicio["ok"])
        if not fila["ok"]:
            fallos = "; ".join(c["detalle"] for c in juicio["fallados"][:3])
            if brazo["reventado"]:
                fila["motivo"] = f"la reproduccion revento: {brazo['error']}"
            elif not brazo["ok"] and not fallos:
                fila["motivo"] = f"la reproduccion no termino ok: {brazo['error'][:120]}"
            else:
                fila["motivo"] = fallos or "postcondiciones no cumplidas"
        juzgados += 1
        if fila["ok"]:
            aprobados += 1
        resultados.append(fila)

        if not conservar_workspace:
            _borrar(ws)
            fila["workspace_borrado"] = True

    evidencia["casos_total"] = len(resultados)
    evidencia["casos_ok"] = aprobados
    tasa = (aprobados / juzgados) if juzgados else 0.0

    if desconocidos:
        return _veredicto(V_NO_EXAMINABLE, resultados, tasa,
                          "hay postcondiciones de tipo desconocido: el examen "
                          "no puede juzgarlas y no se ignoran en silencio")
    if falta_capacidad:
        return _veredicto(V_NO_EXAMINABLE, resultados, tasa,
                          "falta la capacidad de ejecutar alguna postcondicion "
                          "(inyecta ejecutar_fn): no juzgable")
    if juzgados == 0:
        return _veredicto(V_NO_EXAMINABLE, resultados, 0.0,
                          "todos los casos repetian los parametros de la "
                          "grabacion: el examen seria un espejo")
    if evidencia["estructurales"] == 0:
        evidencia["aviso"] = ("ningun caso cambio la ESTRUCTURA: el examen "
                              "solo probo renombrados")

    if tasa + 1e-9 >= umbral:
        return _veredicto(V_VERIFICADO, resultados, tasa,
                          f"{aprobados}/{juzgados} casos nuevos cumplen las "
                          f"postcondiciones")
    fallidos = [f["nombre"] for f in resultados if not f["ok"] and not f["ignorado"]]
    return _veredicto(V_RECHAZADO, resultados, tasa,
                      f"{aprobados}/{juzgados} casos (umbral {umbral:g}); "
                      f"falla: {', '.join(fallidos[:4])}")


# ═══════════════════════════════════════════════════════════════════════════
# contrafactual: la comparacion que nadie hace
# ═══════════════════════════════════════════════════════════════════════════

def contrafactual_activo() -> bool:
    """El contrafactual es CARO (corre el agente entero). Va bajo bandera:
    COGNIA_FLUJOS_CONTRAFACTUAL=1."""
    return os.environ.get("COGNIA_FLUJOS_CONTRAFACTUAL", "").strip() in ("1", "si", "true")


def contrafactual(flujo: dict, caso, reproducir_fn: Callable,
                  agente_fn: Callable, *,
                  workspace_tmp: Optional[str] = None,
                  ejecutar_fn: Optional[Callable] = None,
                  tarea: str = "",
                  activo: Optional[bool] = None) -> dict:
    """Resuelve el MISMO caso por los dos caminos y reporta AMBOS brazos.

    POR QUE EXISTE: sin esto, "el flujo funciono" no dice si el flujo APORTA.
    Un flujo puede aprobar el examen y aun asi costar mas pasos y mas pared
    que el agente resolviendolo de cero — en ese caso sugerirlo es empeorar
    el sistema con la sensacion de mejorarlo. La leccion medida del repo es
    literal: el CONTRAFACTUAL es la unica defensa contra un numero que parece
    verificado sin estarlo.

    Los dos brazos corren en workspaces SEPARADOS y virgenes (el estado
    inducido por un brazo no compara) y se juzgan con LAS MISMAS
    postcondiciones. Devuelve siempre las dos columnas, gane quien gane:
    {gana_flujo, pasos_flujo, pasos_agente, pared_flujo, pared_agente,
     ok_flujo, ok_agente, motivo, ejecutado}.
    """
    base = {
        "ejecutado": False, "gana_flujo": None,
        "pasos_flujo": 0, "pasos_agente": 0,
        "pared_flujo": 0.0, "pared_agente": 0.0,
        "ok_flujo": False, "ok_agente": False,
        "motivo": "", "checks_flujo": [], "checks_agente": [],
    }
    if activo is None:
        activo = contrafactual_activo()
    if not activo:
        base["motivo"] = ("apagado: es caro (corre el agente entero). "
                          "COGNIA_FLUJOS_CONTRAFACTUAL=1 o activo=True")
        return base
    if not isinstance(flujo, dict) or not callable(reproducir_fn) or not callable(agente_fn):
        base["motivo"] = "faltan flujo, reproducir_fn o agente_fn"
        return base

    post = flujo.get("postcondiciones") or []
    if not post:
        base["motivo"] = ("sin postcondiciones no hay con que juzgar los dos "
                          "brazos: la comparacion seria de texto")
        return base

    params = _params_de(caso)
    tarea = tarea or str(flujo.get("tarea") or flujo.get("nombre") or "")
    nombre = _slug(_nombre_de(flujo) or "flujo")

    ws_f = _preparar_workspace(workspace_tmp, f"{nombre}-cf-flujo", flujo, params)
    brazo_f = _correr_brazo(reproducir_fn, (flujo, params, str(ws_f)))
    juicio_f = verificar_postcondiciones(post, ws_f, params,
                                         salida=brazo_f["salida"],
                                         ejecutar_fn=ejecutar_fn)

    ws_a = _preparar_workspace(workspace_tmp, f"{nombre}-cf-agente", flujo, params)
    brazo_a = _correr_brazo(agente_fn, (tarea, params, str(ws_a)))
    juicio_a = verificar_postcondiciones(post, ws_a, params,
                                         salida=brazo_a["salida"],
                                         ejecutar_fn=ejecutar_fn)

    ok_f, ok_a = bool(juicio_f["ok"]), bool(juicio_a["ok"])
    p_f, p_a = brazo_f["pasos"], brazo_a["pasos"]
    w_f, w_a = brazo_f["pared_s"], brazo_a["pared_s"]

    # Criterio, en este orden y declarado: primero CORRECCION (un flujo que no
    # cumple no gana aunque sea rapido), despues PASOS (lo que el usuario
    # espera del atajo), y solo con pasos empatados, la pared.
    if ok_f and not ok_a:
        gana, motivo = True, "solo el flujo cumple las postcondiciones"
    elif ok_a and not ok_f:
        gana, motivo = False, "solo el agente cumple las postcondiciones"
    elif not ok_f and not ok_a:
        gana, motivo = False, "ninguno cumple: el flujo no aporta nada"
    elif p_f < p_a:
        gana, motivo = True, f"ambos cumplen; el flujo usa {p_f} pasos vs {p_a}"
    elif p_f > p_a:
        gana, motivo = False, f"ambos cumplen; el flujo usa MAS pasos ({p_f} vs {p_a})"
    elif w_f < w_a:
        gana, motivo = True, f"empate en pasos ({p_f}); el flujo es mas rapido"
    else:
        gana, motivo = False, (f"empate en pasos ({p_f}) y el flujo no es mas "
                               "rapido: no aporta")

    resultado = dict(base)
    resultado.update({
        "ejecutado": True, "gana_flujo": gana,
        "pasos_flujo": p_f, "pasos_agente": p_a,
        "pared_flujo": w_f, "pared_agente": w_a,
        "ok_flujo": ok_f, "ok_agente": ok_a,
        "motivo": motivo,
        "checks_flujo": juicio_f["checks"], "checks_agente": juicio_a["checks"],
        "error_flujo": brazo_f["error"], "error_agente": brazo_a["error"],
        "workspace_flujo": str(ws_f), "workspace_agente": str(ws_a),
        "tarea": tarea, "params": params,
    })
    _borrar(ws_f)
    _borrar(ws_a)
    return resultado


# ═══════════════════════════════════════════════════════════════════════════
# Estados en disco: promover / cuarentena
# ═══════════════════════════════════════════════════════════════════════════

def _buscar_fichero(nombre: str) -> Optional[Path]:
    slug = _slug(nombre)
    for estado in ESTADOS:
        cand = _dir_estado(estado) / f"{slug}.json"
        if cand.exists():
            return cand
    return None


def _mover_a(nombre: str, estado: str, flujo: Optional[dict] = None,
             extra: Optional[dict] = None) -> str:
    """Escribe el flujo en el directorio del estado y borra las otras copias.
    Devuelve la ruta relativa al almacen ('' si no se pudo escribir)."""
    slug = _slug(nombre)
    if flujo is None:
        origen = _buscar_fichero(nombre)
        flujo = _leer_json(origen) if origen else None
    if not isinstance(flujo, dict):
        return ""
    cuerpo = dict(flujo)
    cuerpo["estado"] = estado
    cuerpo["firma"] = firma_flujo(flujo)
    if extra:
        cuerpo.update(extra)
    destino = _dir_estado(estado) / f"{slug}.json"
    if not _escribir_json(destino, cuerpo):
        return ""
    for otro in ESTADOS:
        if otro == estado:
            continue
        viejo = _dir_estado(otro) / f"{slug}.json"
        try:
            if viejo.exists():
                viejo.unlink()
        except Exception:
            pass
    return f"{estado}/{slug}.json"


def guardar_borrador(flujo: dict) -> dict:
    """Persiste un flujo recien grabado como BORRADOR. Nace no-apto: solo un
    veredicto 'verificado' lo saca de aca."""
    nombre = _nombre_de(flujo)
    if not isinstance(flujo, dict) or not nombre:
        return {"ok": False, "motivo": "flujo sin nombre"}
    rel = _mover_a(nombre, BORRADOR, flujo)
    if not rel:
        return {"ok": False, "motivo": "no se pudo escribir el borrador"}
    _actualizar_entrada(nombre, {
        "estado": BORRADOR, "ruta": rel, "firma": firma_flujo(flujo),
        "ts": time.time(), "motivo": "recien grabado, sin examen",
    })
    return {"ok": True, "nombre": nombre, "estado": BORRADOR, "ruta": rel}


def promover(flujo: dict, veredicto: dict) -> dict:
    """borrador -> verificado. SOLO con un veredicto 'verificado' cuya firma
    coincida con el flujo de AHORA.

    La firma no es paranoia: sin ella, "verificado" significa "hubo un examen
    alguna vez, de algo" — se podria examinar un flujo inofensivo y promover
    otro. No lanza: devuelve {ok:False, motivo} y el flujo se queda donde
    estaba (fail-closed)."""
    nombre = _nombre_de(flujo)
    if not isinstance(flujo, dict) or not nombre:
        return {"ok": False, "motivo": "flujo sin nombre", "estado": ""}
    if not isinstance(veredicto, dict):
        return {"ok": False, "motivo": "veredicto ausente", "estado": ""}
    estado_v = veredicto.get("estado")
    if estado_v != V_VERIFICADO:
        return {"ok": False, "estado": BORRADOR,
                "motivo": f"el veredicto es '{estado_v}': no promueve "
                          f"({veredicto.get('motivo', '')[:120]})"}
    firma_ahora = firma_flujo(flujo)
    firma_examen = veredicto.get("firma_flujo") or \
        (veredicto.get("evidencia") or {}).get("firma_flujo") or ""
    if firma_examen and firma_examen != firma_ahora:
        return {"ok": False, "estado": BORRADOR,
                "motivo": "el flujo cambio DESPUES del examen (firma distinta): "
                          "el veredicto no lo cubre"}

    rel = _mover_a(nombre, VERIFICADO, flujo, {"veredicto": veredicto})
    if not rel:
        return {"ok": False, "estado": BORRADOR,
                "motivo": "no se pudo escribir el flujo verificado"}
    _actualizar_entrada(nombre, {
        "estado": VERIFICADO, "ruta": rel, "firma": firma_ahora,
        "veredicto_ts": veredicto.get("ts") or time.time(),
        "tasa_exito": veredicto.get("tasa_exito", 0.0),
        "motivo": veredicto.get("motivo", ""),
        "evidencia": veredicto.get("evidencia") or {},
        "usos_ok": 0, "usos_fallo": 0, "fallos_seguidos": 0, "ultimo_uso": 0.0,
        "ts": time.time(),
    })
    return {"ok": True, "nombre": nombre, "estado": VERIFICADO, "ruta": rel}


def cuarentena(flujo, motivo: str = "") -> dict:
    """Manda un flujo a cuarentena. Acepta el dict o solo el nombre.

    LA CUARENTENA ES CODIGO: lo que excluye al flujo es la ENTRADA DEL INDICE,
    no la carpeta. Se intenta mover el fichero (higiene), pero si el move
    falla —permisos, fichero abierto, un glob de otro modulo que lo copio— el
    flujo queda igual de excluido, porque `aptos_para_sugerir()` lee el indice
    y es fail-closed. Este repo ya se quemo con un `_cuarentena/` que
    funcionaba por accidente porque el glob no lo miraba."""
    nombre = _nombre_de(flujo)
    if not nombre:
        return {"ok": False, "motivo": "flujo sin nombre", "estado": ""}
    dict_flujo = flujo if isinstance(flujo, dict) else None
    rel = _mover_a(nombre, CUARENTENA, dict_flujo)
    entrada = _actualizar_entrada(nombre, {
        "estado": CUARENTENA,
        "ruta": rel or (leer_indice().get(nombre) or {}).get("ruta", ""),
        "motivo": motivo or "sin motivo declarado",
        "cuarentena_ts": time.time(),
    })
    return {"ok": True, "nombre": nombre, "estado": CUARENTENA,
            "ruta": entrada.get("ruta", ""), "motivo": entrada.get("motivo", ""),
            "fichero_movido": bool(rel)}


# ═══════════════════════════════════════════════════════════════════════════
# aptos_para_sugerir + decay
# ═══════════════════════════════════════════════════════════════════════════

def _ttl_segundos() -> float:
    crudo = os.environ.get("COGNIA_FLUJOS_TTL_DIAS", "").strip()
    try:
        dias = float(crudo) if crudo else float(TTL_DIAS_DEFECTO)
    except Exception:
        dias = float(TTL_DIAS_DEFECTO)
    return max(0.0, dias) * 86400.0


def estado_de(nombre: str) -> dict:
    """La entrada del indice para un flujo ({} si no esta). El indice es la
    AUTORIDAD: si no hay entrada, el flujo no existe para el sistema aunque
    haya un fichero suyo en disco."""
    return dict(leer_indice().get(str(nombre)) or {})


def aptos_para_sugerir(*, ahora: Optional[float] = None,
                       incluir_flujo: bool = True) -> list:
    """Los flujos que el sistema PUEDE sugerir. FAIL-CLOSED en cuatro puntos:

    1. el indice tiene que declararlo 'verificado' (un fichero suelto en
       verificado/ sin entrada NO cuenta: la carpeta no es la autoridad);
    2. el fichero tiene que existir y ser legible;
    3. su firma actual tiene que coincidir con la registrada al verificar
       (editado despues de aprobar -> fuera);
    4. el veredicto no puede estar caducado (COGNIA_FLUJOS_TTL_DIAS).

    Cualquier duda excluye. Un flujo de menos es una sugerencia que no se
    hace; un flujo de mas envenena tareas ajenas — el coste no es simetrico.
    """
    ahora = time.time() if ahora is None else float(ahora)
    ttl = _ttl_segundos()
    salida = []
    for nombre, entrada in sorted(leer_indice().items()):
        if not isinstance(entrada, dict):
            continue
        if entrada.get("estado") != VERIFICADO:
            continue                      # cuarentena y borrador, fuera
        rel = str(entrada.get("ruta") or "")
        ruta = dir_flujos() / rel if rel else None
        cuerpo = _leer_json(ruta) if ruta else None
        if cuerpo is None:
            continue                      # declarado apto y sin fichero: fuera
        firma_reg = str(entrada.get("firma") or "")
        if firma_reg and firma_flujo(cuerpo) != firma_reg:
            continue                      # editado despues de aprobar
        vts = float(entrada.get("veredicto_ts") or 0.0)
        if ttl > 0 and vts > 0 and (ahora - vts) > ttl:
            continue                      # caducado
        fila = {
            "nombre": nombre,
            "ruta": str(ruta),
            "estado": VERIFICADO,
            "tasa_exito": float(entrada.get("tasa_exito") or 0.0),
            "veredicto_ts": vts,
            "usos_ok": int(entrada.get("usos_ok") or 0),
            "usos_fallo": int(entrada.get("usos_fallo") or 0),
            "fallos_seguidos": int(entrada.get("fallos_seguidos") or 0),
        }
        if incluir_flujo:
            fila["flujo"] = cuerpo
        salida.append(fila)
    salida.sort(key=lambda d: (d["fallos_seguidos"], -d["tasa_exito"],
                               -d["usos_ok"], d["nombre"]))
    return salida


def registrar_uso(nombre: str, ok: bool) -> dict:
    """Anota un uso REAL en produccion y PODA si el flujo empezo a fallar.

    El examen dice que el flujo servia en el momento de examinarlo; el mundo
    se mueve (rutas, tools, modelos). El decay es la unica forma de que un
    flujo aprobado pueda DEJAR de estar aprobado sin que nadie lo mire: N
    fallos seguidos (regresion brusca) o una tasa de produccion pobre con
    suficientes usos (aprobo por suerte) mandan a cuarentena automatica.

    Devuelve {ok, estado, podado, motivo, fallos_seguidos, usos_ok, usos_fallo}.
    No lanza: es camino caliente (se llama al terminar cada uso)."""
    nombre = str(nombre or "")
    with _LOCK:
        entrada = dict(leer_indice().get(nombre) or {})
        if not entrada:
            return {"ok": False, "estado": "", "podado": False,
                    "motivo": f"'{nombre}' no esta en el indice"}
        usos_ok = int(entrada.get("usos_ok") or 0)
        usos_fallo = int(entrada.get("usos_fallo") or 0)
        seguidos = int(entrada.get("fallos_seguidos") or 0)
        if ok:
            usos_ok += 1
            seguidos = 0
        else:
            usos_fallo += 1
            seguidos += 1
        entrada = _actualizar_entrada(nombre, {
            "usos_ok": usos_ok, "usos_fallo": usos_fallo,
            "fallos_seguidos": seguidos, "ultimo_uso": time.time(),
        })

        total = usos_ok + usos_fallo
        tasa = (usos_ok / total) if total else 1.0
        motivo_poda = ""
        if seguidos >= MAX_FALLOS_SEGUIDOS:
            motivo_poda = (f"decay: {seguidos} fallos SEGUIDOS en produccion "
                           f"(limite {MAX_FALLOS_SEGUIDOS})")
        elif total >= MIN_USOS_PARA_TASA and tasa < TASA_MINIMA_PRODUCCION:
            motivo_poda = (f"decay: tasa de produccion {tasa:.2f} en {total} "
                           f"usos (minimo {TASA_MINIMA_PRODUCCION})")

        if motivo_poda and entrada.get("estado") != CUARENTENA:
            cuarentena(nombre, motivo_poda)
            return {"ok": True, "estado": CUARENTENA, "podado": True,
                    "motivo": motivo_poda, "fallos_seguidos": seguidos,
                    "usos_ok": usos_ok, "usos_fallo": usos_fallo,
                    "tasa_produccion": round(tasa, 4)}
        return {"ok": True, "estado": entrada.get("estado", ""), "podado": False,
                "motivo": "", "fallos_seguidos": seguidos,
                "usos_ok": usos_ok, "usos_fallo": usos_fallo,
                "tasa_produccion": round(tasa, 4)}


# ═══════════════════════════════════════════════════════════════════════════
# Atajo de conveniencia para el cableado
# ═══════════════════════════════════════════════════════════════════════════

def examinar_y_decidir(flujo: dict, reproducir_fn: Callable, *,
                       n_casos: int = 3,
                       completar_fn: Optional[Callable] = None,
                       ejecutar_fn: Optional[Callable] = None,
                       workspace_tmp: Optional[str] = None) -> dict:
    """El camino completo en una llamada: generar casos -> examinar ->
    promover o dejar en borrador. Pensado para el cableado (una linea al
    terminar la grabacion). Devuelve {veredicto, decision}.

    Un veredicto 'rechazado' o 'no_examinable' NO manda a cuarentena: el
    flujo se queda en borrador, que ya es no-apto. La cuarentena es para lo
    que fallo DESPUES de aprobar — mezclarlas borraria la diferencia entre
    'nunca demostro servir' y 'servia y dejo de servir'."""
    casos = generar_casos(flujo, n=n_casos, completar_fn=completar_fn)
    veredicto = examinar(flujo, casos, reproducir_fn,
                         workspace_tmp=workspace_tmp, ejecutar_fn=ejecutar_fn)
    if veredicto.get("estado") == V_VERIFICADO:
        decision = promover(flujo, veredicto)
    else:
        decision = guardar_borrador(flujo)
        decision["motivo"] = veredicto.get("motivo", "")
    return {"veredicto": veredicto, "decision": decision, "casos": casos}
