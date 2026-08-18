"""
cognia/agent/gguf_meta.py
=========================
Los METADATOS del GGUF servido, leidos del fichero. Solo stdlib.

POR QUE EXISTE (2026-08-17). El repo decide cosas del modelo por SUBSTRING DEL
NOMBRE DEL FICHERO, y la memoria del repo ya tiene la factura: "toda tabla que
decida por nombre de modelo es una bomba". La bomba concreta que destapo esta
tarea: el cerebro principal de la casa es
``Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf`` y el repo lo
declaraba "Qwen2.5 abliterado" en dos sitios (flota.py y model_profiles.py).
El propio GGUF dice otra cosa, y esto se VERIFICO leyendolo:

    general.architecture          = qwen35
    general.base_model.0.name     = Qwen3.5 9B
    general.base_model.0.repo_url = https://huggingface.co/Qwen/Qwen3.5-9B
    qwen35.context_length         = 1048576   (yarn factor 4.0 sobre 262144)
    qwen35.block_count            = 33        (9 con attn_k, 24 SSM: HIBRIDO)

Un nombre se renombra y una tabla por substring se queda muda; la arquitectura
viaja DENTRO del fichero. Este modulo la saca sin dependencias externas
(gguf-py no es dependencia de runtime de cognia) parseando SOLO la cabecera
key-value, que son los primeros kilobytes del fichero.

Contrato: `meta(ruta)` -> dict (vacio si no se pudo leer). NUNCA lanza: quien
lo llama esta en el camino caliente del agente y un metadato ausente jamas
puede tumbar una corrida.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

# Tipos de valor del formato GGUF (ggml/src/gguf.cpp, enum gguf_type).
_U8, _I8, _U16, _I16, _U32, _I32, _F32, _BOOL, _STR, _ARR, _U64, _I64, _F64 = range(13)

# (formato de struct, bytes) por tipo escalar.
_ESCALAR = {
    _U8: ("<B", 1), _I8: ("<b", 1), _U16: ("<H", 2), _I16: ("<h", 2),
    _U32: ("<I", 4), _I32: ("<i", 4), _F32: ("<f", 4), _BOOL: ("<?", 1),
    _U64: ("<Q", 8), _I64: ("<q", 8), _F64: ("<d", 8),
}

# Techo de lo que se MATERIALIZA en RAM (las claves que interesan). La
# chat_template, que es el valor grande de verdad, mide 2,5-17 KB en los GGUF
# de esta casa: 8 MB es holgura x500 y a la vez el corte que impide que un
# fichero corrupto pida un read() de 2^63 bytes.
#
# Lo que se SALTA no cuenta contra este techo porque no se lee: se hace seek.
# Medido 2026-08-17 y por eso existe la distincion — la cabecera KV de Qwythos
# y de gpt-oss pasa de 8 MB ella sola (vocabulario de 151k-200k tokens +
# merges), asi que un unico tope para leer-y-saltar daba {} justo en los dos
# modelos que motivaron esta tarea. El limite del salto es el TAMANO REAL DEL
# FICHERO, que es el guard exacto y no una constante inventada.
_MAX_MATERIAL = 8 * 1024 * 1024

# Cache por (ruta, tamano, mtime): un GGUF de 5,7 GB no cambia entre turnos y
# esto lo llama el camino del agente. La clave lleva tamano+mtime para que
# reemplazar el fichero por otro (mismo nombre) no sirva metadatos rancios —
# que es exactamente la averia del :8088 en la memoria del repo.
_CACHE: dict = {}


class _Lector:
    """Cursor sobre la cabecera del GGUF. Dos operaciones con dos guards:
    `leer` materializa (tope de RAM) y `saltar` hace seek (tope = el fichero).
    """

    def __init__(self, fh, tamano: int) -> None:
        self._fh = fh
        self._tamano = tamano
        self._material = _MAX_MATERIAL

    def leer(self, n: int) -> bytes:
        if n < 0 or n > self._material:
            raise ValueError(f"lectura de {n} bytes fuera del tope de RAM")
        self._material -= n
        b = self._fh.read(n)
        if len(b) != n:
            raise ValueError("cabecera GGUF truncada")
        return b

    def saltar(self, n: int) -> None:
        """Avanza n bytes sin leerlos. Un n que se pasa del fichero delata una
        longitud corrupta (o un formato que no entendemos) y corta ahi."""
        pos = self._fh.tell()
        if n < 0 or pos + n > self._tamano:
            raise ValueError(f"salto de {n} bytes fuera del fichero")
        self._fh.seek(n, os.SEEK_CUR)

    def escalar(self, tipo: int):
        fmt, n = _ESCALAR[tipo]
        return struct.unpack(fmt, self.leer(n))[0]

    def entero(self, ancho: int) -> int:
        # GGUF v1 usa u32 para longitudes/contadores; v2+ usa u64.
        return struct.unpack("<I" if ancho == 4 else "<Q", self.leer(ancho))[0]


def _leer_valor(lec: _Lector, tipo: int, ancho: int):
    """Un valor GGUF. Los arrays se devuelven como lista (los de tokenizer
    tienen 150k entradas: por eso `_saltar_valor` existe y se usa)."""
    if tipo == _STR:
        return lec.leer(lec.entero(ancho)).decode("utf-8", "replace")
    if tipo == _ARR:
        sub = lec.entero(4)
        n = lec.entero(ancho)
        return [_leer_valor(lec, sub, ancho) for _ in range(n)]
    return lec.escalar(tipo)


def _saltar_valor(lec: _Lector, tipo: int, ancho: int) -> None:
    """Consume un valor sin materializarlo. Sin esto, leer la arquitectura
    (que va primera) obligaba igual a construir la lista de 151.936 tokens del
    vocabulario para llegar a las claves de mas abajo."""
    if tipo == _STR:
        lec.saltar(lec.entero(ancho))
        return
    if tipo == _ARR:
        sub = lec.entero(4)
        n = lec.entero(ancho)
        if sub in _ESCALAR:
            lec.saltar(_ESCALAR[sub][1] * n)
        else:
            for _ in range(n):
                _saltar_valor(lec, sub, ancho)
        return
    lec.escalar(tipo)


# Claves que SI se materializan. El resto se salta: la cabecera de Qwythos
# trae 151.936 strings de vocabulario y leerlas costaria ~0,5 s por llamada.
def _interesa(clave: str) -> bool:
    if clave in ("general.architecture", "general.name", "general.basename",
                 "general.size_label", "general.finetune",
                 "general.base_model.0.name",
                 "general.base_model.0.repo_url",
                 "general.sampling.temp", "general.sampling.top_p",
                 "tokenizer.chat_template"):
        return True
    # <arch>.context_length / <arch>.block_count, sin saber aun el arch.
    return clave.endswith((".context_length", ".block_count"))


def _crudo(ruta: str) -> dict:
    """Las claves interesantes de la cabecera, tal cual vienen. Lanza si el
    fichero no es un GGUF legible (el que cachea traduce a {})."""
    with open(ruta, "rb") as fh:
        lec = _Lector(fh, os.path.getsize(ruta))
        if lec.leer(4) != b"GGUF":
            raise ValueError("no empieza con el magic GGUF")
        version = struct.unpack("<I", lec.leer(4))[0]
        if version not in (1, 2, 3):
            raise ValueError(f"version GGUF no soportada: {version}")
        ancho = 4 if version == 1 else 8
        lec.entero(ancho)                 # tensor_count (no se usa aca)
        n_kv = lec.entero(ancho)
        if n_kv > 100_000:
            raise ValueError(f"metadata_kv_count absurdo: {n_kv}")
        out = {}
        for _ in range(n_kv):
            clave = lec.leer(lec.entero(ancho)).decode("utf-8", "replace")
            tipo = lec.entero(4)
            if _interesa(clave):
                out[clave] = _leer_valor(lec, tipo, ancho)
            else:
                _saltar_valor(lec, tipo, ancho)
        return out


def meta(ruta) -> dict:
    """Metadatos del GGUF en `ruta`, o {} si no se pudo leer.

    Claves devueltas (las que el fichero declare):
      arch        general.architecture — 'qwen35', 'gpt-oss', 'qwen2', ...
      base        general.base_model.0.name — 'Qwen3.5 9B'
      nombre      general.name
      n_ctx_train <arch>.context_length
      bloques     <arch>.block_count
      plantilla   tokenizer.chat_template (cruda)
      sampling    {'temperature','top_p'} si el GGUF los declara
                  (general.sampling.*: Nemotron 3.5 los trae, Qwythos no)
    """
    try:
        p = Path(str(ruta))
        st = p.stat()
        clave = (str(p), st.st_size, int(st.st_mtime))
    except Exception:
        return {}
    if clave in _CACHE:
        return dict(_CACHE[clave])
    try:
        kv = _crudo(str(p))
    except Exception:
        kv = None
    if kv is None:
        _CACHE[clave] = {}
        return {}
    arch = str(kv.get("general.architecture") or "")
    out = {"arch": arch}
    for destino, origen in (("base", "general.base_model.0.name"),
                            ("nombre", "general.name"),
                            ("plantilla", "tokenizer.chat_template")):
        v = kv.get(origen)
        if isinstance(v, str) and v:
            out[destino] = v
    for destino, sufijo in (("n_ctx_train", ".context_length"),
                            ("bloques", ".block_count")):
        v = kv.get(f"{arch}{sufijo}")
        if isinstance(v, int):
            out[destino] = v
    sampling = {}
    for destino, origen in (("temperature", "general.sampling.temp"),
                            ("top_p", "general.sampling.top_p")):
        v = kv.get(origen)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            sampling[destino] = round(float(v), 4)
    if sampling:
        out["sampling"] = sampling
    _CACHE[clave] = out
    return dict(out)


def resetear_cache() -> None:
    """Olvida los metadatos cacheados (tests y `cognia doctor --forzar`)."""
    _CACHE.clear()


if __name__ == "__main__":       # `python -m cognia.agent.gguf_meta <gguf>`
    import json
    import sys
    for arg in sys.argv[1:] or [os.environ.get("LLAMA_GGUF_PATH", "")]:
        print(arg)
        print(json.dumps({k: (v[:120] + "..." if isinstance(v, str) and len(v) > 120 else v)
                          for k, v in meta(arg).items()},
                         indent=2, ensure_ascii=False))
