# -*- coding: utf-8 -*-
"""
cognia/agent/formato_tools.py
=============================
Validadores y lectores para que el agente COMPRUEBE lo que escribe (familia de
pruebas, 2026-09-07). Pedido del dueno: "se queja de muchas cosas que no le
dejan probar". Antes de esto, un HTML con un <div> sin cerrar, un CSS con una
llave de mas o un JSON roto solo se descubrian al renderizar (si habia
navegador) o nunca; un PDF/DOCX/XLSX/GLB generado era una caja negra; y un
programa interactivo solo se podia probar de un tiro (ejecutar_guion).

Tools que registra (register(tool)):
  formato_validar   decide por extension: html/css/js/json/yaml/toml/xml/svg/
                    csv/md/py/ini/sql/bat/ps1/sh
  diff_texto        unified diff fichero-fichero o fichero-texto
  sql_probar        sentencias contra :memoria: o una COPIA de un .db
  pdf_inspeccionar / pdf_ver        pymupdf
  docx_texto                        python-docx
  xlsx_leer                         openpyxl
  modelo3d_inspeccionar / modelo3d_ver   trimesh + matplotlib (sin GPU)
  py_lint / py_importar / py_perfilar / py_cobertura
  http_solicitud / puerto_esperar / esperar_fichero
  consola_sesion    proceso interactivo PERSISTENTE entre llamadas
  tui_probar        programa de terminal en pseudo-tty + pantalla emulada (pyte)

Convenciones: resultados "RESULTADO <tool> ...:" / "RESULTADO <tool> ERROR: ...";
dependencias ausentes con el pip exacto (pruebas_comun.importar/binario); nada
de except mudo; PNG al scratchpad (pruebas_comun.ruta_salida).
"""
from __future__ import annotations

import atexit
import configparser
import csv
import difflib
import html.parser
import io
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from cognia.agent import pruebas_comun as _pc

MAX_SALIDA = 4000
_ULTIMO: dict = {"tool": "", "objetivo": "", "ok": None, "detalle": "", "ts": 0.0}


def _anotar(tool: str, objetivo: str, ok, detalle: str = "") -> None:
    _ULTIMO.update({"tool": tool, "objetivo": str(objetivo)[:200], "ok": ok,
                    "detalle": str(detalle)[:200], "ts": time.time()})


def ultimo() -> dict:
    """Ultima tool de la familia que corrio (puerta /probar estado)."""
    return dict(_ULTIMO)


def _capar(texto: str, tope: int = MAX_SALIDA) -> str:
    if len(texto) <= tope:
        return texto
    return texto[:tope] + "\n... [recortado: %d chars mas]" % (len(texto) - tope)


def _partir_cmd(args: str, claves) -> tuple:
    """Como pruebas_comun.partir_args pero SIN quitar las comillas del
    objetivo: para un comando ('"C:/ruta con espacios/python.exe" "x.py"')
    ese strip dejaba las comillas desparejadas y el primer token salia con
    una comilla colgando (cazado en tui_probar)."""
    s = (args or "").strip()
    opts: dict = {}
    if claves:
        patron = re.compile(r"(?:\|\s*|\s+)(%s)\s*=\s*" % "|".join(re.escape(c) for c in claves), re.I)
        while True:
            ms = list(patron.finditer(s))
            if not ms:
                break
            m = ms[-1]
            val = s[m.end():].strip().strip("|").strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            opts[m.group(1).lower()] = val
            s = s[:m.start()].strip().rstrip("|").strip()
    return s, opts


def _tam_y_lineas(p: Path) -> str:
    try:
        n = p.stat().st_size
    except OSError:
        n = 0
    try:
        lineas = p.read_text(encoding="utf-8", errors="replace").count("\n") + 1
    except Exception:
        lineas = 0
    return "%d bytes, %d lineas" % (n, lineas)


def _leer(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ===========================================================================
# formato_validar
# ===========================================================================

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}
# cierre implicito legal en HTML5: abrir uno de estos cierra al anterior igual
_AUTOCIERRE = {"li", "p", "dt", "dd", "option", "tr", "td", "th", "thead", "tbody", "tfoot"}


class _ParserHTML(html.parser.HTMLParser):
    """Detecta etiquetas sin cerrar / mal anidadas (no-void), atributos
    duplicados y recursos locales inexistentes. No es un validador W3C: caza
    lo que rompe el render de verdad."""

    def __init__(self, base: Path):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.pila: list = []            # [(tag, linea)]
        self.problemas: list = []
        self.recursos = 0

    def handle_starttag(self, tag, attrs):
        linea = self.getpos()[0]
        vistos = set()
        for k, v in attrs:
            if k in vistos:
                self.problemas.append("linea %d: <%s> atributo '%s' duplicado" % (linea, tag, k))
            vistos.add(k)
            if k in ("src", "href") and v:
                self._recurso(tag, v, linea)
        if tag in _VOID:
            return
        if tag in _AUTOCIERRE and self.pila and self.pila[-1][0] == tag:
            self.pila.pop()             # <li>...<li>: cierre implicito
        self.pila.append((tag, linea))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and self.pila and self.pila[-1][0] == tag:
            self.pila.pop()

    def handle_endtag(self, tag):
        linea = self.getpos()[0]
        if tag in _VOID:
            return
        nombres = [t for t, _ in self.pila]
        if tag not in nombres:
            self.problemas.append("linea %d: </%s> cierra algo que no esta abierto" % (linea, tag))
            return
        # cerrar hasta encontrarla: lo que quede en medio esta sin cerrar
        while self.pila:
            t, l = self.pila.pop()
            if t == tag:
                break
            if t not in _AUTOCIERRE:
                self.problemas.append("linea %d: <%s> (abierto en linea %d) sin cerrar antes de </%s>"
                                      % (linea, t, l, tag))

    def _recurso(self, tag, valor, linea):
        v = valor.strip()
        if not v or v.startswith(("#", "http:", "https:", "//", "data:", "mailto:", "tel:",
                                  "javascript:", "file:", "blob:")):
            return
        if tag == "a" and not re.search(r"\.[a-z0-9]{1,5}(\?|$)", v, re.I):
            return                      # rutas de router / anclas de SPA
        limpio = v.split("?", 1)[0].split("#", 1)[0]
        if not limpio:
            return
        self.recursos += 1
        cand = (self.base / limpio)
        if not cand.exists():
            attr = "href" if tag in ("a", "link") else "src"
            self.problemas.append("linea %d: <%s %s=\"%s\"> no existe junto al fichero"
                                  % (linea, tag, attr, v))

    def cerrar(self):
        for t, l in self.pila:
            if t not in _AUTOCIERRE and t not in ("html", "body", "head"):
                self.problemas.append("linea %d: <%s> nunca se cierra" % (l, t))


def _validar_html(p: Path) -> list:
    texto = _leer(p)
    parser = _ParserHTML(p.parent)
    try:
        parser.feed(texto)
        parser.close()
    except Exception as exc:
        return ["parser: %s: %s" % (type(exc).__name__, str(exc)[:160])]
    parser.cerrar()
    # <script>/<style> sin cerrar: html.parser se los traga como CDATA hasta EOF
    for tag in ("script", "style"):
        abiertos = len(re.findall(r"<%s\b[^>]*>" % tag, texto, re.I))
        cerrados = len(re.findall(r"</%s\s*>" % tag, texto, re.I))
        if abiertos > cerrados:
            parser.problemas.append("<%s> abiertos: %d, cerrados: %d (uno sin cerrar se come el resto de la pagina)"
                                    % (tag, abiertos, cerrados))
    return parser.problemas


def _validar_css(p: Path) -> list:
    texto = _leer(p)
    problemas = []
    sin_comentarios = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), texto, flags=re.S)
    prof = 0
    for i, linea in enumerate(sin_comentarios.splitlines(), 1):
        for ch in linea:
            if ch == "{":
                prof += 1
            elif ch == "}":
                prof -= 1
                if prof < 0:
                    problemas.append("linea %d: '}' de mas" % i)
                    prof = 0
    if prof > 0:
        problemas.append("%d llave(s) '{' sin cerrar al final del fichero" % prof)
    if sin_comentarios.count("(") != sin_comentarios.count(")"):
        problemas.append("parentesis desbalanceados: %d '(' y %d ')'"
                         % (sin_comentarios.count("("), sin_comentarios.count(")")))
    # bloques: selector { declaraciones }
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", sin_comentarios):
        selector, cuerpo = m.group(1).strip(), m.group(2)
        linea = sin_comentarios.count("\n", 0, m.start()) + 1
        if not selector:
            problemas.append("linea %d: bloque sin selector" % linea)
        if selector.startswith("@"):
            continue
        decls = [d.strip() for d in cuerpo.split(";")]
        ultima = decls[-1] if decls else ""
        if ultima and ":" in ultima and "\n" in ultima.strip("\n") and len(ultima.split(":")) > 2:
            problemas.append("linea %d: en '%s' hay una propiedad sin ';' antes de '}' (%s)"
                             % (linea, selector[:40], ultima.strip()[:60]))
        for d in decls:
            if d and ":" not in d:
                problemas.append("linea %d: en '%s' la declaracion '%s' no tiene ':'"
                                 % (linea, selector[:40], d[:50]))
    for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", sin_comentarios):
        u = m.group(1).strip()
        if u.startswith(("http:", "https:", "data:", "//", "#")):
            continue
        if not (p.parent / u.split("?")[0]).exists():
            problemas.append("linea %d: url(%s) no existe junto al fichero"
                             % (sin_comentarios.count("\n", 0, m.start()) + 1, u))
    return problemas


def _validar_js(p: Path) -> list:
    try:
        node = _pc.binario("node", "instala Node.js para validar sintaxis JS")
    except ValueError as exc:
        return ["AVISO: %s; sintaxis JS sin comprobar" % exc]
    rc, out, err = _pc.correr([node, "--check", str(p)], timeout=30)
    if rc == 0:
        return []
    txt = (err or out).strip()
    lineas = [l for l in txt.splitlines() if l.strip()][:8]
    return ["node --check: " + " | ".join(lineas)[:600]]


def _validar_json(p: Path) -> list:
    try:
        json.loads(_leer(p))
        return []
    except json.JSONDecodeError as exc:
        return ["linea %d col %d: %s" % (exc.lineno, exc.colno, exc.msg)]


def _validar_yaml(p: Path) -> list:
    yaml = _pc.importar("yaml")
    try:
        list(yaml.safe_load_all(_leer(p)))
        return []
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        pos = " (linea %d col %d)" % (mark.line + 1, mark.column + 1) if mark else ""
        return [(getattr(exc, "problem", None) or str(exc))[:200] + pos]


def _validar_toml(p: Path) -> list:
    import tomllib
    try:
        tomllib.loads(_leer(p))
        return []
    except tomllib.TOMLDecodeError as exc:
        return [str(exc)[:200]]


def _validar_xml(p: Path, svg: bool) -> list:
    import xml.etree.ElementTree as ET
    try:
        raiz = ET.fromstring(_leer(p).encode("utf-8"))
    except ET.ParseError as exc:
        return ["XML mal formado: %s" % exc]
    problemas = []
    if svg:
        etiqueta = raiz.tag.split("}")[-1]
        if etiqueta != "svg":
            problemas.append("la raiz es <%s>, no <svg>" % etiqueta)
        if "viewBox" not in raiz.attrib and not ("width" in raiz.attrib and "height" in raiz.attrib):
            problemas.append("<svg> sin viewBox ni width+height: el tamano queda al azar del navegador")
    ids: dict = {}
    for el in raiz.iter():
        i = el.attrib.get("id")
        if i:
            ids[i] = ids.get(i, 0) + 1
    for i, n in ids.items():
        if n > 1:
            problemas.append("id '%s' repetido %d veces" % (i, n))
    return problemas


def _validar_csv(p: Path) -> list:
    texto = _leer(p)
    if not texto.strip():
        return ["fichero vacio"]
    try:
        dialecto = csv.Sniffer().sniff(texto[:4000])
    except csv.Error:
        dialecto = csv.excel
    filas = list(csv.reader(io.StringIO(texto), dialecto))
    if not filas:
        return ["sin filas"]
    n = len(filas[0])
    problemas = []
    for i, f in enumerate(filas[1:], 2):
        if not f:
            continue
        if len(f) != n:
            problemas.append("fila %d: %d columnas (la cabecera tiene %d)" % (i, len(f), n))
            if len(problemas) >= 10:
                problemas.append("... (mas filas desiguales)")
                break
    return problemas


def _validar_md(p: Path) -> list:
    texto = _leer(p)
    problemas = []
    if len(re.findall(r"^\s*```", texto, re.M)) % 2:
        problemas.append("bloque ``` sin cerrar")
    for m in re.finditer(r"!?\[[^\]]*\]\(([^)\s]+)[^)]*\)", texto):
        dest = m.group(1).strip()
        if dest.startswith(("http:", "https:", "#", "mailto:", "data:")):
            continue
        if not (p.parent / dest.split("#")[0]).exists():
            problemas.append("linea %d: enlace local roto: %s"
                             % (texto.count("\n", 0, m.start()) + 1, dest))
    return problemas


def _validar_py(p: Path) -> list:
    src = _leer(p)
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        return ["linea %s: SyntaxError: %s" % (exc.lineno, exc.msg)]
    try:
        from pyflakes import api as _pf_api
        from pyflakes import reporter as _pf_rep
    except Exception:
        return []
    out, err = io.StringIO(), io.StringIO()
    _pf_api.check(src, str(p), _pf_rep.Reporter(out, err))
    avisos = [l.split(":", 1)[1].strip() if ":" in l else l for l in out.getvalue().splitlines() if l.strip()]
    return ["pyflakes: " + a for a in avisos[:20]]


def _validar_ini(p: Path) -> list:
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read_string(_leer(p))
        return []
    except configparser.Error as exc:
        return [str(exc)[:200]]


def _partir_sql(texto: str) -> list:
    sin = re.sub(r"--[^\n]*", "", texto)
    sin = re.sub(r"/\*.*?\*/", "", sin, flags=re.S)
    return [s.strip() for s in sin.split(";") if s.strip()]


def _validar_sql(p: Path) -> list:
    import sqlite3   # DB temporal de prueba en memoria: no es la DB de Cognia, db_pool no aplica
    problemas = []
    con = sqlite3.connect(":memory:")
    try:
        for i, s in enumerate(_partir_sql(_leer(p)), 1):
            try:
                if re.match(r"^\s*(create|drop|alter)\b", s, re.I):
                    con.execute(s)      # el EXPLAIN de un CREATE no crea: hay que ejecutarlo para las siguientes
                else:
                    con.execute("EXPLAIN " + s)
            except sqlite3.Error as exc:
                problemas.append("sentencia %d: %s -- %s" % (i, exc, s[:80].replace("\n", " ")))
    finally:
        con.close()
    return problemas


def _validar_script(p: Path) -> list:
    raw = p.read_bytes()[:4]
    problemas = []
    if raw.startswith(b"\xef\xbb\xbf") and p.suffix.lower() in (".sh", ".bat"):
        problemas.append("empieza con BOM UTF-8: bash/cmd lo leen como caracteres basura")
    if p.suffix.lower() == ".sh" and not _leer(p).startswith("#!"):
        problemas.append("sin shebang (#!/bin/bash)")
    return problemas


_VALIDADORES = {
    ".html": _validar_html, ".htm": _validar_html, ".xhtml": _validar_html,
    ".css": _validar_css,
    ".js": _validar_js, ".mjs": _validar_js, ".cjs": _validar_js,
    ".json": _validar_json,
    ".yaml": _validar_yaml, ".yml": _validar_yaml,
    ".toml": _validar_toml,
    ".xml": lambda p: _validar_xml(p, False),
    ".svg": lambda p: _validar_xml(p, True),
    ".csv": _validar_csv,
    ".md": _validar_md, ".markdown": _validar_md,
    ".py": _validar_py, ".pyw": _validar_py,
    ".ini": _validar_ini, ".cfg": _validar_ini,
    ".sql": _validar_sql,
    ".bat": _validar_script, ".cmd": _validar_script, ".ps1": _validar_script, ".sh": _validar_script,
}


def validar(ruta: str) -> dict:
    """{ruta, extension, problemas, meta, soportado}"""
    p = _pc.resolver_ruta(ruta)
    if p.is_dir():
        raise ValueError("%s es un directorio; pasa un fichero" % p)
    ext = p.suffix.lower()
    fn = _VALIDADORES.get(ext)
    meta = _tam_y_lineas(p)
    if fn is None:
        return {"ruta": str(p), "extension": ext, "problemas": [], "meta": meta, "soportado": False}
    return {"ruta": str(p), "extension": ext, "problemas": fn(p), "meta": meta, "soportado": True}


# ===========================================================================
# diff_texto
# ===========================================================================

def diff_texto(a: str, b: str, contexto: int = 3) -> dict:
    pa = _pc.resolver_ruta(a)
    ta = _leer(pa).splitlines()
    try:
        pb = _pc.resolver_ruta(b)
        tb = _leer(pb).splitlines()
        nombre_b = str(pb)
    except ValueError:
        tb = b.replace("\\n", "\n").splitlines()
        nombre_b = "<texto>"
    lineas = list(difflib.unified_diff(ta, tb, fromfile=str(pa), tofile=nombre_b, n=contexto, lineterm=""))
    mas = sum(1 for l in lineas if l.startswith("+") and not l.startswith("+++"))
    menos = sum(1 for l in lineas if l.startswith("-") and not l.startswith("---"))
    return {"a": str(pa), "b": nombre_b, "diff": "\n".join(lineas), "mas": mas, "menos": menos,
            "iguales": not lineas}


# ===========================================================================
# sql_probar
# ===========================================================================

def sql_probar(destino: str, sql: str, esquema: str = "") -> dict:
    # sqlite3 directo a proposito: es una DB temporal de prueba (:memory: o
    # una COPIA del .db del usuario), no la DB de Cognia; storage/db_pool
    # gestiona conexiones a la DB real y no tiene sentido aqui.
    import sqlite3
    tmp = None
    if destino.strip().lower() in (":memoria:", ":memory:", "", "memoria"):
        ruta = ":memory:"
    else:
        origen = _pc.resolver_ruta(destino)
        tmp = tempfile.NamedTemporaryFile(prefix="cognia_sqlprueba_", suffix=".db", delete=False)
        tmp.close()
        shutil.copyfile(str(origen), tmp.name)
        ruta = tmp.name
    resultados = []
    con = sqlite3.connect(ruta)
    try:
        if esquema:
            pe = _pc.resolver_ruta(esquema)
            try:
                con.executescript(_leer(pe))
                resultados.append({"sql": "<esquema %s>" % pe.name, "ok": True, "detalle": "aplicado"})
            except sqlite3.Error as exc:
                resultados.append({"sql": "<esquema %s>" % pe.name, "ok": False, "detalle": str(exc)})
        for s in _partir_sql(sql):
            try:
                cur = con.execute(s)
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    filas = cur.fetchmany(31)
                    resultados.append({"sql": s, "ok": True, "columnas": cols, "filas": filas[:30],
                                       "mas": len(filas) > 30})
                else:
                    resultados.append({"sql": s, "ok": True, "afectadas": cur.rowcount})
            except sqlite3.Error as exc:
                resultados.append({"sql": s, "ok": False, "detalle": str(exc)})
        con.commit()
    finally:
        con.close()
        if tmp:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    return {"destino": ruta if ruta == ":memory:" else "copia temporal de %s" % destino,
            "resultados": resultados}


def _texto_sql(r: dict) -> str:
    partes = []
    for x in r["resultados"]:
        s = x["sql"].replace("\n", " ")[:90]
        if not x["ok"]:
            partes.append("ERROR en `%s`: %s" % (s, x["detalle"]))
        elif "filas" in x:
            cab = " | ".join(x["columnas"])
            cuerpo = "\n".join("  " + " | ".join(str(c) for c in f) for f in x["filas"])
            partes.append("`%s` -> %d fila(s)%s\n  %s\n%s" % (s, len(x["filas"]),
                                                              " (hay mas)" if x.get("mas") else "",
                                                              cab, cuerpo))
        elif "afectadas" in x:
            partes.append("`%s` -> OK (%s fila(s) afectada(s))" % (s, x["afectadas"] if x["afectadas"] >= 0 else "?"))
        else:
            partes.append("`%s` -> %s" % (s, x.get("detalle", "OK")))
    errores = sum(1 for x in r["resultados"] if not x["ok"])
    cab = "%s · %d sentencia(s), %d error(es)" % (r["destino"], len(r["resultados"]), errores)
    return cab + "\n" + "\n".join(partes)


# ===========================================================================
# PDF / DOCX / XLSX
# ===========================================================================

def _rango_paginas(spec: str, n: int) -> list:
    spec = (spec or "").strip()
    if not spec:
        return list(range(min(n, 3)))
    out = []
    for trozo in spec.split(","):
        trozo = trozo.strip()
        if "-" in trozo:
            a, b = trozo.split("-", 1)
            a = _pc.entero(a, 1, 1, n)
            b = _pc.entero(b, n, a, n)
            out.extend(range(a - 1, b))
        elif trozo:
            out.append(_pc.entero(trozo, 1, 1, n) - 1)
    return sorted(set(i for i in out if 0 <= i < n))


def pdf_inspeccionar(ruta: str, paginas: str = "") -> dict:
    fitz = _pc.importar("pymupdf")
    p = _pc.resolver_ruta(ruta)
    doc = fitz.open(str(p))
    try:
        n = doc.page_count
        blancas, imagenes, textos = [], 0, []
        for i in range(n):
            pg = doc[i]
            t = pg.get_text().strip()
            imgs = len(pg.get_images())
            imagenes += imgs
            if not t and not imgs:
                blancas.append(i + 1)
        for i in _rango_paginas(paginas, n):
            textos.append((i + 1, doc[i].get_text().strip()))
        r0 = doc[0].rect if n else None
        return {"ruta": str(p), "paginas": n, "tamano": (round(r0.width), round(r0.height)) if r0 else None,
                "metadatos": {k: v for k, v in (doc.metadata or {}).items() if v},
                "imagenes": imagenes, "blancas": blancas, "textos": textos}
    finally:
        doc.close()


def pdf_ver(ruta: str, pagina: int = 1, salida=None, zoom: float = 1.5, ctx=None) -> dict:
    fitz = _pc.importar("pymupdf")
    p = _pc.resolver_ruta(ruta)
    doc = fitz.open(str(p))
    try:
        n = doc.page_count
        i = max(1, min(n, int(pagina))) - 1
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        png = _pc.ruta_salida(ctx, "%s_p%d" % (p.stem, i + 1), ".png", salida or "")
        pix.save(str(png))
    finally:
        doc.close()
    return {"png": str(png), "pagina": i + 1, "paginas": n,
            "resumen": _pc.texto_resumen_imagen(_pc.resumen_imagen(png))}


def docx_texto(ruta: str) -> dict:
    docx = _pc.importar("docx")
    p = _pc.resolver_ruta(ruta)
    d = docx.Document(str(p))
    lineas = []
    for par in d.paragraphs:
        t = par.text.strip()
        if not t:
            continue
        estilo = (par.style.name if par.style is not None else "") or ""
        if estilo.lower().startswith("heading") or estilo.lower().startswith("title"):
            lineas.append("# [%s] %s" % (estilo, t))
        else:
            lineas.append(t)
    tablas = []
    for ti, tabla in enumerate(d.tables, 1):
        filas = []
        for fila in tabla.rows[:20]:
            filas.append(" | ".join(c.text.strip().replace("\n", " ") for c in fila.cells))
        tablas.append("tabla %d (%d filas x %d cols):\n  " % (ti, len(tabla.rows), len(tabla.columns))
                      + "\n  ".join(filas))
    imagenes = sum(1 for rel in d.part.rels.values() if "image" in rel.reltype)
    return {"ruta": str(p), "parrafos": len(lineas), "texto": "\n".join(lineas),
            "tablas": tablas, "imagenes": imagenes}


def xlsx_leer(ruta: str, hoja: str = "", filas: int = 20) -> dict:
    openpyxl = _pc.importar("openpyxl")
    p = _pc.resolver_ruta(ruta)
    wb_f = openpyxl.load_workbook(str(p), data_only=False)      # formulas
    wb_v = openpyxl.load_workbook(str(p), data_only=True)       # valores cacheados
    nombres = wb_f.sheetnames
    if hoja and hoja not in nombres:
        raise ValueError("no existe la hoja '%s'; hojas: %s" % (hoja, ", ".join(nombres)))
    activa = hoja or nombres[0]
    wf, wv = wb_f[activa], wb_v[activa]
    tabla, errores, sin_valor = [], [], []
    for i, (ff, fv) in enumerate(zip(wf.iter_rows(), wv.iter_rows()), 1):
        celdas = []
        for cf, cv in zip(ff, fv):
            val = cv.value
            if isinstance(val, str) and val.startswith("#"):
                errores.append("%s: %s" % (cf.coordinate, val))
            if isinstance(cf.value, str) and cf.value.startswith("=") and val is None:
                sin_valor.append("%s: %s" % (cf.coordinate, cf.value[:40]))
            celdas.append("" if val is None else str(val))
        if i <= filas:
            tabla.append(" | ".join(celdas))
    return {"ruta": str(p), "hojas": nombres, "hoja": activa,
            "dimensiones": "%d filas x %d cols" % (wf.max_row, wf.max_column),
            "tabla": tabla, "errores": errores[:20], "sin_valor": sin_valor[:20]}


# ===========================================================================
# 3D
# ===========================================================================

def _mallas(ruta: str) -> tuple:
    trimesh = _pc.importar("trimesh")
    p = _pc.resolver_ruta(ruta)
    obj = trimesh.load(str(p), force=None)
    if isinstance(obj, trimesh.Scene):
        mallas = [(n, g) for n, g in obj.geometry.items() if isinstance(g, trimesh.Trimesh)]
    else:
        mallas = [(p.stem, obj)]
    return p, obj, mallas


def modelo3d_inspeccionar(ruta: str) -> dict:
    p, obj, mallas = _mallas(ruta)
    if not mallas:
        raise ValueError("%s no contiene ninguna malla" % p.name)
    partes = []
    for nombre, m in mallas:
        vis = getattr(m, "visual", None)
        tex = 0
        try:
            tex = 1 if (vis is not None and getattr(vis, "kind", "") == "texture") else 0
        except Exception:
            tex = 0
        partes.append({"nombre": nombre, "vertices": int(len(m.vertices)), "caras": int(len(m.faces)),
                       "watertight": bool(m.is_watertight),
                       "volumen": float(m.volume) if m.is_watertight else None,
                       "area": float(m.area), "bounds": m.bounds.tolist(), "textura": tex})
    import numpy as np
    b = np.array([q["bounds"] for q in partes])
    bounds = [b[:, 0, :].min(axis=0).round(3).tolist(), b[:, 1, :].max(axis=0).round(3).tolist()]
    return {"ruta": str(p), "mallas": partes, "bounds": bounds, "escena": len(mallas) > 1}


def modelo3d_ver(ruta: str, salida=None, vista: str = "iso", ctx=None) -> dict:
    p, obj, mallas = _mallas(ruta)
    if not mallas:
        raise ValueError("%s no contiene ninguna malla" % p.name)
    mpl = _pc.importar("matplotlib")
    mpl.use("Agg")
    plt = _pc.importar("matplotlib.pyplot")
    _pc.importar("mpl_toolkits.mplot3d")
    vistas = {"iso": (30, 45), "frente": (0, 0), "arriba": (90, 0), "lado": (0, 90)}
    elegidas = list(vistas.items()) if vista in ("", "todas", "3") else [(vista, vistas.get(vista, vistas["iso"]))]
    fig = plt.figure(figsize=(4.2 * len(elegidas), 4.2))
    for k, (nombre, (elev, azim)) in enumerate(elegidas, 1):
        ax = fig.add_subplot(1, len(elegidas), k, projection="3d")
        for _, m in mallas:
            v, f = m.vertices, m.faces
            if len(f) > 60000:
                f = f[:: max(1, len(f) // 60000)]
            ax.plot_trisurf(v[:, 0], v[:, 1], v[:, 2], triangles=f, color="#8aa7ff",
                            edgecolor="#223" if len(f) < 4000 else "none", linewidth=0.2)
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(nombre)
        ax.set_axis_off()
    png = _pc.ruta_salida(ctx, "%s_%s" % (p.stem, vista or "vistas"), ".png", salida or "")
    fig.savefig(str(png), dpi=110, bbox_inches="tight")
    plt.close(fig)
    return {"png": str(png), "vistas": [n for n, _ in elegidas],
            "resumen": _pc.texto_resumen_imagen(_pc.resumen_imagen(png))}


# ===========================================================================
# Python: lint / importar / perfilar / cobertura
# ===========================================================================

def py_lint(ruta: str) -> dict:
    p = _pc.resolver_ruta(ruta)
    ficheros = sorted(p.rglob("*.py")) if p.is_dir() else [p]
    ficheros = [f for f in ficheros if not any(s in f.parts for s in ("venv", "venv312", ".venv", "node_modules", "__pycache__", ".git"))]
    if not ficheros:
        raise ValueError("no hay ficheros .py en %s" % p)
    try:
        from pyflakes import api as _pf_api
        from pyflakes import reporter as _pf_rep
    except Exception:
        raise ValueError("falta pyflakes. Instalalo con: pip install pyflakes")
    por_fichero = {}
    for f in ficheros[:400]:
        out, err = io.StringIO(), io.StringIO()
        try:
            _pf_api.check(_leer(f), str(f), _pf_rep.Reporter(out, err))
        except Exception as exc:
            por_fichero[str(f)] = ["no se pudo analizar: %s" % exc]
            continue
        avisos = [l for l in (out.getvalue() + err.getvalue()).splitlines() if l.strip()]
        if avisos:
            por_fichero[str(f)] = [a.replace(str(f) + ":", "linea ", 1) for a in avisos]
    return {"ficheros": len(ficheros), "avisos": por_fichero}


def py_importar(objetivo: str, cwd: str = "") -> dict:
    obj = objetivo.strip().strip("\"'")
    directorio = cwd or None
    if obj.endswith(".py") or "/" in obj or "\\" in obj:
        p = _pc.resolver_ruta(obj)
        directorio = directorio or str(p.parent)
        modulo = p.stem
    else:
        modulo = obj
    if directorio:
        directorio = str(_pc.resolver_ruta(directorio))
    codigo = ("import importlib, sys, time; sys.path.insert(0, %r); t=time.perf_counter(); "
              "importlib.import_module(%r); print('IMPORT_OK %%.3f' %% (time.perf_counter()-t))"
              % (directorio or os.getcwd(), modulo))
    rc, out, err = _pc.correr([sys.executable, "-c", codigo], timeout=30, cwd=directorio)
    m = re.search(r"IMPORT_OK ([\d.]+)", out)
    return {"modulo": modulo, "ok": rc == 0 and bool(m), "segundos": float(m.group(1)) if m else None,
            "salida": _capar((out.replace(m.group(0), "") if m else out).strip(), 1500),
            "error": _capar(err.strip(), 2500), "rc": rc}


def _partir_comando(comando: str) -> list:
    import shlex
    try:
        partes = shlex.split(comando, posix=(os.name != "nt"))
    except ValueError:
        partes = comando.split()
    # en modo no-posix shlex deja las comillas puestas ("C:\ruta con espacios\x.exe")
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in partes]


def py_perfilar(comando: str, top: int = 15, timeout: int = 120, cwd: str = "") -> dict:
    import pstats
    partes = _partir_comando(comando)
    if not partes:
        raise ValueError("falta el comando (ej: python script.py)")
    if Path(partes[0]).name.lower().startswith("python"):
        partes = partes[1:]
    if not partes:
        raise ValueError("el comando no nombra un script (.py) ni un modulo (-m)")
    prof = tempfile.NamedTemporaryFile(prefix="cognia_perfil_", suffix=".prof", delete=False)
    prof.close()
    cmd = [sys.executable, "-m", "cProfile", "-o", prof.name] + partes
    directorio = str(_pc.resolver_ruta(cwd)) if cwd else None
    t0 = time.perf_counter()
    rc, out, err = _pc.correr(cmd, timeout=timeout, cwd=directorio)
    total = time.perf_counter() - t0
    try:
        if not os.path.exists(prof.name) or os.path.getsize(prof.name) == 0:
            return {"ok": False, "rc": rc, "total": total, "salida": _capar(out, 1000),
                    "error": _capar(err, 2000) or "cProfile no dejo fichero (¿el script revento?)", "top": ""}
        buf = io.StringIO()
        st = pstats.Stats(prof.name, stream=buf)
        st.sort_stats("cumulative").print_stats(top)
        texto = buf.getvalue()
        lineas = [l for l in texto.splitlines() if l.strip()]
        try:
            inicio = next(i for i, l in enumerate(lineas) if l.strip().startswith("ncalls"))
        except StopIteration:
            inicio = 0
        return {"ok": rc == 0, "rc": rc, "total": total, "salida": _capar(out, 800),
                "error": _capar(err, 1500), "top": "\n".join(lineas[inicio:inicio + top + 1])}
    finally:
        try:
            os.unlink(prof.name)
        except OSError:
            pass


def py_cobertura(comando: str, cwd: str = "", timeout: int = 600) -> dict:
    _pc.importar("coverage")
    partes = _partir_comando(comando) or ["-m", "pytest", "-q"]
    if partes and Path(partes[0]).name.lower().startswith("python"):
        partes = partes[1:]
    if partes and partes[0] == "pytest":
        partes = ["-m", "pytest"] + partes[1:]
    if partes and partes[0] != "-m" and not partes[0].endswith(".py"):
        partes = ["-m", "pytest"] + partes
    directorio = str(_pc.resolver_ruta(cwd)) if cwd else os.getcwd()
    datos = os.path.join(tempfile.mkdtemp(prefix="cognia_cov_"), ".coverage")
    env = dict(os.environ, COVERAGE_FILE=datos, PYTHONUTF8="1")
    try:
        r1 = subprocess.run([sys.executable, "-m", "coverage", "run", "--source=."] + partes, cwd=directorio,
                            env=env, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                            errors="replace")
        r2 = subprocess.run([sys.executable, "-m", "coverage", "report", "--sort=cover"], cwd=directorio,
                            env=env, capture_output=True, text=True, timeout=120, encoding="utf-8",
                            errors="replace")
    except subprocess.TimeoutExpired:
        raise ValueError("timeout de %ds corriendo la cobertura" % timeout)
    informe = (r2.stdout or "").strip()
    m = re.search(r"^TOTAL\s+.*?(\d+)%\s*$", informe, re.M)
    lineas = [l for l in informe.splitlines() if re.search(r"\d+%", l) and not l.startswith("TOTAL")]
    return {"rc_tests": r1.returncode, "total": int(m.group(1)) if m else None,
            "peores": lineas[:12], "tests": _capar((r1.stdout or "").strip()[-1200:], 1200),
            "error": _capar((r1.stderr or r2.stderr or "").strip(), 1200)}


# ===========================================================================
# Red y ficheros
# ===========================================================================

def http_solicitud(metodo: str, url: str, cuerpo: str = "", cabeceras: str = "", timeout: int = 20) -> dict:
    requests = _pc.importar("requests")
    m = (metodo or "GET").upper()
    heads = {}
    for par in (cabeceras or "").split(";"):
        if ":" in par:
            k, v = par.split(":", 1)
            heads[k.strip()] = v.strip()
    datos = None
    js = None
    if cuerpo:
        try:
            js = json.loads(cuerpo)
        except ValueError:
            datos = cuerpo
    t0 = time.perf_counter()
    try:
        r = requests.request(m, url, headers=heads or None, data=datos, json=js, timeout=timeout,
                             allow_redirects=True)
    except requests.exceptions.ConnectionError as exc:
        raise ValueError("no se pudo conectar a %s (%s). Si es tu servidor local: arrancalo con "
                         "ejecutar_fondo, espera unos segundos (puerto_esperar) y vuelve a probar."
                         % (url, str(exc)[:120]))
    except requests.exceptions.Timeout:
        raise ValueError("timeout de %ds contra %s" % (timeout, url))
    ms = int((time.perf_counter() - t0) * 1000)
    ct = r.headers.get("content-type", "")
    texto = r.text or ""
    if "json" in ct:
        try:
            texto = json.dumps(r.json(), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    return {"metodo": m, "url": r.url, "status": r.status_code, "ms": ms, "content_type": ct,
            "bytes": len(r.content), "cuerpo": _capar(texto, 2500),
            "redirigido": bool(r.history)}


def puerto_esperar(destino: str, timeout: int = 30) -> dict:
    d = destino.strip()
    url = ""
    if re.match(r"^https?://", d, re.I):
        from urllib.parse import urlparse
        u = urlparse(d)
        url = d
        host = u.hostname or "127.0.0.1"
        puerto = u.port or (443 if u.scheme == "https" else 80)
    elif ":" in d:
        host, puerto = d.rsplit(":", 1)
        puerto = int(puerto)
    else:
        host, puerto = "127.0.0.1", int(d)
    t0 = time.perf_counter()
    abierto = False
    while time.perf_counter() - t0 < timeout:
        try:
            with socket.create_connection((host, puerto), timeout=1.0):
                abierto = True
                break
        except OSError:
            time.sleep(0.25)
    seg = round(time.perf_counter() - t0, 2)
    out = {"host": host, "puerto": puerto, "abierto": abierto, "segundos": seg, "status": None}
    if abierto and (url or puerto in (80, 443, 8000, 8080, 3000, 5000, 5173, 8888)):
        try:
            requests = _pc.importar("requests")
            r = requests.get(url or "http://%s:%d/" % (host, puerto), timeout=5)
            out["status"] = r.status_code
        except Exception as exc:
            out["status"] = "sin respuesta HTTP (%s)" % type(exc).__name__
    return out


def esperar_fichero(ruta: str, timeout: int = 30, estable_ms: int = 500) -> dict:
    p = _pc.resolver_ruta(ruta, debe_existir=False)
    t0 = time.perf_counter()
    ultimo_tam, desde = -1, None
    while time.perf_counter() - t0 < timeout:
        if p.exists():
            try:
                tam = p.stat().st_size
            except OSError:
                tam = -1
            if tam == ultimo_tam and tam >= 0:
                if desde is not None and (time.perf_counter() - desde) * 1000 >= estable_ms:
                    return {"ruta": str(p), "existe": True, "estable": True, "bytes": tam,
                            "segundos": round(time.perf_counter() - t0, 2)}
            else:
                ultimo_tam, desde = tam, time.perf_counter()
        time.sleep(0.1)
    return {"ruta": str(p), "existe": p.exists(), "estable": False,
            "bytes": (p.stat().st_size if p.exists() else 0), "segundos": round(time.perf_counter() - t0, 2)}


# ===========================================================================
# consola_sesion: proceso interactivo persistente
# ===========================================================================

MAX_SESIONES = 4
_SESIONES: dict = {}
_contador = [0]


def _lector(pipe, q: "queue.Queue"):
    """Por TROZOS, no por lineas: un prompt de input() no lleva salto (mismo
    motivo que ejecucion_guionada._lector)."""
    fd = pipe.fileno()
    try:
        while True:
            trozo = os.read(fd, 4096)
            if not trozo:
                break
            q.put(trozo)
    except Exception:
        pass
    finally:
        q.put(None)


def _drenar(q: "queue.Queue", pausa_ms: int, espera_max_ms: int) -> tuple:
    trozos: list = []
    eof = False
    t_ini = time.perf_counter()
    ultimo = t_ini
    while True:
        try:
            item = q.get(timeout=0.05)
        except queue.Empty:
            ahora = time.perf_counter()
            if (ahora - ultimo) * 1000 >= pausa_ms and (trozos or (ahora - t_ini) * 1000 >= pausa_ms):
                break
            if (ahora - t_ini) * 1000 >= espera_max_ms:
                break
            continue
        if item is None:
            eof = True
            break
        trozos.append(item.decode("utf-8", errors="replace"))
        ultimo = time.perf_counter()
    return "".join(trozos), eof


def _matar(proc) -> None:
    """Por arbol: matar el shell NO mata el proceso (leccion del repo)."""
    if proc.poll() is not None:
        return
    try:
        from cognia.harness.timeout_tool import _matar_arbol
        _matar_arbol(proc)
        return
    except Exception:
        pass
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        proc.kill()


def sesion_abrir(comando: str, cwd: str = "") -> dict:
    vivas = [k for k, s in _SESIONES.items() if s["proc"].poll() is None]
    if len(vivas) >= MAX_SESIONES:
        raise ValueError("ya hay %d sesiones abiertas (%s); cierra alguna con `consola_sesion cerrar <id>`"
                         % (len(vivas), ", ".join(vivas)))
    directorio = str(_pc.resolver_ruta(cwd)) if cwd else None
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    kw = {}
    if os.name != "nt":
        kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(comando, shell=True, cwd=directorio, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    except Exception as exc:
        raise ValueError("no se pudo lanzar: %s: %s" % (type(exc).__name__, exc))
    _contador[0] += 1
    sid = "s%d" % _contador[0]
    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=_lector, args=(proc.stdout, q), daemon=True).start()
    _SESIONES[sid] = {"proc": proc, "q": q, "comando": comando, "t0": time.time(), "eof": False}
    salida, eof = _drenar(q, 400, 4000)
    _SESIONES[sid]["eof"] = eof
    return {"id": sid, "pid": proc.pid, "salida": salida, "vivo": proc.poll() is None}


def _sesion(sid: str) -> dict:
    s = _SESIONES.get(sid.strip())
    if s is None:
        raise ValueError("no existe la sesion '%s'; abiertas: %s" % (sid, ", ".join(_SESIONES) or "ninguna"))
    return s


def sesion_enviar(sid: str, texto: str, espera_ms: int = 4000) -> dict:
    s = _sesion(sid)
    proc = s["proc"]
    if proc.poll() is not None:
        return {"id": sid, "salida": "", "vivo": False, "rc": proc.returncode,
                "nota": "el programa ya habia terminado (rc %s)" % proc.returncode}
    try:
        proc.stdin.write((texto + "\n").encode("utf-8"))
        proc.stdin.flush()
    except Exception as exc:
        raise ValueError("stdin cerrado (%s)" % type(exc).__name__)
    salida, eof = _drenar(s["q"], 400, espera_ms)
    s["eof"] = s["eof"] or eof
    return {"id": sid, "salida": salida, "vivo": proc.poll() is None, "rc": proc.returncode}


def sesion_leer(sid: str, espera_ms: int = 1000) -> dict:
    s = _sesion(sid)
    salida, eof = _drenar(s["q"], 200, espera_ms)
    s["eof"] = s["eof"] or eof
    return {"id": sid, "salida": salida, "vivo": s["proc"].poll() is None, "rc": s["proc"].returncode}


def sesion_cerrar(sid: str) -> dict:
    s = _sesion(sid)
    proc = s["proc"]
    rc = proc.poll()
    try:
        proc.stdin.close()
    except Exception:
        pass
    if rc is None:
        try:
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            _matar(proc)
    cola, _ = _drenar(s["q"], 100, 400)
    del _SESIONES[sid]
    return {"id": sid, "rc": proc.poll(), "salida": cola}


def sesion_lista() -> list:
    return [{"id": k, "comando": s["comando"], "vivo": s["proc"].poll() is None, "pid": s["proc"].pid,
             "segundos": int(time.time() - s["t0"])} for k, s in _SESIONES.items()]


def _cerrar_todas() -> None:
    for sid in list(_SESIONES):
        try:
            sesion_cerrar(sid)
        except Exception:
            pass


atexit.register(_cerrar_todas)


# ===========================================================================
# tui_probar: pseudo-terminal + pantalla emulada
# ===========================================================================

_TECLAS_ANSI = {
    "arriba": "\x1b[A", "abajo": "\x1b[B", "derecha": "\x1b[C", "izquierda": "\x1b[D",
    "up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D",
    "intro": "\r", "enter": "\r", "tab": "\t", "esc": "\x1b", "escape": "\x1b",
    "espacio": " ", "space": " ", "backspace": "\x7f", "inicio": "\x1b[H", "fin": "\x1b[F",
    "home": "\x1b[H", "end": "\x1b[F", "repag": "\x1b[5~", "avpag": "\x1b[6~",
    "supr": "\x1b[3~", "delete": "\x1b[3~", "f1": "\x1bOP", "f2": "\x1bOQ", "f3": "\x1bOR",
    "f4": "\x1bOS", "f5": "\x1b[15~", "f10": "\x1b[21~", "ctrl-c": "\x03", "ctrl-d": "\x04",
}


def _tecla_a_ansi(t: str) -> str:
    t = t.strip()
    if not t:
        return ""
    bajo = t.lower()
    if bajo in _TECLAS_ANSI:
        return _TECLAS_ANSI[bajo]
    if bajo.startswith("ctrl-") and len(bajo) == 6:
        return chr(ord(bajo[5].upper()) - 64)
    return t                        # letras / texto literal


# CSI (ESC[...letra), ESC= / ESC>, y OSC (ESC]...BEL): lo que manda ConPTY
# antes de que el programa pinte nada.
_RE_SOLO_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>]|\x1b\][^\x07]*\x07")


class _PtyWin:
    """winpty (pywinpty) con la misma API minima que el pty POSIX. `read` de
    PtyProcess BLOQUEA (recv de socket), asi que un hilo lee y encola; `leer`
    drena con pausa, como consola_sesion."""

    def __init__(self, argv, cwd, filas, columnas):
        winpty = _pc.importar("winpty")
        try:
            self.p = winpty.PtyProcess.spawn(argv, cwd=cwd or None, dimensions=(filas, columnas),
                                             env=dict(os.environ, PYTHONUTF8="1", TERM="xterm-256color"))
        except Exception as exc:
            raise ValueError("winpty no pudo lanzar el programa: %s: %s" % (type(exc).__name__, str(exc)[:200]))
        self.q: "queue.Queue" = queue.Queue()
        threading.Thread(target=self._bombear, daemon=True).start()

    def _bombear(self):
        try:
            while True:
                t = self.p.read(4096)
                if t:
                    self.q.put(t)
        except EOFError:
            pass
        except Exception:
            pass
        finally:
            self.q.put(None)

    def leer(self, espera_ms: int, silencio_ms: int = 300) -> str:
        """Lee hasta `espera_ms`; en cuanto llega algo, corta tras
        `silencio_ms` sin datos. ConPTY tarda en arrancar (>1 s con el
        lanzador del venv) y la salida llega a trozos: esperar un tiempo fijo
        devolvia la pantalla vacia (cazado en el test)."""
        fin = time.perf_counter() + espera_ms / 1000.0
        trozos = []
        ultimo = None
        while time.perf_counter() < fin:
            try:
                t = self.q.get(timeout=0.05)
            except queue.Empty:
                if ultimo is not None and (time.perf_counter() - ultimo) * 1000 >= silencio_ms:
                    break
                continue
            if t is None:
                break
            trozos.append(t)
            # el preambulo de ConPTY ([1t, [?1004h...) llega antes que
            # el programa: solo cuenta como "primera salida" lo que no sea
            # puro escape, si no el silencio corta antes de que pinte nada
            if _RE_SOLO_ESCAPES.sub("", t).strip():
                ultimo = time.perf_counter()
        return "".join(trozos)

    def escribir(self, s: str) -> None:
        self.p.write(s)

    def vivo(self) -> bool:
        return bool(self.p.isalive())

    def cerrar(self) -> None:
        try:
            if self.p.isalive():
                self.p.terminate(force=True)
        except Exception:
            pass


class _PtyPosix:
    def __init__(self, argv, cwd, filas, columnas):
        import fcntl
        import pty
        import struct
        import termios
        pid, fd = pty.fork()
        if pid == 0:
            if cwd:
                os.chdir(cwd)
            os.environ["TERM"] = "xterm-256color"
            os.execvp(argv[0], argv)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", filas, columnas, 0, 0))

    def leer(self, espera_ms: int, silencio_ms: int = 300) -> str:
        import select
        fin = time.perf_counter() + espera_ms / 1000.0
        trozos = []
        ultimo = None
        while time.perf_counter() < fin:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if not r:
                if ultimo is not None and (time.perf_counter() - ultimo) * 1000 >= silencio_ms:
                    break
                continue
            ultimo = time.perf_counter()
            try:
                t = os.read(self.fd, 4096)
            except OSError:
                break
            if not t:
                break
            trozos.append(t.decode("utf-8", errors="replace"))
        return "".join(trozos)

    def escribir(self, s: str) -> None:
        os.write(self.fd, s.encode("utf-8"))

    def vivo(self) -> bool:
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False

    def cerrar(self) -> None:
        try:
            import signal
            os.kill(self.pid, signal.SIGKILL)
        except Exception:
            pass


def _pantalla_texto(screen) -> str:
    lineas = [l.rstrip() for l in screen.display]
    while lineas and not lineas[-1]:
        lineas.pop()
    return "\n".join(lineas)


def tui_probar(comando: str, teclas: list, columnas: int = 80, filas: int = 24,
               espera_ms: int = 700, timeout: int = 60, cwd: str = "") -> dict:
    pyte = _pc.importar("pyte")
    argv = _partir_comando(comando)
    if not argv:
        raise ValueError("falta el comando")
    directorio = str(_pc.resolver_ruta(cwd)) if cwd else None
    screen = pyte.Screen(columnas, filas)
    stream = pyte.Stream(screen)
    pty_ = (_PtyWin if os.name == "nt" else _PtyPosix)(argv, directorio, filas, columnas)
    pantallas = []
    t0 = time.perf_counter()
    try:
        # arranque: hasta 4 s (o espera_ms si es mayor) pero corta al primer
        # silencio tras la primera salida; cada tecla: hasta 3x espera_ms
        stream.feed(pty_.leer(max(espera_ms, 4000)))
        pantallas.append({"tecla": None, "pantalla": _pantalla_texto(screen)})
        for t in teclas:
            if time.perf_counter() - t0 > timeout:
                pantallas.append({"tecla": t, "pantalla": "", "nota": "timeout de %ds" % timeout})
                break
            if not pty_.vivo():
                pantallas.append({"tecla": t, "pantalla": "", "nota": "el programa ya habia terminado"})
                continue
            pty_.escribir(_tecla_a_ansi(t))
            stream.feed(pty_.leer(espera_ms * 3, silencio_ms=max(150, espera_ms // 2)))
            pantallas.append({"tecla": t, "pantalla": _pantalla_texto(screen)})
        vivo = pty_.vivo()
    finally:
        pty_.cerrar()
    return {"pantallas": pantallas, "vivo": vivo, "segundos": round(time.perf_counter() - t0, 2),
            "tamano": "%dx%d" % (columnas, filas)}


# ===========================================================================
# Registro
# ===========================================================================

def _err(tool: str, exc: BaseException) -> str:
    if isinstance(exc, ValueError):
        return "RESULTADO %s ERROR: %s" % (tool, exc)
    return "RESULTADO %s ERROR: %s: %s" % (tool, type(exc).__name__, str(exc)[:200])


def _p(nombre, tipo="string", requerido=False, descripcion="", clave=True) -> dict:
    return {"nombre": nombre, "tipo": tipo, "requerido": requerido, "descripcion": descripcion, "clave": clave}


def register(tool) -> None:

    # ---- formato_validar ------------------------------------------------
    @tool("formato_validar",
          "formato_validar <ruta>  -- valida por extension (html/css/js/json/yaml/toml/xml/svg/csv/md/py/ini/sql/sh) y lista los problemas con linea",
          desc="Comprueba que un fichero que escribiste esta BIEN FORMADO antes de renderizarlo o "
               "ejecutarlo: HTML (etiquetas sin cerrar, atributos duplicados, src/href locales que no "
               "existen), CSS (llaves, ';' faltantes, url() rotas), JS (node --check), JSON, YAML, TOML, "
               "XML/SVG (ids duplicados, viewBox), CSV (columnas desiguales), Markdown (enlaces rotos, "
               "``` sin cerrar), Python (sintaxis + pyflakes), INI, SQL (EXPLAIN de cada sentencia), "
               "scripts (BOM/shebang). Devuelve OK o cada problema con su linea, mas tamano y lineas.",
          params=[_p("ruta", requerido=True, descripcion="fichero a validar", clave=False)],
          timeout_s=60)
    def _formato_validar(args, ctx):
        ruta, _ = _pc.partir_args(args, [])
        try:
            r = validar(ruta)
        except Exception as exc:
            _anotar("formato_validar", ruta, False, str(exc))
            return _err("formato_validar", exc)
        if not r["soportado"]:
            _anotar("formato_validar", ruta, None, "sin validador")
            return ("RESULTADO formato_validar %s: sin validador para '%s'; existe y pesa %s"
                    % (ruta, r["extension"] or "(sin extension)", r["meta"]))
        if not r["problemas"]:
            _anotar("formato_validar", ruta, True, r["meta"])
            return "RESULTADO formato_validar %s: OK (%s, %s)" % (ruta, r["extension"], r["meta"])
        _anotar("formato_validar", ruta, False, "%d problema(s)" % len(r["problemas"]))
        return ("RESULTADO formato_validar %s: %d problema(s) (%s):\n  - %s"
                % (ruta, len(r["problemas"]), r["meta"], "\n  - ".join(r["problemas"][:40])))

    # ---- diff_texto -----------------------------------------------------
    @tool("diff_texto",
          "diff_texto <a> | <b> [| contexto=N]  -- unified diff entre dos ficheros (o fichero y texto literal)",
          desc="Compara dos ficheros (o un fichero con un texto literal si `b` no es una ruta) y devuelve "
               "el unified diff con +N -M lineas. Usala para verificar que una edicion cambio EXACTAMENTE "
               "lo que querias, o que una salida generada coincide con la esperada.",
          params=[_p("a", requerido=True, descripcion="fichero original", clave=False),
                  _p("b", requerido=True, descripcion="fichero nuevo o texto literal", clave=False),
                  _p("contexto", "integer", descripcion="lineas de contexto (default 3)")],
          timeout_s=30)
    def _diff_texto(args, ctx):
        s, o = _pc.partir_args(args, ["contexto"])
        partes = [x.strip() for x in s.split("|", 1)]
        if len(partes) < 2:
            return "RESULTADO diff_texto ERROR: uso: diff_texto <a> | <b> [| contexto=N]"
        try:
            r = diff_texto(partes[0], partes[1], _pc.entero(o.get("contexto"), 3, 0, 50))
        except Exception as exc:
            return _err("diff_texto", exc)
        _anotar("diff_texto", partes[0], r["iguales"], "+%d -%d" % (r["mas"], r["menos"]))
        if r["iguales"]:
            return "RESULTADO diff_texto: IGUALES (%s vs %s)" % (r["a"], r["b"])
        return "RESULTADO diff_texto: +%d -%d lineas\n%s" % (r["mas"], r["menos"], _capar(r["diff"]))

    # ---- sql_probar -----------------------------------------------------
    @tool("sql_probar",
          "sql_probar <ruta.db|:memoria:> | sql=<sentencias> [| esquema=<ruta.sql>]  -- ejecuta SQL contra una DB en memoria o una COPIA temporal del .db",
          desc="Prueba sentencias SQL (sqlite) sin tocar datos reales: contra :memoria: o contra una COPIA "
               "temporal de un .db. Aplica primero un esquema (.sql) si lo pasas y luego cada sentencia "
               "separada por ';'; devuelve filas (max 30), filas afectadas y el error con la sentencia "
               "culpable. Usala para verificar consultas y esquemas que escribiste.",
          params=[_p("destino", requerido=True, descripcion=":memoria: o ruta de un .db", clave=False),
                  _p("sql", requerido=True, descripcion="sentencias separadas por ;"),
                  _p("esquema", descripcion="fichero .sql con el esquema a aplicar antes")],
          timeout_s=60)
    def _sql_probar(args, ctx):
        destino, o = _pc.partir_args(args, ["sql", "esquema"])
        if not o.get("sql") and not o.get("esquema"):
            return "RESULTADO sql_probar ERROR: falta sql=... (o esquema=...)"
        try:
            r = sql_probar(destino, o.get("sql", ""), o.get("esquema", ""))
        except Exception as exc:
            return _err("sql_probar", exc)
        errores = sum(1 for x in r["resultados"] if not x["ok"])
        _anotar("sql_probar", destino, errores == 0, "%d error(es)" % errores)
        return "RESULTADO sql_probar: " + _capar(_texto_sql(r))

    # ---- pdf ------------------------------------------------------------
    @tool("pdf_inspeccionar",
          "pdf_inspeccionar <ruta> [| paginas=1-3]  -- paginas, tamano, metadatos, texto de las paginas pedidas, imagenes y paginas en blanco",
          desc="Abre un PDF (pymupdf) y devuelve nº de paginas, tamano, metadatos, cuantas imagenes tiene, "
               "que paginas estan en blanco y el texto de las paginas pedidas (default 1-3). Usala para "
               "comprobar un PDF que generaste (reportlab, LaTeX, conversion) sin abrirlo a mano.",
          params=[_p("ruta", requerido=True, descripcion="fichero .pdf", clave=False),
                  _p("paginas", descripcion="rango: 1-3, 2, 1,4")],
          timeout_s=60)
    def _pdf_inspeccionar(args, ctx):
        ruta, o = _pc.partir_args(args, ["paginas"])
        try:
            r = pdf_inspeccionar(ruta, o.get("paginas", ""))
        except Exception as exc:
            return _err("pdf_inspeccionar", exc)
        _anotar("pdf_inspeccionar", ruta, True, "%d paginas" % r["paginas"])
        partes = ["%d pagina(s)" % r["paginas"]]
        if r["tamano"]:
            partes.append("%dx%d pt" % r["tamano"])
        partes.append("%d imagen(es)" % r["imagenes"])
        if r["blancas"]:
            partes.append("EN BLANCO: paginas %s" % ", ".join(map(str, r["blancas"][:20])))
        if r["metadatos"]:
            partes.append("metadatos: " + ", ".join("%s=%s" % (k, str(v)[:40]) for k, v in list(r["metadatos"].items())[:5]))
        textos = "\n".join("--- pagina %d ---\n%s" % (n, t or "(sin texto)") for n, t in r["textos"])
        return "RESULTADO pdf_inspeccionar %s: %s\n%s" % (ruta, " · ".join(partes), _capar(textos))

    @tool("pdf_ver",
          "pdf_ver <ruta> [| pagina=1] [| salida=X.png] [| zoom=1.5]  -- renderiza una pagina del PDF a PNG",
          desc="Convierte una pagina de un PDF en una imagen PNG (pymupdf) y devuelve la ruta y un resumen "
               "visual (tamano, colores, si esta en blanco). Combinala con captura_inspeccionar/vlm_mirar "
               "para ver como quedo maquetado.",
          params=[_p("ruta", requerido=True, descripcion="fichero .pdf", clave=False),
                  _p("pagina", "integer", descripcion="numero de pagina (default 1)"),
                  _p("salida", descripcion="ruta del PNG (default: scratchpad)"),
                  _p("zoom", "number", descripcion="escala (default 1.5)")],
          timeout_s=60)
    def _pdf_ver(args, ctx):
        ruta, o = _pc.partir_args(args, ["pagina", "salida", "zoom"])
        try:
            zoom = float(o.get("zoom") or 1.5)
        except ValueError:
            zoom = 1.5
        try:
            r = pdf_ver(ruta, _pc.entero(o.get("pagina"), 1, 1), o.get("salida"), zoom, ctx)
        except Exception as exc:
            return _err("pdf_ver", exc)
        _anotar("pdf_ver", ruta, True, r["png"])
        return "RESULTADO pdf_ver %s: pagina %d/%d en %s · %s" % (ruta, r["pagina"], r["paginas"], r["png"], r["resumen"])

    # ---- docx / xlsx ----------------------------------------------------
    @tool("docx_texto",
          "docx_texto <ruta>  -- texto de un .docx con los titulos marcados, tablas e imagenes contadas",
          desc="Lee un documento Word (.docx, python-docx): parrafos con los encabezados marcados como "
               "# [Heading N], las tablas como texto y cuantas imagenes lleva. Usala para verificar un "
               "documento que generaste.",
          params=[_p("ruta", requerido=True, descripcion="fichero .docx", clave=False)],
          timeout_s=60)
    def _docx_texto(args, ctx):
        ruta, _ = _pc.partir_args(args, [])
        try:
            r = docx_texto(ruta)
        except Exception as exc:
            return _err("docx_texto", exc)
        _anotar("docx_texto", ruta, True, "%d parrafos" % r["parrafos"])
        cuerpo = r["texto"] + ("\n" + "\n".join(r["tablas"]) if r["tablas"] else "")
        return ("RESULTADO docx_texto %s: %d parrafo(s), %d tabla(s), %d imagen(es)\n%s"
                % (ruta, r["parrafos"], len(r["tablas"]), r["imagenes"], _capar(cuerpo)))

    @tool("xlsx_leer",
          "xlsx_leer <ruta> [| hoja=Nombre] [| filas=20]  -- hojas, dimensiones, primeras filas, celdas con error y formulas sin valor",
          desc="Lee una hoja de calculo (.xlsx, openpyxl): lista de hojas, dimensiones, las primeras N filas "
               "como tabla, las celdas con error (#REF!, #DIV/0!) y las formulas que no tienen valor "
               "calculado (el fichero lo escribio un programa y nadie lo abrio en Excel). Usala para "
               "verificar un xlsx que generaste.",
          params=[_p("ruta", requerido=True, descripcion="fichero .xlsx", clave=False),
                  _p("hoja", descripcion="nombre de la hoja (default la primera)"),
                  _p("filas", "integer", descripcion="filas a mostrar (default 20)")],
          timeout_s=60)
    def _xlsx_leer(args, ctx):
        ruta, o = _pc.partir_args(args, ["hoja", "filas"])
        try:
            r = xlsx_leer(ruta, o.get("hoja", ""), _pc.entero(o.get("filas"), 20, 1, 500))
        except Exception as exc:
            return _err("xlsx_leer", exc)
        _anotar("xlsx_leer", ruta, not r["errores"], r["dimensiones"])
        partes = ["hojas: %s" % ", ".join(r["hojas"]), "hoja '%s' %s" % (r["hoja"], r["dimensiones"])]
        if r["errores"]:
            partes.append("CELDAS CON ERROR: " + ", ".join(r["errores"]))
        if r["sin_valor"]:
            partes.append("formulas sin valor cacheado (no se calculan hasta abrir en Excel/LibreOffice): "
                          + ", ".join(r["sin_valor"]))
        return "RESULTADO xlsx_leer %s: %s\n%s" % (ruta, " · ".join(partes), _capar("\n".join(r["tabla"])))

    # ---- 3D -------------------------------------------------------------
    @tool("modelo3d_inspeccionar",
          "modelo3d_inspeccionar <ruta>  -- vertices, caras, watertight, volumen/area, bounds y texturas de un obj/stl/glb/gltf/ply",
          desc="Analiza un modelo 3D (trimesh): por cada malla vertices, caras, si es cerrada (watertight), "
               "volumen y area, caja envolvente y si lleva textura; y si es una escena con varias mallas. "
               "Usala para verificar un modelo que generaste o exportaste (¿esta vacio? ¿escala absurda? "
               "¿agujeros?).",
          params=[_p("ruta", requerido=True, descripcion="fichero obj/stl/glb/gltf/ply/off", clave=False)],
          timeout_s=120)
    def _modelo3d_inspeccionar(args, ctx):
        ruta, _ = _pc.partir_args(args, [])
        try:
            r = modelo3d_inspeccionar(ruta)
        except Exception as exc:
            return _err("modelo3d_inspeccionar", exc)
        _anotar("modelo3d_inspeccionar", ruta, True, "%d malla(s)" % len(r["mallas"]))
        lineas = []
        for m in r["mallas"]:
            lineas.append("  - %s: %d vertices, %d caras, %s, area %.3f%s%s"
                          % (m["nombre"], m["vertices"], m["caras"],
                             "cerrada (watertight)" if m["watertight"] else "ABIERTA (agujeros)",
                             m["area"], (", volumen %.3f" % m["volumen"]) if m["volumen"] is not None else "",
                             ", con textura" if m["textura"] else ""))
        return ("RESULTADO modelo3d_inspeccionar %s: %d malla(s)%s · bounds min %s max %s\n%s"
                % (ruta, len(r["mallas"]), " (escena)" if r["escena"] else "", r["bounds"][0], r["bounds"][1],
                   "\n".join(lineas)))

    @tool("modelo3d_ver",
          "modelo3d_ver <ruta> [| salida=X.png] [| vista=iso|frente|arriba|lado|todas]  -- render sin GPU del modelo 3D a PNG",
          desc="Dibuja un modelo 3D (trimesh + matplotlib, sin GPU) en una o varias vistas y devuelve el PNG "
               "con un resumen visual. Usala para VER la forma de un modelo que generaste; combinala con "
               "vlm_mirar si quieres juzgarlo.",
          params=[_p("ruta", requerido=True, descripcion="fichero 3D", clave=False),
                  _p("salida", descripcion="ruta del PNG (default: scratchpad)"),
                  _p("vista", descripcion="iso (default) | frente | arriba | lado | todas")],
          timeout_s=180)
    def _modelo3d_ver(args, ctx):
        ruta, o = _pc.partir_args(args, ["salida", "vista"])
        try:
            r = modelo3d_ver(ruta, o.get("salida"), (o.get("vista") or "iso").lower(), ctx)
        except Exception as exc:
            return _err("modelo3d_ver", exc)
        _anotar("modelo3d_ver", ruta, True, r["png"])
        return "RESULTADO modelo3d_ver %s: vistas %s en %s · %s" % (ruta, "/".join(r["vistas"]), r["png"], r["resumen"])

    # ---- python ---------------------------------------------------------
    @tool("py_lint",
          "py_lint <ruta o directorio>  -- pyflakes: nombres sin definir, imports sin usar, etc., agrupado por fichero",
          desc="Pasa pyflakes por un fichero o un directorio de Python y agrupa los avisos por fichero "
               "(nombres sin definir, imports sin usar, variables asignadas y no usadas, sintaxis). Mas "
               "barato que ejecutar: caza el NameError antes de correr.",
          params=[_p("ruta", requerido=True, descripcion="fichero .py o directorio", clave=False)],
          timeout_s=120)
    def _py_lint(args, ctx):
        ruta, _ = _pc.partir_args(args, [])
        try:
            r = py_lint(ruta)
        except Exception as exc:
            return _err("py_lint", exc)
        n = sum(len(v) for v in r["avisos"].values())
        _anotar("py_lint", ruta, n == 0, "%d aviso(s)" % n)
        if not r["avisos"]:
            return "RESULTADO py_lint %s: sin avisos (%d fichero(s))" % (ruta, r["ficheros"])
        cuerpo = "\n".join("%s:\n  - %s" % (f, "\n  - ".join(a)) for f, a in r["avisos"].items())
        return "RESULTADO py_lint %s: %d aviso(s) en %d de %d fichero(s)\n%s" % (
            ruta, n, len(r["avisos"]), r["ficheros"], _capar(cuerpo))

    @tool("py_importar",
          "py_importar <modulo o ruta.py> [| cwd=RUTA]  -- importa el modulo en un subproceso limpio y devuelve OK o el traceback",
          desc="Importa un modulo Python en un subproceso limpio (mismo interprete, timeout 30 s) y devuelve "
               "OK con los segundos que tardo o el traceback. Caza ImportError, SyntaxError, imports "
               "circulares y efectos secundarios (codigo que se ejecuta al importar) sin correr el programa.",
          params=[_p("objetivo", requerido=True, descripcion="nombre de modulo (paquete.mod) o ruta a .py", clave=False),
                  _p("cwd", descripcion="directorio desde el que importar (se anade al sys.path)")],
          timeout_s=45)
    def _py_importar(args, ctx):
        obj, o = _pc.partir_args(args, ["cwd"])
        try:
            r = py_importar(obj, o.get("cwd", ""))
        except Exception as exc:
            return _err("py_importar", exc)
        _anotar("py_importar", obj, r["ok"], "rc %s" % r["rc"])
        if r["ok"]:
            extra = ("\nsalida al importar (efecto secundario): " + r["salida"]) if r["salida"] else ""
            return "RESULTADO py_importar %s: OK en %.3f s%s" % (r["modulo"], r["segundos"], extra)
        return "RESULTADO py_importar %s: FALLO (rc %s)\n%s%s" % (
            r["modulo"], r["rc"], r["error"], ("\nstdout: " + r["salida"]) if r["salida"] else "")

    @tool("py_perfilar",
          "py_perfilar <comando python> [| top=15] [| timeout=N] [| cwd=RUTA]  -- cProfile: las funciones con mas tiempo acumulado",
          desc="Corre un script o modulo Python bajo cProfile en un subproceso y devuelve las funciones con "
               "mas tiempo acumulado y el tiempo total. Usala cuando algo va lento y quieres saber DONDE "
               "antes de optimizar a ciegas.",
          params=[_p("comando", requerido=True, descripcion="python script.py args | -m modulo", clave=False),
                  _p("top", "integer", descripcion="cuantas funciones (default 15)"),
                  _p("timeout", "integer", descripcion="segundos (default 120)"),
                  _p("cwd", descripcion="directorio de trabajo")],
          danger=True, timeout_s=0)
    def _py_perfilar(args, ctx):
        cmd, o = _partir_cmd(args, ["top", "timeout", "cwd"])
        try:
            r = py_perfilar(cmd, _pc.entero(o.get("top"), 15, 1, 100), _pc.entero(o.get("timeout"), 120, 5, 3600),
                            o.get("cwd", ""))
        except Exception as exc:
            return _err("py_perfilar", exc)
        _anotar("py_perfilar", cmd, r["ok"], "%.2f s" % r["total"])
        if not r["top"]:
            return "RESULTADO py_perfilar %s: ERROR (rc %s, %.2f s)\n%s" % (cmd, r["rc"], r["total"], r["error"])
        return "RESULTADO py_perfilar %s: rc %s, %.2f s de pared\n%s%s" % (
            cmd, r["rc"], r["total"], r["top"], ("\nstderr: " + r["error"]) if r["error"] else "")

    @tool("py_cobertura",
          "py_cobertura <comando de tests> [| cwd=RUTA] [| timeout=N]  -- coverage run + report: % total y los ficheros peor cubiertos",
          desc="Corre los tests bajo coverage (coverage run -m pytest ...) y devuelve el porcentaje total y "
               "los ficheros con menos cobertura. Usala para saber que parte de lo que escribiste NO esta "
               "probada por los tests que escribiste.",
          params=[_p("comando", requerido=True, descripcion="ej: pytest tests/ -q | -m pytest tests/test_x.py", clave=False),
                  _p("cwd", descripcion="raiz del proyecto (default cwd)"),
                  _p("timeout", "integer", descripcion="segundos (default 600)")],
          danger=True, timeout_s=0)
    def _py_cobertura(args, ctx):
        cmd, o = _partir_cmd(args, ["cwd", "timeout"])
        try:
            r = py_cobertura(cmd, o.get("cwd", ""), _pc.entero(o.get("timeout"), 600, 10, 3600))
        except Exception as exc:
            return _err("py_cobertura", exc)
        _anotar("py_cobertura", cmd, r["total"] is not None, "%s%%" % r["total"])
        if r["total"] is None:
            return "RESULTADO py_cobertura: no hubo informe (rc tests %s)\n%s\n%s" % (r["rc_tests"], r["tests"], r["error"])
        return ("RESULTADO py_cobertura: %d%% total · tests rc %s\npeor cubiertos:\n  %s\n%s"
                % (r["total"], r["rc_tests"], "\n  ".join(r["peores"]) or "(todo cubierto)", r["tests"][-600:]))

    # ---- red / ficheros -------------------------------------------------
    @tool("http_solicitud",
          "http_solicitud <METODO> <url> [| cuerpo=...] [| cabeceras=k:v;k2:v2] [| timeout=N]  -- peticion HTTP: status, cabeceras, cuerpo y ms",
          desc="Hace una peticion HTTP (GET/POST/PUT/PATCH/DELETE...) con cuerpo (JSON o texto) y cabeceras, "
               "y devuelve status, content-type, tamano, milisegundos y el cuerpo (JSON formateado). Usala "
               "para probar una API que escribiste: arranca el servidor con ejecutar_fondo, espera con "
               "puerto_esperar y dispara las peticiones.",
          params=[_p("metodo", requerido=True, descripcion="GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS", clave=False),
                  _p("url", requerido=True, descripcion="URL completa", clave=False),
                  _p("cuerpo", descripcion="JSON o texto a enviar"),
                  _p("cabeceras", descripcion="k:v;k2:v2"),
                  _p("timeout", "integer", descripcion="segundos (default 20)")],
          danger=True, timeout_s=90)
    def _http_solicitud(args, ctx):
        s, o = _pc.partir_args(args, ["cuerpo", "cabeceras", "timeout"])
        partes = s.split(None, 1)
        if len(partes) == 1 and re.match(r"^https?://", partes[0], re.I):
            metodo, url = "GET", partes[0]
        elif len(partes) == 2:
            metodo, url = partes
        else:
            return "RESULTADO http_solicitud ERROR: uso: http_solicitud <METODO> <url> [| cuerpo=...]"
        try:
            r = http_solicitud(metodo, url.strip(), o.get("cuerpo", ""), o.get("cabeceras", ""),
                               _pc.entero(o.get("timeout"), 20, 1, 300))
        except Exception as exc:
            return _err("http_solicitud", exc)
        _anotar("http_solicitud", url, r["status"] < 400, "%d" % r["status"])
        return ("RESULTADO http_solicitud %s %s: %d en %d ms · %s · %d bytes%s\n%s"
                % (r["metodo"], r["url"], r["status"], r["ms"], r["content_type"] or "sin content-type",
                   r["bytes"], " (redirigido)" if r["redirigido"] else "", r["cuerpo"] or "(cuerpo vacio)"))

    @tool("puerto_esperar",
          "puerto_esperar <puerto|host:puerto|url> [| timeout=N]  -- espera a que un puerto acepte conexiones (y prueba GET / si es HTTP)",
          desc="Sondea un puerto hasta que acepte conexiones o venza el timeout, y devuelve cuanto tardo; si "
               "parece HTTP hace un GET / y devuelve el status. Usala justo despues de arrancar un servidor "
               "con ejecutar_fondo, antes de renderizar o hacer peticiones.",
          params=[_p("destino", requerido=True, descripcion="8000 | localhost:8000 | http://localhost:8000", clave=False),
                  _p("timeout", "integer", descripcion="segundos (default 30)")],
          timeout_s=0)
    def _puerto_esperar(args, ctx):
        d, o = _pc.partir_args(args, ["timeout"])
        if not d:
            return "RESULTADO puerto_esperar ERROR: falta el puerto"
        try:
            r = puerto_esperar(d, _pc.entero(o.get("timeout"), 30, 1, 600))
        except Exception as exc:
            return _err("puerto_esperar", exc)
        _anotar("puerto_esperar", d, r["abierto"], "%s s" % r["segundos"])
        if not r["abierto"]:
            return ("RESULTADO puerto_esperar %s:%d: CERRADO tras %s s. El servidor no arranco o escucha en otro "
                    "puerto: mira su salida con ver_salida." % (r["host"], r["puerto"], r["segundos"]))
        return "RESULTADO puerto_esperar %s:%d: ABIERTO en %s s%s" % (
            r["host"], r["puerto"], r["segundos"], (" · GET / -> %s" % r["status"]) if r["status"] is not None else "")

    @tool("esperar_fichero",
          "esperar_fichero <ruta> [| timeout=N] [| estable=MS]  -- espera a que un fichero exista y deje de crecer",
          desc="Espera a que un fichero exista y su tamano se mantenga estable durante `estable` ms (lo esta "
               "escribiendo un proceso de fondo: un build, una exportacion, un render). Devuelve bytes y "
               "segundos. Usala antes de leer/inspeccionar algo que genera ejecutar_fondo.",
          params=[_p("ruta", requerido=True, descripcion="fichero esperado", clave=False),
                  _p("timeout", "integer", descripcion="segundos (default 30)"),
                  _p("estable", "integer", descripcion="ms sin crecer para darlo por terminado (default 500)")],
          timeout_s=0)
    def _esperar_fichero(args, ctx):
        ruta, o = _pc.partir_args(args, ["timeout", "estable"])
        try:
            r = esperar_fichero(ruta, _pc.entero(o.get("timeout"), 30, 1, 3600), _pc.entero(o.get("estable"), 500, 50, 60000))
        except Exception as exc:
            return _err("esperar_fichero", exc)
        _anotar("esperar_fichero", ruta, r["estable"], "%d bytes" % r["bytes"])
        if r["estable"]:
            return "RESULTADO esperar_fichero %s: listo, %d bytes tras %s s" % (r["ruta"], r["bytes"], r["segundos"])
        if r["existe"]:
            return "RESULTADO esperar_fichero %s: existe pero SIGUE CRECIENDO tras %s s (%d bytes)" % (r["ruta"], r["segundos"], r["bytes"])
        return "RESULTADO esperar_fichero %s: NO aparecio en %s s" % (r["ruta"], r["segundos"])

    # ---- consola_sesion -------------------------------------------------
    @tool("consola_sesion",
          "consola_sesion abrir <comando> [| cwd=RUTA] | enviar <id> <texto> | leer <id> [| espera=MS] | cerrar <id> | lista  -- proceso interactivo que sobrevive entre llamadas",
          desc="Mantiene un programa de consola ABIERTO entre llamadas (a diferencia de ejecutar_guion, que "
               "es de un tiro): `abrir <comando>` lo lanza y devuelve un id (s1) con lo que imprimio; "
               "`enviar <id> <texto>` le teclea una linea y devuelve la respuesta; `leer <id>` trae lo nuevo; "
               "`cerrar <id>` lo mata por arbol; `lista` muestra las abiertas (max 4). Usala para REPLs, "
               "juegos de texto, asistentes y servidores que aceptan comandos por stdin, decidiendo cada "
               "entrada segun la respuesta anterior.",
          params=[_p("accion", requerido=True, descripcion="abrir | enviar | leer | cerrar | lista", clave=False),
                  _p("resto", descripcion="comando (abrir), '<id> <texto>' (enviar), '<id>' (leer/cerrar)", clave=False),
                  _p("cwd", descripcion="directorio de trabajo (abrir)"),
                  _p("espera", "integer", descripcion="ms maximos a esperar salida (leer/enviar, default 1000/4000)")],
          danger=True, timeout_s=60)
    def _consola_sesion(args, ctx):
        s, o = _partir_cmd(args, ["cwd", "espera"])
        partes = s.split(None, 1)
        if not partes:
            return "RESULTADO consola_sesion ERROR: uso: consola_sesion abrir <comando> | enviar <id> <texto> | leer <id> | cerrar <id> | lista"
        accion = partes[0].lower()
        resto = partes[1].strip() if len(partes) > 1 else ""
        try:
            if accion == "abrir":
                if not resto:
                    return "RESULTADO consola_sesion ERROR: falta el comando"
                r = sesion_abrir(resto, o.get("cwd", ""))
                _anotar("consola_sesion", resto, r["vivo"], r["id"])
                return ("RESULTADO consola_sesion abrir: sesion %s (pid %d, %s)\n>>> arranque\n%s"
                        % (r["id"], r["pid"], "viva" if r["vivo"] else "TERMINO ya", _capar(r["salida"]) or "(sin salida aun)"))
            if accion == "enviar":
                sub = resto.split(None, 1)
                if not sub:
                    return "RESULTADO consola_sesion ERROR: uso: enviar <id> <texto>"
                texto = sub[1] if len(sub) > 1 else ""
                r = sesion_enviar(sub[0], texto, _pc.entero(o.get("espera"), 4000, 100, 60000))
                _anotar("consola_sesion", sub[0], r["vivo"], "enviar")
                nota = (" · " + r["nota"]) if r.get("nota") else ""
                return ("RESULTADO consola_sesion enviar %s: %s%s\n>>> entrada: %r\n%s"
                        % (r["id"], "viva" if r["vivo"] else "TERMINO (rc %s)" % r["rc"], nota, texto,
                           _capar(r["salida"]) or "(sin salida en la espera)"))
            if accion == "leer":
                if not resto:
                    return "RESULTADO consola_sesion ERROR: uso: leer <id>"
                r = sesion_leer(resto.split()[0], _pc.entero(o.get("espera"), 1000, 50, 60000))
                return ("RESULTADO consola_sesion leer %s: %s\n%s"
                        % (r["id"], "viva" if r["vivo"] else "TERMINO (rc %s)" % r["rc"], _capar(r["salida"]) or "(nada nuevo)"))
            if accion == "cerrar":
                if not resto:
                    return "RESULTADO consola_sesion ERROR: uso: cerrar <id>"
                r = sesion_cerrar(resto.split()[0])
                return "RESULTADO consola_sesion cerrar %s: cerrada (rc %s)%s" % (
                    r["id"], r["rc"], ("\nsalida final:\n" + _capar(r["salida"])) if r["salida"] else "")
            if accion == "lista":
                l = sesion_lista()
                if not l:
                    return "RESULTADO consola_sesion lista: ninguna sesion abierta"
                return "RESULTADO consola_sesion lista:\n" + "\n".join(
                    "  %s: %s · %s · pid %d · %d s" % (x["id"], x["comando"][:60], "viva" if x["vivo"] else "terminada", x["pid"], x["segundos"]) for x in l)
            return "RESULTADO consola_sesion ERROR: accion '%s' desconocida (abrir|enviar|leer|cerrar|lista)" % accion
        except Exception as exc:
            return _err("consola_sesion", exc)

    # ---- tui_probar -----------------------------------------------------
    @tool("tui_probar",
          "tui_probar <comando> [| teclas=abajo,abajo,intro] [| columnas=80] [| filas=24] [| espera=MS] [| timeout=N]  -- corre un programa de terminal (curses/rich/textual) en una pseudo-tty y devuelve la PANTALLA tras cada tecla",
          desc="Prueba un programa de TERMINAL con interfaz (curses, rich, textual, menus con colores) sin "
               "humano: lo lanza en una pseudo-terminal real (winpty/pty), emula la pantalla (pyte) y "
               "devuelve el texto de la pantalla al arrancar y tras cada tecla (arriba, abajo, izquierda, "
               "derecha, intro, tab, esc, espacio, f1..f10, ctrl-c, letras). Usala cuando ejecutar_guion no "
               "sirve porque el programa pinta la pantalla entera en vez de imprimir lineas.",
          params=[_p("comando", requerido=True, descripcion="programa a correr", clave=False),
                  _p("teclas", descripcion="teclas separadas por coma"),
                  _p("columnas", "integer", descripcion="ancho (default 80)"),
                  _p("filas", "integer", descripcion="alto (default 24)"),
                  _p("espera", "integer", descripcion="ms tras cada tecla (default 700)"),
                  _p("timeout", "integer", descripcion="segundos totales (default 60)"),
                  _p("cwd", descripcion="directorio de trabajo")],
          danger=True, timeout_s=0)
    def _tui_probar(args, ctx):
        cmd, o = _partir_cmd(args, ["teclas", "columnas", "filas", "espera", "timeout", "cwd"])
        if not cmd:
            return "RESULTADO tui_probar ERROR: falta el comando"
        teclas = [t for t in (o.get("teclas") or "").split(",") if t.strip()]
        try:
            r = tui_probar(cmd, teclas, _pc.entero(o.get("columnas"), 80, 20, 300), _pc.entero(o.get("filas"), 24, 5, 100),
                           _pc.entero(o.get("espera"), 700, 50, 20000), _pc.entero(o.get("timeout"), 60, 1, 3600),
                           o.get("cwd", ""))
        except Exception as exc:
            return _err("tui_probar", exc)
        _anotar("tui_probar", cmd, True, "%d pantalla(s)" % len(r["pantallas"]))
        bloques = []
        for p in r["pantallas"]:
            cab = ">>> arranque" if p["tecla"] is None else ">>> tecla %r" % p["tecla"]
            if p.get("nota"):
                cab += " (%s)" % p["nota"]
            bloques.append(cab + "\n" + (p["pantalla"] or "(pantalla vacia)"))
        return "RESULTADO tui_probar %s: %d pantalla(s) de %s, %.1f s, al final %s\n%s" % (
            cmd, len(r["pantallas"]), r["tamano"], r["segundos"], "sigue vivo" if r["vivo"] else "termino",
            _capar("\n".join(bloques), 6000))
