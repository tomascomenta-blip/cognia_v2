# -*- coding: utf-8 -*-
"""Vocabulario CERRADO de claves del LIBRO (ESPEC 3.4).

POR QUE UN VOCABULARIO CERRADO Y NO TEXTO LIBRE: la deteccion de
contradicciones es un `GROUP BY clave HAVING COUNT(DISTINCT valor) > 1`
(ESPEC 3.4 y 7.6). Con claves libres, "el test de canal" y "tests/estado" son
dos claves distintas para el mismo hecho y el GROUP BY no cruza nada: la
contradiccion existe y el gate dice verde. Un vocabulario cerrado convierte la
deteccion en aritmetica.

QUIEN EMITE CADA PREFIJO (la mitad del valor esta aqui): `archivo:`, `cmd:`,
`test:`, `err:` y `cfg:` los emite el INTERCEPTOR desde una medicion; `regla:`
lo teclea el dueno; `dec:` y `nota:` son los unicos que puede emitir el modelo
-- y son exactamente los dos que quedan FUERA de la deteccion por clave
(punto ciego DECLARADO, ESPEC 7.6, no escondido).
"""

import hashlib
import os
import re

# El orden importa: `prefijo()` devuelve el primero que casa, y ninguno es
# prefijo de otro, asi que no hay ambiguedad que resolver.
PREFIJOS = ("archivo:", "cmd:", "test:", "err:", "cfg:", "regla:", "dec:", "nota:")

# Los unicos que puede escribir el modelo. Ver el docstring del modulo.
PREFIJOS_DEL_MODELO = ("dec:", "nota:")

# Excluidos del GROUP BY de contradicciones (G4). Son prosa: dos `dec:` con
# distinto valor no son una contradiccion medible, son dos opiniones. Si
# entraran, G4 abortaria resets por desacuerdos del modelo consigo mismo, que
# es justo el juicio que este diseno saca de la ruta critica.
PREFIJOS_SIN_CONTRADICCION = ("dec:", "nota:")

_RE_CLAVE = re.compile(r"^(archivo|cmd|test|err|cfg|regla|dec|nota):.+")

# Firma de error: TIPO + el simbolo mas cercano. Normalizada a proposito para
# que dos AssertionError del mismo test colapsen en UNA firma y el contador
# `firma -> n` de la banda N cuente lo que tiene que contar.
_RE_ERROR = re.compile(
    r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Failure))\b[: ]*(.{0,80})")


def valida(clave) -> bool:
    """True si `clave` pertenece al vocabulario cerrado. NUNCA lanza."""
    try:
        return bool(_RE_CLAVE.match(str(clave or "")))
    except Exception:
        return False


def prefijo(clave) -> str:
    """El prefijo de `clave` con los dos puntos, o '' si no es del vocabulario."""
    texto = str(clave or "")
    for p in PREFIJOS:
        if texto.startswith(p):
            return p
    return ""


def es_del_modelo(clave) -> bool:
    return prefijo(clave) in PREFIJOS_DEL_MODELO


def cuenta_para_contradiccion(clave) -> bool:
    """Si esta clave entra en el GROUP BY de G4. Ver PREFIJOS_SIN_CONTRADICCION."""
    p = prefijo(clave)
    return bool(p) and p not in PREFIJOS_SIN_CONTRADICCION


def sha14(dato) -> str:
    """sha256[:14] -- el formato del LIBRO (ESPEC 3.2). Mismo que el interceptor."""
    if isinstance(dato, str):
        dato = dato.encode("utf-8", "replace")
    return hashlib.sha256(dato or b"").hexdigest()[:14]


def sha_de_fichero(ruta):
    """sha256[:14] del contenido en DISCO, o None si no se pudo leer.

    None y no '' ni el sha del vacio: "no pude leer" y "el fichero esta vacio"
    piden decisiones opuestas en G3 (la primera es una averia del gate, la
    segunda es un hecho del mundo) y desde fuera se verian igual.
    """
    try:
        with open(str(ruta), "rb") as fh:
            return sha14(fh.read())
    except Exception:
        return None


def firma_error(texto):
    """`err:<Tipo>:<simbolo>` a partir de una cola de error, o None si no hay.

    None cuando no se reconoce nada: inventar una firma con la primera linea
    haria que cada corrida generase una firma distinta y el contador anti-loop
    (banda N) contaria 1 para siempre -- un detector que nunca dispara es peor
    que no tenerlo, porque parece que vigila.
    """
    m = _RE_ERROR.search(str(texto or ""))
    if not m:
        return None
    tipo = m.group(1)
    cola = re.sub(r"[^A-Za-z0-9_./-]+", "_", (m.group(2) or "").strip())[:40]
    cola = cola.strip("_")
    return "err:" + tipo + (":" + cola if cola else "")


def canonica(tool, args, out, exit_code=None, ruta_destino=None, sha=None):
    """(clave, valor) canonicos de UNA llamada a tool. Funcion pura salvo por
    el sha de disco, que solo se calcula si el llamador no lo trajo.

    La tabla de la ESPEC 3.4, aplicada:
      - la tool escribio un fichero  -> ('archivo:<ruta>', sha256[:14] del disco)
      - hubo exit code entero        -> ('cmd:<tool>', exit_code)  [test: si es pytest]
      - no hubo exit code            -> ('cmd:<tool>', None)

    `valor=None` NO es `valor=0`. Un comando bloqueado por el sentinel no se
    ejecuto nunca y no puede entrar como exito (P0-1). Se propaga tal cual.
    """
    nombre = str(tool or "")
    destino = ruta_destino
    if destino is None:
        try:
            from cognia.harness.interceptor import ruta_destino as _rd
            destino = _rd(nombre, args or "")
        except Exception:
            destino = ""
    if destino:
        ruta = str(destino).replace("\\", "/")
        valor = sha if sha is not None else sha_de_fichero(destino)
        return ("archivo:" + ruta, valor)

    medido = isinstance(exit_code, int) and not isinstance(exit_code, bool)
    crudo = " ".join([nombre, str(args or "")]).lower()
    # `test:` es un `cmd:` cuyo valor canonico es el booleano exit==0 (ESPEC
    # 3.4). Se separa porque un criterio del contrato pregunta "paso?", no
    # "que exit dio", y mezclarlos hace que un exit 1 y un exit 4 cuenten como
    # dos valores distintos de la misma clave: G4 veria una contradiccion
    # donde solo hay dos formas de fallar.
    if "pytest" in crudo or crudo.startswith("test "):
        return ("test:" + (str(args or nombre).strip()[:120] or nombre),
                (exit_code == 0) if medido else None)
    return ("cmd:" + (str(args or "").strip()[:120] or nombre),
            exit_code if medido else None)


def de_evento(evento):
    """La clave de un evento ya armado, o '' si no trae ninguna. Nunca lanza."""
    try:
        return str((evento or {}).get("clave") or "")
    except Exception:
        return ""


def ruta_de_clave(clave):
    """La ruta de una clave `archivo:`, o None. Util para G3."""
    if prefijo(clave) != "archivo:":
        return None
    return str(clave)[len("archivo:"):] or None


def normalizar_ruta(ruta, workspace=None):
    """Ruta absoluta con separadores '/' para comparar contra el LIBRO.

    Se resuelve contra el WORKSPACE y no contra el CWD del proceso: es el mismo
    bug que P0-3 arreglo en GoalContract, y aqui produciria un G3 que hashea un
    fichero homonimo de otra carpeta y dice OK.
    """
    texto = str(ruta or "")
    if not texto:
        return ""
    if not os.path.isabs(texto) and workspace:
        texto = os.path.join(str(workspace), texto)
    return os.path.normpath(texto).replace("\\", "/")
