# -*- coding: utf-8 -*-
"""
cognia/harness/enlaces.py -- Rutas de fichero CLICABLES en el transcript (OSC 8)
================================================================================
POR QUE EXISTE (2026-08-23): el transcript de Cognia esta lleno de rutas (el
render colapsado de tools, el ultimo spill de /offload) y hoy son texto muerto:
abrir el fichero exige seleccionar la ruta, copiarla y pegarla en otro lado.
Windows Terminal soporta hyperlinks OSC 8 (ctrl+click abre el file://) y rich
ya sabe emitirlos (style 'link <target>'): lo unico que faltaba era decidir QUE
se enlaza y con que target.

REGLAS (las de CodeWhale, adoptadas tal cual):
 - Solo se enlazan esquemas http(s) y file:// ABSOLUTOS. Aca: rutas absolutas
   de fichero QUE EXISTEN (la existencia es el filtro anti-falso-positivo:
   'C:v' o un /comando jamas se enlazan porque no son ficheros reales).
 - El target va percent-encodeado (urllib.parse.quote: controles, espacios y
   todo lo no seguro) — un ESC o un BEL crudos dentro del target ROMPEN la
   propia secuencia OSC 8.
 - El target JAMAS aparece en el texto visible: el link vive en escapes
   invisibles y la seleccion/copia del texto queda byte-identica al plano.

CONTRATO: funciones puras salvo `texto_rich` (importa rich LAZY y devuelve un
Text, o None si no aplica). Nada imprime; nada lanza (el error se traga
devolviendo el camino plano — el integrador decide si avisa degradado).

CONFIG (a call-time): env COGNIA_ENLACES=0 apaga GANANDO a la config ('1'
fuerza); sin env decide la clave 'enlaces' (default on, se cambia con
/enlaces on|off). El integrador ademas exige tty de verdad: sin terminal el
fallback es el texto plano byte-identico.

PUNTO DE EXTENSION: _RUTAS es la lista de regex candidatos; un esquema nuevo
(http en el transcript, p. ej.) se agrega con su regex + su constructor de
target en `_target_para`, sin tocar a los integradores.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

# Candidatos a ruta: absoluta Windows (C:\... o C:/...) o absoluta POSIX.
# Se excluyen espacios, comillas y los chars invalidos de NTFS; el filtro
# final es os.path.exists, asi que el regex solo acota donde mirar.
_RX_WIN = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|*?\x00-\x1f]+")
_RX_POSIX = re.compile(r"(?<![\w:\\/])/[^\s\"'<>|*?\x00-\x1f]+")
_RUTAS = (_RX_WIN, _RX_POSIX)

# Puntuacion de cierre que el texto pega a la ruta (' -> fichero: x.txt).' o
# '(ver C:\x.txt)'): se recorta del final del candidato antes de mirar disco.
_PUNTUACION_FINAL = ".,;:)]}\"'"


def activo(cfg: dict | None = None) -> bool:
    """Si los enlaces estan encendidos. env COGNIA_ENLACES gana a la config."""
    v = (os.environ.get("COGNIA_ENLACES") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "si", "on"):
        return True
    # P6 (2026-08-24): /estilo enlace visible off apaga el OSC 8 (E9). La env
    # sigue ganando (arriba); el registro gana a la config 'enlaces'.
    from cognia.ux import aspecto as _A
    if not _A.visible("enlace"):
        return False
    base = cfg
    if base is None:
        try:
            _cli = sys.modules.get("cognia.cli")
            base = _cli._load_config() if _cli is not None else {}
        except Exception:
            base = {}
    return str(base.get("enlaces", "on")).strip().lower() not in (
        "off", "0", "false", "no")


def target_de(ruta: str) -> str:
    """El target file:/// de una ruta ABSOLUTA, saneado.

    Percent-encodea todo lo no seguro (controles incluidos) via Path.as_uri,
    con un fallback manual con quote() cuando as_uri no puede. Una ruta
    relativa o vacia devuelve '' (jamas se enlaza un target relativo).
    Defensa final: si algun control o espacio sobreviviera, se re-encodea —
    un byte < 0x20 crudo dentro del OSC 8 corta la secuencia.
    """
    r = (ruta or "").strip()
    if not r or not os.path.isabs(r):
        return ""
    try:
        uri = Path(r).resolve().as_uri()
    except (ValueError, OSError):
        try:
            plano = str(Path(r)).replace("\\", "/")
            if not plano.startswith("/"):
                plano = "/" + plano
            uri = "file://" + quote(plano, safe="/:")
        except Exception:
            return ""
    # Cinturon: cualquier control/espacio que quede se percent-encodea.
    return "".join(f"%{ord(c):02X}" if ord(c) < 0x21 or ord(c) == 0x7f else c
                   for c in uri)


def _recortar_puntuacion(candidato: str) -> str:
    return candidato.rstrip(_PUNTUACION_FINAL)


def enlaces_en(texto: str) -> list:
    """Los spans enlazables de una linea: [(inicio, fin, target), ...].

    Solo rutas ABSOLUTAS que EXISTEN en disco (fichero o directorio). Sin
    solapes y en orden; una linea sin rutas devuelve [] y el integrador
    imprime plano sin pagar nada mas.
    """
    t = texto or ""
    spans: list = []
    ocupado: list = []
    for rx in _RUTAS:
        for m in rx.finditer(t):
            cand = _recortar_puntuacion(m.group(0))
            if not cand:
                continue
            ini, fin = m.start(), m.start() + len(cand)
            if any(ini < f and fin > i for i, f in ocupado):
                continue
            try:
                if not (os.path.isabs(cand) and os.path.exists(cand)):
                    continue
            except (OSError, ValueError):
                continue
            target = target_de(cand)
            if target:
                spans.append((ini, fin, target))
                ocupado.append((ini, fin))
    spans.sort(key=lambda s: s[0])
    return spans


def marcar_markup(texto: str) -> str:
    """La linea con markup de rich: cada ruta envuelta en [link=target]...
    Para los caminos que imprimen CON markup (cli._print_line). El texto
    visible no cambia: solo se agregan tags invisibles. Sin rutas devuelve el
    texto tal cual."""
    t = texto or ""
    spans = enlaces_en(t)
    if not spans:
        return t
    out, pos = [], 0
    for ini, fin, target in spans:
        out.append(t[pos:ini])
        out.append(f"[link={target}]{t[ini:fin]}[/link]")
        pos = fin
    out.append(t[pos:])
    return "".join(out)


def texto_rich(texto: str, estilo: str = ""):
    """Un rich.Text con las rutas linkeadas (estilo base `estilo`), o None si
    no aplica (sin rutas, o sin rich): el caller imprime el plano de siempre.
    El plain del Text devuelto es IDENTICO al texto de entrada — el link es
    estilo, no contenido."""
    t = texto or ""
    spans = enlaces_en(t)
    if not spans:
        return None
    try:
        from rich.text import Text
    except ImportError:
        return None
    rico = Text(t, style=estilo or "")
    for ini, fin, target in spans:
        rico.stylize("link " + target, ini, fin)
    return rico
