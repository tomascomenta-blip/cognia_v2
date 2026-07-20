"""
Cognia design benchmark (Eje 3 de 06_AGENTE_PLAN.md §4): 25 specs textuales ->
pagina HTML/CSS single-file; score = % de asserts DUROS pasados.

Cada spec pide una pagina concreta con requisitos EXPLICITOS (cada assert
traza a un requisito escrito en el prompt — no se penaliza lo no pedido).
El checker es 100% mecanico: parser DOM propio (html.parser stdlib) + parser
CSS minimo de los bloques <style>. CERO juez LLM (anti-Goodhart estructural,
06_AGENTE_PLAN §4 eje 3). Las specs y sus asserts quedan CONGELADAS al
commitear este archivo, ANTES de construir el agente v1 (regla P7 del plan:
si el agente las ve durante el desarrollo, el bench muere).

Usage:
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_design --check-only
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_design --limit 3 --label smoke
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_design --label baseline_pelado

Backend: el mismo que benchmark_code.py (LlamaBackend via make_backend).
Alcance declarado del checker: selectores compuestos con descendencia
(`tag#id.class[attr=v] tag2.class2`), sin `>`/`+`/`~`; CSS de bloques <style>
(inline style= NO cuenta como regla); "single_file" prohibe <link
rel=stylesheet> y <script src=> pero PERMITE <img src=http...> (una URL de
placeholder de imagen no rompe el caracter single-file del CSS/JS).
"""
import argparse
import datetime
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent

SYSTEM_PROMPT = ("You are an expert web designer and front-end developer. "
                 "Reply with ONLY a complete single-file HTML document. "
                 "No explanations.")

DEFAULT_MAX_TOKENS = 1600
BASE_TEMPERATURE = 0.0

# Requisitos generales: van appendeados a CADA prompt de spec, por eso los
# asserts base (doc_basics, lang, viewport, single_file, no_inline_styles,
# heading_order) son JUSTOS — estan pedidos explicitamente, siempre.
BASE_REQUIREMENTS = (
    "\n\nGeneral requirements (mandatory):\n"
    "- Reply with ONLY one complete HTML document starting with <!DOCTYPE html>.\n"
    "- All CSS inside a single <style> tag in the <head>. No inline style attributes.\n"
    "- No external CSS or JavaScript files.\n"
    '- Include <html lang="en">, a non-empty <title>, and '
    '<meta name="viewport" content="width=device-width, initial-scale=1">.\n'
    "- Exactly one <h1>; do not skip heading levels.\n"
    "- Every <img> must have a descriptive alt attribute.\n")

# Los 6 asserts base que todos los specs comparten (img_alt se agrega solo
# en specs que piden imagenes, para que no pase vacio).
BASE_ASSERTS = [
    {"type": "doc_basics"},
    {"type": "lang_attr"},
    {"type": "meta_viewport"},
    {"type": "single_file"},
    {"type": "no_inline_styles"},
    {"type": "heading_order"},
]


# ── Mini-DOM (html.parser stdlib) ────────────────────────────────────────────

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "source", "track", "wbr"}


class Node:
    """Nodo de elemento: tag, attrs (dict, ultima aparicion gana), hijos."""
    __slots__ = ("tag", "attrs", "children", "parent", "_text")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children = []
        self.parent = parent
        self._text = []

    def text(self):
        """Texto del subtree completo (incluye hijos), espacios colapsados."""
        parts = list(self._text)
        for ch in self.children:
            parts.append(ch.text())
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def own_text(self):
        """Solo el texto directo del nodo (sin hijos)."""
        return re.sub(r"\s+", " ", " ".join(self._text)).strip()

    def walk(self):
        """Itera el subtree en orden de documento (sin incluir self)."""
        for ch in self.children:
            yield ch
            yield from ch.walk()


class _DomBuilder(HTMLParser):
    """Parser tolerante: end tags huerfanos se ignoran, cierres implicitos
    de void tags manejados; suficiente para el HTML que emite un LLM."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs},
                    parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs},
                    parent=self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        # Buscar el tag abierto mas cercano; si no esta, ignorar el cierre.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1]._text.append(data)


def parse_html(text):
    """Devuelve la raiz del mini-DOM (nodo #document)."""
    builder = _DomBuilder()
    try:
        builder.feed(text)
        builder.close()
    except Exception:
        pass  # parser tolerante: lo construido hasta el error sirve
    return builder.root


# ── Selectores (subset): tag, #id, .class, [attr], [attr=v], descendencia ───

_COMPOUND_RE = re.compile(
    r"^([a-zA-Z][\w-]*|\*)?"        # tag u opcional *
    r"(#[\w-]+)?"                   # #id
    r"((?:\.[\w-]+)*)"              # .clases
    r"((?:\[[^\]]+\])*)$")          # [attr] / [attr=v]


def _parse_compound(part):
    m = _COMPOUND_RE.match(part)
    if not m:
        raise ValueError(f"selector no soportado: {part!r}")
    tag = m.group(1) or None
    node_id = m.group(2)[1:] if m.group(2) else None
    classes = [c for c in (m.group(3) or "").split(".") if c]
    attrs = []
    for raw in re.findall(r"\[([^\]]+)\]", m.group(4) or ""):
        if "=" in raw:
            name, val = raw.split("=", 1)
            attrs.append((name.strip().lower(), val.strip().strip('"\'')))
        else:
            attrs.append((raw.strip().lower(), None))
    return {"tag": tag if tag != "*" else None, "id": node_id,
            "classes": classes, "attrs": attrs}


def _match_compound(node, comp):
    if comp["tag"] and node.tag != comp["tag"]:
        return False
    if comp["id"] and node.attrs.get("id") != comp["id"]:
        return False
    node_classes = (node.attrs.get("class") or "").split()
    for cls in comp["classes"]:
        if cls not in node_classes:
            return False
    for name, val in comp["attrs"]:
        if name not in node.attrs:
            return False
        if val is not None and node.attrs.get(name, "").lower() != val.lower():
            return False
    return True


def find_all(root, selector):
    """Todos los nodos que matchean el selector (descendencia con espacio)."""
    chain = [_parse_compound(p) for p in selector.split()]
    out = []
    for node in root.walk():
        if not _match_compound(node, chain[-1]):
            continue
        # ancestros deben matchear la cadena restante, en orden, hacia arriba
        needed = len(chain) - 2
        anc = node.parent
        while needed >= 0 and anc is not None and anc.tag != "#document":
            if _match_compound(anc, chain[needed]):
                needed -= 1
            anc = anc.parent
        if needed < 0:
            out.append(node)
    return out


# ── Parser CSS minimo (bloques <style>) ──────────────────────────────────────

def extract_style_text(root):
    parts = []
    for node in root.walk():
        if node.tag == "style":
            parts.append(node.own_text() or node.text())
    return "\n".join(parts)


def parse_css(text, media=None):
    """Reglas planas [{selector, decls, media}]; @media recursivo, otros
    @-rules (keyframes, font-face) se saltean — fuera del alcance de asserts."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    rules = []
    i, n = 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j == -1:
            break
        sel = text[i:j].strip()
        # ultimo statement del bloque previo puede quedar pegado (p.ej. tras
        # un @import ...;): quedarse con lo que sigue al ultimo ';'
        sel = sel.split(";")[-1].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        body = text[j + 1:k - 1]
        if sel.lower().startswith("@media"):
            rules.extend(parse_css(body, media=sel))
        elif sel.startswith("@"):
            pass
        else:
            decls = {}
            for d in body.split(";"):
                if ":" in d:
                    prop, val = d.split(":", 1)
                    decls[prop.strip().lower()] = val.strip().lower()
            for s in sel.split(","):
                s = s.strip()
                if s:
                    rules.append({"selector": s, "decls": decls, "media": media})
        i = k
    return rules


# ── Asserts (cada uno devuelve (ok: bool, detail: str)) ──────────────────────

def _a_doc_basics(raw, root, css, p):
    checks = []
    if not re.search(r"<!doctype\s+html", raw, re.IGNORECASE):
        checks.append("falta <!DOCTYPE html>")
    for tag in ("html", "head", "body"):
        if not find_all(root, tag):
            checks.append(f"falta <{tag}>")
    titles = find_all(root, "title")
    if not titles or not titles[0].text():
        checks.append("falta <title> con texto")
    return (not checks, "; ".join(checks) or "ok")


def _a_lang_attr(raw, root, css, p):
    htmls = find_all(root, "html")
    ok = bool(htmls) and bool(htmls[0].attrs.get("lang", "").strip())
    return ok, "ok" if ok else "<html> sin atributo lang"


def _a_meta_viewport(raw, root, css, p):
    for node in find_all(root, "meta"):
        if node.attrs.get("name", "").lower() == "viewport" and \
                "width=device-width" in node.attrs.get("content", "").lower():
            return True, "ok"
    return False, "sin <meta name=viewport> con width=device-width"


def _a_single_file(raw, root, css, p):
    bad = []
    for node in find_all(root, "link"):
        if "stylesheet" in node.attrs.get("rel", "").lower():
            bad.append(f"<link stylesheet href={node.attrs.get('href', '')!r}>")
    for node in find_all(root, "script"):
        if node.attrs.get("src", "").strip():
            bad.append(f"<script src={node.attrs['src']!r}>")
    return (not bad, "; ".join(bad) or "ok")


def _a_no_inline_styles(raw, root, css, p):
    offenders = [n.tag for n in root.walk() if n.attrs.get("style", "").strip()]
    return (not offenders,
            f"style= inline en: {', '.join(offenders[:5])}" if offenders else "ok")


def _a_heading_order(raw, root, css, p):
    levels = [int(n.tag[1]) for n in root.walk()
              if re.fullmatch(r"h[1-6]", n.tag)]
    n_h1 = levels.count(1)
    if n_h1 != 1:
        return False, f"{n_h1} <h1> (debe ser exactamente 1)"
    if levels and levels[0] != 1:
        return False, f"el primer heading es h{levels[0]}, no h1"
    prev = 0
    for lv in levels:
        if lv > prev + 1:
            return False, f"salto de h{prev} a h{lv}"
        prev = lv
    return True, "ok"


def _a_img_alt(raw, root, css, p):
    missing = [n.attrs.get("src", "?")[:40] for n in find_all(root, "img")
               if not n.attrs.get("alt", "").strip()]
    return (not missing,
            f"img sin alt: {missing[:3]}" if missing else "ok")


def _a_element(raw, root, css, p):
    found = find_all(root, p["sel"])
    n, lo, hi = len(found), p.get("min", 1), p.get("max")
    ok = n >= lo and (hi is None or n <= hi)
    rng = f">={lo}" + (f",<={hi}" if hi is not None else "")
    return ok, f"{n} x '{p['sel']}' (esperado {rng})"


def _a_text(raw, root, css, p):
    needle = p["contains"].lower()
    for node in find_all(root, p["sel"]):
        if needle in node.text().lower():
            return True, "ok"
    return False, f"ningun '{p['sel']}' contiene {p['contains']!r}"


def _a_css_rule(raw, root, css, p):
    """Existe una regla cuyo selector contiene `sel` (""=cualquiera), que
    declara `prop` y (opcional) cuyo valor contiene alguno de `val`."""
    want_sel = p.get("sel", "").lower()
    prop = p["prop"].lower()
    vals = p.get("val")
    if isinstance(vals, str):
        vals = [vals]
    for rule in css:
        if want_sel and want_sel not in rule["selector"].lower():
            continue
        if prop not in rule["decls"]:
            continue
        if vals is None or any(v.lower() in rule["decls"][prop] for v in vals):
            return True, "ok"
    return False, (f"sin regla CSS con selector~{want_sel!r} y "
                   f"{prop}{':' + '|'.join(vals) if vals else ''}")


def _a_css_media(raw, root, css, p):
    needle = p.get("contains", "").lower()
    for rule in css:
        if rule["media"] and needle in rule["media"].lower():
            return True, "ok"
    return False, (f"sin regla dentro de @media que contenga {needle!r}"
                   if needle else "sin @media con reglas")


def _a_labels(raw, root, css, p):
    """Todo input visible necesita label[for], aria-label o label ancestro."""
    label_for = {n.attrs.get("for") for n in find_all(root, "label")
                 if n.attrs.get("for")}
    bad = []
    for node in find_all(root, "input"):
        itype = node.attrs.get("type", "text").lower()
        if itype in ("hidden", "submit", "button", "reset"):
            continue
        if node.attrs.get("aria-label", "").strip():
            continue
        if node.attrs.get("id") in label_for:
            continue
        anc = node.parent
        while anc is not None and anc.tag != "#document":
            if anc.tag == "label":
                break
            anc = anc.parent
        else:
            bad.append(node.attrs.get("name") or node.attrs.get("id") or itype)
            continue
    return (not bad, f"inputs sin label: {bad[:4]}" if bad else "ok")


ASSERT_FNS = {
    "doc_basics": _a_doc_basics,
    "lang_attr": _a_lang_attr,
    "meta_viewport": _a_meta_viewport,
    "single_file": _a_single_file,
    "no_inline_styles": _a_no_inline_styles,
    "heading_order": _a_heading_order,
    "img_alt": _a_img_alt,
    "element": _a_element,
    "text": _a_text,
    "css_rule": _a_css_rule,
    "css_media": _a_css_media,
    "labels": _a_labels,
}


def check_page(html_text, asserts):
    """Corre todos los asserts sobre la pagina; [{...assert, ok, detail}].

    Una pagina sin NINGUN elemento parseable no es un documento: falla todos
    los asserts (evita que los de ausencia-de-violacion — single_file,
    no_inline_styles, labels — pasen vacios y le regalen piso a una
    respuesta vacia)."""
    root = parse_html(html_text or "")
    if not any(True for _ in root.walk()):
        return [{**a, "ok": False, "detail": "pagina vacia (sin elementos)"}
                for a in asserts]
    css = parse_css(extract_style_text(root))
    results = []
    for a in asserts:
        fn = ASSERT_FNS[a["type"]]
        try:
            ok, detail = fn(html_text or "", root, css, a)
        except Exception as exc:  # un assert roto cuenta como FAIL, no crash
            ok, detail = False, f"checker error: {exc}"
        results.append({**a, "ok": ok, "detail": detail})
    return results


# ── Specs congeladas (25) ────────────────────────────────────────────────────
# Regla de justicia: cada assert corresponde a un requisito ESCRITO en el
# prompt (los base, a BASE_REQUIREMENTS). Numeros exactos pedidos = numeros
# exactos asserteados.

SPECS = [
    {"id": "D01", "title": "pricing table",
     "prompt": (
         "Create a pricing page for a SaaS product called 'CloudBox'. "
         "Requirements: (1) a single <h1> with the product name; (2) exactly "
         "3 pricing cards, each an <article> with class \"plan\", inside a "
         "container with class \"plans\"; (3) each plan has an <h2> with the "
         "plan name, a <p> with class \"price\", and a <ul> with at least 3 "
         "<li> features; (4) each plan has a link or button with class "
         "\"cta\"; (5) exactly one plan is highlighted with the extra class "
         "\"featured\"; (6) the .plans container uses CSS grid or flexbox; "
         "(7) a media query for screens narrower than 700px adapts the "
         "layout."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "CloudBox"},
         {"type": "element", "sel": ".plans", "min": 1},
         {"type": "element", "sel": "article.plan", "min": 3, "max": 3},
         {"type": "element", "sel": "article.plan h2", "min": 3},
         {"type": "element", "sel": "article.plan p.price", "min": 3},
         {"type": "element", "sel": "article.plan ul li", "min": 9},
         {"type": "element", "sel": ".cta", "min": 3},
         {"type": "element", "sel": "article.featured", "min": 1, "max": 1},
         {"type": "css_rule", "sel": ".plans", "prop": "display",
          "val": ["grid", "flex"]},
         {"type": "css_media", "contains": "700px"},
     ]},

    {"id": "D02", "title": "login form",
     "prompt": (
         "Create a login page for an app called 'Notely'. Requirements: "
         "(1) a single <h1>; (2) a <form> with class \"login\" containing an "
         "email input (type=\"email\") and a password input "
         "(type=\"password\"), both marked required; (3) every input has an "
         "associated <label> (for/id); (4) a \"remember me\" checkbox input "
         "with its own label; (5) a submit button (<button type=\"submit\">); "
         "(6) the form is centered on the page inside a card with class "
         "\"card\" that has a border-radius and a box-shadow in CSS; (7) a "
         "CSS rule styles the button on hover (a selector with :hover)."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "form.login", "min": 1},
         {"type": "element", "sel": "input[type=email][required]", "min": 1},
         {"type": "element", "sel": "input[type=password][required]", "min": 1},
         {"type": "element", "sel": "input[type=checkbox]", "min": 1},
         {"type": "labels"},
         {"type": "element", "sel": "button[type=submit]", "min": 1},
         {"type": "element", "sel": ".card", "min": 1},
         {"type": "css_rule", "sel": ".card", "prop": "border-radius"},
         {"type": "css_rule", "sel": ".card", "prop": "box-shadow"},
         {"type": "css_rule", "sel": ":hover", "prop": "background"},
     ]},

    {"id": "D03", "title": "landing hero",
     "prompt": (
         "Create a landing page for a fitness app called 'PulseFit'. "
         "Requirements: (1) a <header> containing a <nav> with a brand link "
         "with class \"logo\" and exactly 3 more navigation links inside a "
         "<ul>; (2) a hero <section> with class \"hero\" containing the "
         "single <h1>, a paragraph, and a call-to-action link with class "
         "\"btn\"; (3) the hero has a CSS background (background or "
         "background-color rule on .hero); (4) the nav <ul> uses flexbox; "
         "(5) a media query for screens narrower than 600px; (6) a <footer> "
         "with a copyright paragraph containing the text 'PulseFit'."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "header nav", "min": 1},
         {"type": "element", "sel": "nav .logo", "min": 1},
         {"type": "element", "sel": "nav ul li", "min": 3},
         {"type": "element", "sel": "section.hero", "min": 1},
         {"type": "element", "sel": ".hero h1", "min": 1},
         {"type": "element", "sel": ".hero .btn", "min": 1},
         {"type": "css_rule", "sel": ".hero", "prop": "background"},
         {"type": "css_rule", "sel": "ul", "prop": "display", "val": "flex"},
         {"type": "css_media", "contains": "600px"},
         {"type": "text", "sel": "footer", "contains": "PulseFit"},
     ]},

    {"id": "D04", "title": "blog card grid",
     "prompt": (
         "Create a blog index page called 'The Daily Byte'. Requirements: "
         "(1) a single <h1> with the blog name; (2) exactly 4 post cards, "
         "each an <article> with class \"card\", inside a container with "
         "class \"grid\"; (3) each card has an <img> (any placeholder src, "
         "descriptive alt), an <h2> title, a <p> excerpt, and a link with "
         "class \"read-more\"; (4) the .grid container uses CSS grid with a "
         "gap; (5) a media query for screens narrower than 800px switches "
         "the grid to one column."),
     "images": True,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "Daily Byte"},
         {"type": "element", "sel": ".grid", "min": 1},
         {"type": "element", "sel": "article.card", "min": 4, "max": 4},
         {"type": "element", "sel": "article.card img", "min": 4},
         {"type": "element", "sel": "article.card h2", "min": 4},
         {"type": "element", "sel": ".read-more", "min": 4},
         {"type": "css_rule", "sel": ".grid", "prop": "display", "val": "grid"},
         {"type": "css_rule", "sel": ".grid", "prop": "gap"},
         {"type": "css_media", "contains": "800px"},
     ]},

    {"id": "D05", "title": "contact form",
     "prompt": (
         "Create a contact page for a studio called 'Bravo Design'. "
         "Requirements: (1) a single <h1>; (2) a <form> with class "
         "\"contact\" containing: a text input for the name, an email input, "
         "and a <textarea> for the message — all three marked required and "
         "each with an associated <label> (for/id); (3) a submit <button>; "
         "(4) inputs and textarea have a CSS border-radius rule; (5) a "
         "<footer> containing an <address> element with the text "
         "'hello@bravo.design'."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "form.contact", "min": 1},
         {"type": "element", "sel": "form.contact input[type=text][required]",
          "min": 1},
         {"type": "element", "sel": "form.contact input[type=email][required]",
          "min": 1},
         {"type": "element", "sel": "form.contact textarea[required]", "min": 1},
         {"type": "labels"},
         {"type": "element", "sel": "button", "min": 1},
         {"type": "css_rule", "sel": "", "prop": "border-radius"},
         {"type": "element", "sel": "footer address", "min": 1},
         {"type": "text", "sel": "address", "contains": "hello@bravo.design"},
     ]},

    {"id": "D06", "title": "FAQ accordion",
     "prompt": (
         "Create an FAQ page for an online store called 'Kupo'. "
         "Requirements: (1) a single <h1> containing 'FAQ'; (2) exactly 5 "
         "questions, each a <details> element with a <summary> (the "
         "question) and at least one <p> (the answer), all inside a "
         "<section> with class \"faq\"; (3) the first <details> has the "
         "open attribute; (4) a CSS rule styles summary with cursor: "
         "pointer; (5) details elements have a CSS border or "
         "border-bottom rule."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "FAQ"},
         {"type": "element", "sel": "section.faq", "min": 1},
         {"type": "element", "sel": "section.faq details", "min": 5, "max": 5},
         {"type": "element", "sel": "details summary", "min": 5},
         {"type": "element", "sel": "details p", "min": 5},
         {"type": "element", "sel": "details[open]", "min": 1},
         {"type": "css_rule", "sel": "summary", "prop": "cursor",
          "val": "pointer"},
         {"type": "css_rule", "sel": "details", "prop": "border"},
     ]},

    {"id": "D07", "title": "data table",
     "prompt": (
         "Create a page showing a comparison table of 5 programming "
         "languages. Requirements: (1) a single <h1>; (2) a <table> with a "
         "<caption>, a <thead> with one header row of exactly 4 <th> "
         "columns, and a <tbody> with at least 5 rows; (3) zebra striping "
         "via a CSS rule using nth-child on the table rows; (4) the table "
         "has a CSS border-collapse: collapse rule; (5) th cells have a "
         "distinct background-color rule."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "table caption", "min": 1},
         {"type": "element", "sel": "thead th", "min": 4, "max": 4},
         {"type": "element", "sel": "tbody tr", "min": 5},
         {"type": "css_rule", "sel": "nth-child", "prop": "background"},
         {"type": "css_rule", "sel": "table", "prop": "border-collapse",
          "val": "collapse"},
         {"type": "css_rule", "sel": "th", "prop": "background"},
     ]},

    {"id": "D08", "title": "profile card",
     "prompt": (
         "Create a personal profile page for 'Ana Torres', UX engineer. "
         "Requirements: (1) a centered card with class \"profile\" "
         "containing: an <img> avatar (any placeholder src, descriptive "
         "alt) with class \"avatar\", the single <h1> with the name, a "
         "paragraph with class \"role\" containing 'UX engineer', and a "
         "short bio paragraph; (2) a <ul> with class \"social\" of exactly "
         "3 links; (3) the avatar has a CSS border-radius of 50%; (4) the "
         "card has box-shadow and border-radius rules; (5) the page body "
         "uses flexbox or grid to center the card."),
     "images": True,
     "asserts": [
         {"type": "element", "sel": ".profile", "min": 1},
         {"type": "element", "sel": ".profile img.avatar", "min": 1},
         {"type": "text", "sel": ".profile h1", "contains": "Ana Torres"},
         {"type": "text", "sel": ".role", "contains": "UX engineer"},
         {"type": "element", "sel": "ul.social a", "min": 3, "max": 3},
         {"type": "css_rule", "sel": ".avatar", "prop": "border-radius",
          "val": "50%"},
         {"type": "css_rule", "sel": ".profile", "prop": "box-shadow"},
         {"type": "css_rule", "sel": "body", "prop": "display",
          "val": ["flex", "grid"]},
     ]},

    {"id": "D09", "title": "newsletter signup",
     "prompt": (
         "Create a newsletter signup page for a magazine called 'Orbit'. "
         "Requirements: (1) a single <h1>; (2) a <section> with class "
         "\"newsletter\" containing a short paragraph and a <form>; (3) the "
         "form has an email input (type=\"email\", required) with an "
         "associated <label> or aria-label; (4) a submit button "
         "(<button type=\"submit\">) whose text contains 'Subscribe'; "
         "(5) a <footer> with fine print inside a <small> element; (6) the "
         ".newsletter section has a CSS max-width rule."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "section.newsletter", "min": 1},
         {"type": "element", "sel": "section.newsletter form", "min": 1},
         {"type": "element", "sel": "input[type=email][required]", "min": 1},
         {"type": "labels"},
         {"type": "element", "sel": "button[type=submit]", "min": 1},
         {"type": "text", "sel": "button", "contains": "Subscribe"},
         {"type": "element", "sel": "footer small", "min": 1},
         {"type": "css_rule", "sel": ".newsletter", "prop": "max-width"},
     ]},

    {"id": "D10", "title": "404 page",
     "prompt": (
         "Create a 404 error page. Requirements: (1) the single <h1> "
         "contains '404'; (2) a paragraph with class \"message\" explaining "
         "the page was not found; (3) a link with class \"home\" whose text "
         "contains 'home'; (4) the body uses flexbox or grid to center the "
         "content; (5) the h1 has a large CSS font-size rule."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "404"},
         {"type": "element", "sel": "p.message", "min": 1},
         {"type": "element", "sel": "a.home", "min": 1},
         {"type": "text", "sel": "a.home", "contains": "home"},
         {"type": "css_rule", "sel": "body", "prop": "display",
          "val": ["flex", "grid"]},
         {"type": "css_rule", "sel": "h1", "prop": "font-size"},
     ]},

    {"id": "D11", "title": "dashboard stat tiles",
     "prompt": (
         "Create an analytics dashboard page titled 'Sales Overview'. "
         "Requirements: (1) a single <h1>; (2) a <section> with class "
         "\"stats\" containing exactly 4 tiles, each an <article> with "
         "class \"stat\"; (3) each tile has an <h2> (metric name) and a "
         "<p> with class \"value\" (the number); (4) the .stats section "
         "uses CSS grid with a grid-template-columns rule; (5) a media "
         "query for screens narrower than 900px adapts the columns; "
         "(6) the .value paragraphs have a CSS font-size rule."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "section.stats", "min": 1},
         {"type": "element", "sel": "article.stat", "min": 4, "max": 4},
         {"type": "element", "sel": "article.stat h2", "min": 4},
         {"type": "element", "sel": "article.stat p.value", "min": 4},
         {"type": "css_rule", "sel": ".stats", "prop": "grid-template-columns"},
         {"type": "css_media", "contains": "900px"},
         {"type": "css_rule", "sel": ".value", "prop": "font-size"},
     ]},

    {"id": "D12", "title": "recipe page",
     "prompt": (
         "Create a recipe page for 'Pancakes'. Requirements: (1) the single "
         "<h1> contains 'Pancakes'; (2) one photo <img> (any placeholder "
         "src, descriptive alt); (3) a <section> with class \"ingredients\" "
         "with an <h2> containing 'Ingredients' and a <ul> of at least 5 "
         "<li>; (4) a <section> with class \"steps\" with an <h2> "
         "containing 'Instructions' and an <ol> of at least 4 <li>; (5) a "
         "paragraph with class \"time\" whose text contains 'minutes'."),
     "images": True,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "Pancakes"},
         {"type": "element", "sel": "img", "min": 1},
         {"type": "element", "sel": "section.ingredients h2", "min": 1},
         {"type": "text", "sel": "section.ingredients h2",
          "contains": "Ingredients"},
         {"type": "element", "sel": "section.ingredients ul li", "min": 5},
         {"type": "element", "sel": "section.steps h2", "min": 1},
         {"type": "text", "sel": "section.steps h2",
          "contains": "Instructions"},
         {"type": "element", "sel": "section.steps ol li", "min": 4},
         {"type": "text", "sel": "p.time", "contains": "minutes"},
     ]},

    {"id": "D13", "title": "product card",
     "prompt": (
         "Create a product page for a store called 'TechMart'. "
         "Requirements: (1) the single <h1> contains 'TechMart'; (2) an "
         "<article> with class \"product\" containing: an <img> (any "
         "placeholder src, descriptive alt), an <h2> with the product "
         "name, a <p> with class \"price\" containing '$', a <span> with "
         "class \"rating\", and a <button> with class \"add\" whose text "
         "contains 'Add to cart'; (3) the .add button has a CSS "
         "background-color rule and a :hover rule changing its "
         "background; (4) the .product card has box-shadow and "
         "border-radius rules."),
     "images": True,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "TechMart"},
         {"type": "element", "sel": "article.product", "min": 1},
         {"type": "element", "sel": "article.product img", "min": 1},
         {"type": "element", "sel": "article.product h2", "min": 1},
         {"type": "text", "sel": ".price", "contains": "$"},
         {"type": "element", "sel": "span.rating", "min": 1},
         {"type": "element", "sel": "button.add", "min": 1},
         {"type": "text", "sel": "button.add", "contains": "Add to cart"},
         {"type": "css_rule", "sel": ".add", "prop": "background"},
         {"type": "css_rule", "sel": ":hover", "prop": "background"},
         {"type": "css_rule", "sel": ".product", "prop": "box-shadow"},
         {"type": "css_rule", "sel": ".product", "prop": "border-radius"},
     ]},

    {"id": "D14", "title": "team section",
     "prompt": (
         "Create a team page titled 'Our Team' for an agency. "
         "Requirements: (1) the single <h1> contains 'Our Team'; (2) a "
         "container with class \"team\" holding exactly 3 <figure> "
         "elements with class \"member\"; (3) each member has an <img> "
         "(any placeholder src, descriptive alt) and a <figcaption> with "
         "the person's name; (4) the .team container uses flexbox or "
         "grid; (5) the member images are round via a border-radius: 50% "
         "rule."),
     "images": True,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "Our Team"},
         {"type": "element", "sel": ".team", "min": 1},
         {"type": "element", "sel": "figure.member", "min": 3, "max": 3},
         {"type": "element", "sel": "figure.member img", "min": 3},
         {"type": "element", "sel": "figure.member figcaption", "min": 3},
         {"type": "css_rule", "sel": ".team", "prop": "display",
          "val": ["flex", "grid"]},
         {"type": "css_rule", "sel": "", "prop": "border-radius",
          "val": "50%"},
     ]},

    {"id": "D15", "title": "timeline",
     "prompt": (
         "Create a company history page titled 'Company History'. "
         "Requirements: (1) the single <h1> contains 'History'; (2) an "
         "<ol> with class \"timeline\" of exactly 4 <li> milestones; "
         "(3) each milestone has an <h2>, a <p>, and a <time> element "
         "with a datetime attribute; (4) the timeline items have a CSS "
         "border-left rule; (5) the time elements have a CSS font-weight "
         "rule."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "History"},
         {"type": "element", "sel": "ol.timeline li", "min": 4, "max": 4},
         {"type": "element", "sel": "ol.timeline li h2", "min": 4},
         {"type": "element", "sel": "ol.timeline li p", "min": 4},
         {"type": "element", "sel": "time[datetime]", "min": 4},
         {"type": "css_rule", "sel": "li", "prop": "border-left"},
         {"type": "css_rule", "sel": "time", "prop": "font-weight"},
     ]},

    {"id": "D16", "title": "navbar + footer layout",
     "prompt": (
         "Create a documentation home page for a tool called 'GridKit'. "
         "Requirements: (1) a <header> containing a <nav> with a <ul> of "
         "exactly 4 links; (2) the header is sticky via a CSS position: "
         "sticky rule; (3) a <main> with the single <h1> and at least 2 "
         "<section> elements, each with an <h2>; (4) a <footer> with "
         "exactly 3 columns, each a <div> with class \"footer-col\" "
         "containing a <ul> of links; (5) the footer uses flexbox or "
         "grid."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "header nav ul li a", "min": 4},
         {"type": "element", "sel": "header nav ul li", "min": 4, "max": 4},
         {"type": "css_rule", "sel": "header", "prop": "position",
          "val": "sticky"},
         {"type": "element", "sel": "main h1", "min": 1},
         {"type": "element", "sel": "main section", "min": 2},
         {"type": "element", "sel": "main section h2", "min": 2},
         {"type": "element", "sel": "footer div.footer-col", "min": 3,
          "max": 3},
         {"type": "element", "sel": ".footer-col ul", "min": 3},
         {"type": "css_rule", "sel": "footer", "prop": "display",
          "val": ["flex", "grid"]},
     ]},

    {"id": "D17", "title": "testimonials",
     "prompt": (
         "Create a testimonials page titled 'What our clients say'. "
         "Requirements: (1) the single <h1> contains 'clients'; (2) a "
         "<section> with class \"testimonials\" holding exactly 3 "
         "<blockquote> elements with class \"testimonial\"; (3) each "
         "testimonial has a <p> (the quote) and a <cite> (the author); "
         "(4) blockquotes are styled with a CSS font-style: italic rule; "
         "(5) cites have a CSS font-weight rule; (6) the .testimonials "
         "section uses flexbox or grid."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "clients"},
         {"type": "element", "sel": "section.testimonials", "min": 1},
         {"type": "element", "sel": "blockquote.testimonial", "min": 3,
          "max": 3},
         {"type": "element", "sel": "blockquote.testimonial p", "min": 3},
         {"type": "element", "sel": "blockquote.testimonial cite", "min": 3},
         {"type": "css_rule", "sel": "blockquote", "prop": "font-style",
          "val": "italic"},
         {"type": "css_rule", "sel": "cite", "prop": "font-weight"},
         {"type": "css_rule", "sel": ".testimonials", "prop": "display",
          "val": ["flex", "grid"]},
     ]},

    {"id": "D18", "title": "dark theme with CSS variables",
     "prompt": (
         "Create a blog article page that supports dark mode via CSS "
         "custom properties. Requirements: (1) a single <h1>; (2) a "
         ":root CSS rule defining --bg and --text custom properties; "
         "(3) the body uses var(--bg) for background and var(--text) for "
         "color; (4) a @media (prefers-color-scheme: dark) query "
         "overrides the variables; (5) the content lives in a <div> with "
         "class \"container\" that has a CSS max-width rule."),
     "images": False,
     "asserts": [
         {"type": "css_rule", "sel": ":root", "prop": "--bg"},
         {"type": "css_rule", "sel": ":root", "prop": "--text"},
         {"type": "css_rule", "sel": "body", "prop": "background",
          "val": "var"},
         {"type": "css_rule", "sel": "body", "prop": "color", "val": "var"},
         {"type": "css_media", "contains": "prefers-color-scheme"},
         {"type": "element", "sel": "div.container", "min": 1},
         {"type": "css_rule", "sel": ".container", "prop": "max-width"},
     ]},

    {"id": "D19", "title": "image gallery",
     "prompt": (
         "Create a photo gallery page titled 'Gallery'. Requirements: "
         "(1) the single <h1> contains 'Gallery'; (2) a container with "
         "class \"gallery\" holding exactly 6 <figure> elements, each "
         "with an <img> (any placeholder src, descriptive alt) and a "
         "<figcaption>; (3) the gallery uses CSS grid with a "
         "grid-template-columns rule; (4) a media query for screens "
         "narrower than 600px adapts the columns; (5) images have a CSS "
         "width: 100% rule."),
     "images": True,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "Gallery"},
         {"type": "element", "sel": ".gallery figure", "min": 6, "max": 6},
         {"type": "element", "sel": ".gallery figure img", "min": 6},
         {"type": "element", "sel": ".gallery figure figcaption", "min": 6},
         {"type": "css_rule", "sel": ".gallery",
          "prop": "grid-template-columns"},
         {"type": "css_media", "contains": "600px"},
         {"type": "css_rule", "sel": "img", "prop": "width", "val": "100%"},
     ]},

    {"id": "D20", "title": "breadcrumbs + pagination",
     "prompt": (
         "Create a search results page for a shop. Requirements: (1) a "
         "single <h1>; (2) a breadcrumb <nav> with aria-label="
         "\"Breadcrumb\" containing an <ol> of exactly 3 <li>; (3) a "
         "pagination <nav> with class \"pagination\" containing at least "
         "5 links; (4) the current page link is marked with "
         "aria-current=\"page\"; (5) the breadcrumb <ol> uses a CSS "
         "display: flex rule; (6) pagination links have a CSS padding "
         "rule."),
     "images": False,
     "asserts": [
         {"type": "element", "sel": "nav[aria-label=Breadcrumb] ol li",
          "min": 3, "max": 3},
         {"type": "element", "sel": "nav.pagination a", "min": 5},
         {"type": "element", "sel": "a[aria-current=page]", "min": 1},
         {"type": "css_rule", "sel": "ol", "prop": "display", "val": "flex"},
         {"type": "css_rule", "sel": ".pagination", "prop": "padding"},
     ]},

    {"id": "D21", "title": "features section",
     "prompt": (
         "Create a features page for a developer tool called 'DevBox'. "
         "Requirements: (1) the single <h1> contains 'DevBox'; (2) a "
         "container with class \"features\" holding exactly 3 <div> "
         "elements with class \"feature\"; (3) each feature has a <span> "
         "with class \"icon\" (an emoji), an <h2>, and a <p>; (4) the "
         ".features container uses flexbox or grid with a gap rule; "
         "(5) the .icon spans have a CSS font-size rule."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "DevBox"},
         {"type": "element", "sel": ".features", "min": 1},
         {"type": "element", "sel": "div.feature", "min": 3, "max": 3},
         {"type": "element", "sel": "div.feature span.icon", "min": 3},
         {"type": "element", "sel": "div.feature h2", "min": 3},
         {"type": "element", "sel": "div.feature p", "min": 3},
         {"type": "css_rule", "sel": ".features", "prop": "display",
          "val": ["flex", "grid"]},
         {"type": "css_rule", "sel": ".features", "prop": "gap"},
         {"type": "css_rule", "sel": ".icon", "prop": "font-size"},
     ]},

    {"id": "D22", "title": "signup form with validation",
     "prompt": (
         "Create an account creation page titled 'Create account'. "
         "Requirements: (1) the single <h1> contains 'Create account'; "
         "(2) a <form> with class \"signup\" containing: a username "
         "input (type=\"text\", required, minlength=\"3\"), an email "
         "input (type=\"email\", required), and a password input "
         "(type=\"password\", required, minlength=\"8\") — each with an "
         "associated <label> (for/id); (3) a <select> for the country "
         "with at least 3 <option> entries; (4) a submit button "
         "(<button type=\"submit\">); (5) a CSS rule for input:focus "
         "that changes the outline."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "Create account"},
         {"type": "element", "sel": "form.signup", "min": 1},
         {"type": "element",
          "sel": "input[type=text][required][minlength=3]", "min": 1},
         {"type": "element", "sel": "input[type=email][required]", "min": 1},
         {"type": "element",
          "sel": "input[type=password][required][minlength=8]", "min": 1},
         {"type": "labels"},
         {"type": "element", "sel": "select option", "min": 3},
         {"type": "element", "sel": "button[type=submit]", "min": 1},
         {"type": "css_rule", "sel": ":focus", "prop": "outline"},
     ]},

    {"id": "D23", "title": "alert banners",
     "prompt": (
         "Create a notifications demo page titled 'System status'. "
         "Requirements: (1) the single <h1> contains 'System status'; "
         "(2) exactly 3 <div> alert banners, all with class \"alert\" "
         "and role=\"alert\": one with extra class \"alert-success\", "
         "one \"alert-error\", one \"alert-warning\"; (3) each alert "
         "contains a <strong> element; (4) each variant class has its "
         "own CSS background rule (three distinct rules); (5) the .alert "
         "class has CSS padding and border-radius rules."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "System status"},
         {"type": "element", "sel": "div.alert[role=alert]", "min": 3,
          "max": 3},
         {"type": "element", "sel": ".alert-success", "min": 1},
         {"type": "element", "sel": ".alert-error", "min": 1},
         {"type": "element", "sel": ".alert-warning", "min": 1},
         {"type": "element", "sel": ".alert strong", "min": 3},
         {"type": "css_rule", "sel": ".alert-success", "prop": "background"},
         {"type": "css_rule", "sel": ".alert-error", "prop": "background"},
         {"type": "css_rule", "sel": ".alert-warning", "prop": "background"},
         {"type": "css_rule", "sel": ".alert", "prop": "padding"},
         {"type": "css_rule", "sel": ".alert", "prop": "border-radius"},
     ]},

    {"id": "D24", "title": "skill progress bars",
     "prompt": (
         "Create a resume skills page titled 'My Skills'. Requirements: "
         "(1) the single <h1> contains 'Skills'; (2) a <ul> with class "
         "\"skills\" of exactly 4 <li>, each containing a <label> with "
         "the skill name and a <progress> element with value and "
         "max=\"100\" attributes; (3) progress elements have a CSS "
         "width: 100% rule; (4) the .skills list has a CSS list-style: "
         "none rule."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "Skills"},
         {"type": "element", "sel": "ul.skills li", "min": 4, "max": 4},
         {"type": "element", "sel": "ul.skills li label", "min": 4},
         {"type": "element", "sel": "ul.skills li progress[max=100]",
          "min": 4},
         {"type": "css_rule", "sel": "progress", "prop": "width",
          "val": "100%"},
         {"type": "css_rule", "sel": ".skills", "prop": "list-style",
          "val": "none"},
     ]},

    {"id": "D25", "title": "article typography",
     "prompt": (
         "Create a long-form article page titled 'The Art of Focus'. "
         "Requirements: (1) the single <h1> contains 'The Art of Focus'; "
         "(2) an <article> with at least 4 <p>, one <h2>, one "
         "<blockquote>, and a link (<a>) inside one of the paragraphs; "
         "(3) the article has CSS max-width and margin rules (centered "
         "column); (4) the body has CSS font-family and line-height "
         "rules; (5) the blockquote has a CSS border-left rule."),
     "images": False,
     "asserts": [
         {"type": "text", "sel": "h1", "contains": "The Art of Focus"},
         {"type": "element", "sel": "article p", "min": 4},
         {"type": "element", "sel": "article h2", "min": 1},
         {"type": "element", "sel": "article blockquote", "min": 1},
         {"type": "element", "sel": "article p a", "min": 1},
         {"type": "css_rule", "sel": "article", "prop": "max-width"},
         {"type": "css_rule", "sel": "article", "prop": "margin"},
         {"type": "css_rule", "sel": "body", "prop": "font-family"},
         {"type": "css_rule", "sel": "body", "prop": "line-height"},
         {"type": "css_rule", "sel": "blockquote", "prop": "border-left"},
     ]},
]


# ── Self-test del checker (--check-only): fixtures + casos esperados ─────────
# El fixture GOOD pasa todos los tipos de assert; los BAD fallan cada tipo
# a proposito. Esto verifica el ORACULO sin gastar modelo (CP0, plan §7).

GOOD_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fixture</title>
<style>
/* comentario */
body { display: flex; margin: 0; }
.card { border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.2); background: #fff; }
.plans { display: grid; gap: 1rem; }
button:hover { background: navy; }
table { border-collapse: collapse; }
tbody tr:nth-child(even) { background: #eee; }
@media (max-width: 700px) { .plans { display: block; } }
</style>
</head>
<body>
<header><nav class="top"><a class="logo" href="#">Fixture</a>
<ul><li><a href="#">A</a></li><li><a href="#">B</a></li><li><a href="#">C</a></li></ul>
</nav></header>
<main>
<h1>Fixture Page</h1>
<section class="hero"><h2>Sub</h2><p class="price">$10</p></section>
<div class="plans">
<article class="plan featured"><h2>Pro</h2><p class="price">$20</p>
<ul><li>a</li><li>b</li><li>c</li></ul><a class="cta" href="#">Go</a></article>
</div>
<img src="x.png" alt="una imagen">
<form class="login"><label for="em">Email</label>
<input id="em" type="email" required>
<label><input type="checkbox"> remember</label>
<button type="submit">Enter</button></form>
</main>
<footer><address>hello@bravo.design</address><p>(c) Fixture</p></footer>
</body>
</html>
"""

BAD_PAGE = """<html>
<head>
<link rel="stylesheet" href="https://cdn.example.com/x.css">
<script src="https://cdn.example.com/x.js"></script>
<style>p { color: red }</style>
</head>
<body>
<h1 style="color:red">One</h1>
<h1>Two</h1>
<h4>Skipped</h4>
<img src="y.png">
<input type="text" name="orphan">
</body>
</html>
"""

# (pagina, assert, esperado) — el self-test exige TODOS los esperados.
SELFTEST_CASES = [
    (GOOD_PAGE, {"type": "doc_basics"}, True),
    (GOOD_PAGE, {"type": "lang_attr"}, True),
    (GOOD_PAGE, {"type": "meta_viewport"}, True),
    (GOOD_PAGE, {"type": "single_file"}, True),
    (GOOD_PAGE, {"type": "no_inline_styles"}, True),
    (GOOD_PAGE, {"type": "heading_order"}, True),
    (GOOD_PAGE, {"type": "img_alt"}, True),
    (GOOD_PAGE, {"type": "labels"}, True),
    (GOOD_PAGE, {"type": "element", "sel": "article.plan", "min": 1, "max": 1}, True),
    (GOOD_PAGE, {"type": "element", "sel": "article.plan ul li", "min": 3}, True),
    (GOOD_PAGE, {"type": "element", "sel": "input[type=email][required]", "min": 1}, True),
    (GOOD_PAGE, {"type": "element", "sel": "nav ul li", "min": 3, "max": 3}, True),
    (GOOD_PAGE, {"type": "text", "sel": "address", "contains": "hello@bravo.design"}, True),
    (GOOD_PAGE, {"type": "text", "sel": "h1", "contains": "fixture page"}, True),
    (GOOD_PAGE, {"type": "css_rule", "sel": ".plans", "prop": "display",
                 "val": ["grid", "flex"]}, True),
    (GOOD_PAGE, {"type": "css_rule", "sel": ":hover", "prop": "background"}, True),
    (GOOD_PAGE, {"type": "css_rule", "sel": "nth-child", "prop": "background"}, True),
    (GOOD_PAGE, {"type": "css_media", "contains": "700px"}, True),
    (GOOD_PAGE, {"type": "css_rule", "sel": ".card", "prop": "border-radius"}, True),
    # negativos: cada tipo debe FALLAR donde corresponde
    (BAD_PAGE, {"type": "doc_basics"}, False),          # sin doctype/title
    (BAD_PAGE, {"type": "lang_attr"}, False),
    (BAD_PAGE, {"type": "meta_viewport"}, False),
    (BAD_PAGE, {"type": "single_file"}, False),         # link+script externos
    (BAD_PAGE, {"type": "no_inline_styles"}, False),    # h1 style=
    (BAD_PAGE, {"type": "heading_order"}, False),       # 2 h1 + salto a h4
    (BAD_PAGE, {"type": "img_alt"}, False),
    (BAD_PAGE, {"type": "labels"}, False),
    (BAD_PAGE, {"type": "element", "sel": ".nonexistent", "min": 1}, False),
    (BAD_PAGE, {"type": "text", "sel": "h1", "contains": "missing"}, False),
    (BAD_PAGE, {"type": "css_rule", "sel": "p", "prop": "display"}, False),
    (BAD_PAGE, {"type": "css_media"}, False),
    (GOOD_PAGE, {"type": "element", "sel": "article.plan", "min": 2}, False),
    # css_rule busca en TODAS las reglas, incluidas las de @media (semantica
    # declarada): un valor inexistente en todo el CSS debe fallar.
    (GOOD_PAGE, {"type": "css_rule", "sel": ".plans", "prop": "display",
                 "val": "inline-block"}, False),
]


def validate_specs():
    """Sanidad de las specs: ids unicos, tipos conocidos, >= 6 asserts."""
    errors = []
    seen = set()
    for spec in SPECS:
        if spec["id"] in seen:
            errors.append(f"{spec['id']}: id duplicado")
        seen.add(spec["id"])
        asserts = full_asserts(spec)
        if len(asserts) < 6:
            errors.append(f"{spec['id']}: solo {len(asserts)} asserts")
        for a in asserts:
            if a["type"] not in ASSERT_FNS:
                errors.append(f"{spec['id']}: tipo desconocido {a['type']}")
            if a["type"] == "element":
                try:
                    [_parse_compound(part) for part in a["sel"].split()]
                except ValueError as exc:
                    errors.append(f"{spec['id']}: {exc}")
    return errors


def full_asserts(spec):
    """Asserts base + img_alt (si la spec pide imagenes) + especificos."""
    base = list(BASE_ASSERTS)
    if spec.get("images"):
        base.append({"type": "img_alt"})
    return base + spec["asserts"]


def run_selftest():
    """Corre los casos del self-test; devuelve (n_ok, n_total, fallas)."""
    fails = []
    for i, (page, a, expected) in enumerate(SELFTEST_CASES):
        [res] = check_page(page, [a])
        if res["ok"] != expected:
            fails.append(f"caso {i}: {a} esperado={expected} "
                         f"obtenido={res['ok']} ({res['detail']})")
    return len(SELFTEST_CASES) - len(fails), len(SELFTEST_CASES), fails


# ── Runner contra el modelo real ─────────────────────────────────────────────

_HTML_FENCE_RE = re.compile(r"```(?:html)?\s*\n(.*?)```", re.DOTALL)


def extract_html(response):
    """Documento HTML de la respuesta: fence ```html, o del <!DOCTYPE/<html
    al ultimo </html> (o al final si el cierre se corto por max_tokens)."""
    if not response:
        return ""
    m = _HTML_FENCE_RE.search(response)
    if m:
        return m.group(1).strip()
    m = re.search(r"<!doctype\s+html|<html[\s>]", response, re.IGNORECASE)
    if m:
        doc = response[m.start():]
        end = doc.lower().rfind("</html>")
        return doc[:end + 7].strip() if end != -1 else doc.strip()
    return response.strip()


def build_prompt(spec_prompt):
    from node.inference_pipeline import _apply_qwen_template
    return _apply_qwen_template(spec_prompt + BASE_REQUIREMENTS,
                                system=SYSTEM_PROMPT)


def describe_failed(results):
    """Requisitos NO cumplidos, en lenguaje de requisito (no de fix): cada
    assert fallido traza a un requisito YA escrito en el prompt, asi que
    devolverlo es feedback de verificacion (como un traceback), no leakear
    una respuesta oculta. Es el 'el assert ES el traceback del diseño' del
    plan §4 eje-3."""
    lines = []
    for r in results:
        if r["ok"]:
            continue
        t = r["type"]
        if t == "element":
            lines.append(f"- Falta el/los elemento(s) que matcheen '{r['sel']}' "
                         f"(requerido: {r.get('min', 1)}+).")
        elif t == "text":
            lines.append(f"- Un '{r['sel']}' debe contener el texto "
                         f"'{r['contains']}'.")
        elif t == "css_rule":
            sel = r.get("sel") or "(alguna regla)"
            val = ("/".join(r["val"]) if isinstance(r.get("val"), list)
                   else r.get("val", ""))
            lines.append(f"- Falta una regla CSS para '{sel}' con "
                         f"'{r['prop']}{': ' + val if val else ''}'.")
        elif t == "css_media":
            lines.append(f"- Falta una @media query que contenga "
                         f"'{r.get('contains', '')}'.")
        elif t == "labels":
            lines.append("- Todo input visible necesita un <label> asociado "
                         "(for/id) o aria-label.")
        elif t == "heading_order":
            lines.append("- Debe haber exactamente un <h1> y no saltar niveles "
                         "de heading.")
        elif t == "img_alt":
            lines.append("- Toda <img> necesita un atributo alt descriptivo.")
        elif t == "no_inline_styles":
            lines.append("- No uses atributos style= inline; todo el CSS en el "
                         "<style> del <head>.")
        elif t in ("doc_basics", "lang_attr", "meta_viewport", "single_file"):
            lines.append(f"- Incumplido: {r['detail'][:80]}")
    return "\n".join(lines)


DESIGN_REPAIR_SYSTEM = ("You are an expert web designer fixing a page to meet "
                        "ALL stated requirements. Reply with ONLY the complete "
                        "corrected single-file HTML document. No explanations.")


def build_repair_prompt(spec_prompt, prev_html, failed_text):
    from node.inference_pipeline import _apply_qwen_template
    msg = (spec_prompt + BASE_REQUIREMENTS
           + "\n\nYour previous page was:\n```html\n" + prev_html[:6000]
           + "\n```\n\nIt did NOT satisfy these requirements:\n" + failed_text
           + "\n\nReply with the COMPLETE corrected HTML document that fixes "
             "these while keeping everything that already worked.")
    return _apply_qwen_template(msg, system=DESIGN_REPAIR_SYSTEM)


def run_benchmark(specs, label, max_tokens=DEFAULT_MAX_TOKENS, seed=None,
                  repair=False):
    from cognia_v3.eval.benchmark_code import make_backend
    backend, gguf_name = make_backend()
    if backend is None:
        print("ERROR: no llama backend available")
        sys.exit(1)
    print(f"[bench_design] backend OK, model={gguf_name}, specs={len(specs)}, "
          f"max_tokens={max_tokens}, seed={seed}, repair={repair}", flush=True)

    by_spec = []
    total_pass = total_asserts = 0
    n_repaired = 0
    for i, spec in enumerate(specs, 1):
        asserts = full_asserts(spec)
        print(f"[{i}/{len(specs)}] {spec['id']} ({spec['title']}) "
              f"generating...", flush=True)
        t0 = time.perf_counter()
        # cache_prompt=False: mismo protocolo determinista que benchmark_code
        response = backend.generate(build_prompt(spec["prompt"]),
                                    max_tokens=max_tokens,
                                    temperature=BASE_TEMPERATURE, seed=seed,
                                    cache_prompt=False) or ""
        gen_s = time.perf_counter() - t0
        tokens = backend.last_tokens_predicted or 0
        html_doc = extract_html(response)
        results = check_page(html_doc, asserts)
        n_ok = sum(1 for r in results if r["ok"])
        did_repair = False
        # Repair dirigido por assert fallido (v1, plan §4 eje-3): si faltan
        # requisitos, UN reintento con los requisitos incumplidos como feedback.
        # Se adopta solo si mejora el conteo de asserts (nunca empeora).
        if repair and n_ok < len(results):
            failed_text = describe_failed(results)
            t1 = time.perf_counter()
            retry = backend.generate(
                build_repair_prompt(spec["prompt"], html_doc, failed_text),
                max_tokens=max_tokens, temperature=BASE_TEMPERATURE,
                seed=seed, cache_prompt=False) or ""
            gen_s += time.perf_counter() - t1
            tokens += backend.last_tokens_predicted or 0
            retry_html = extract_html(retry)
            retry_results = check_page(retry_html, asserts)
            retry_ok = sum(1 for r in retry_results if r["ok"])
            if retry_ok > n_ok:
                response, html_doc = retry, retry_html
                results, n_ok = retry_results, retry_ok
                did_repair = True
                n_repaired += 1
        total_pass += n_ok
        total_asserts += len(results)
        print(f"    -> {n_ok}/{len(results)} asserts"
              f"{' [repaired]' if did_repair else ''} ({gen_s:.0f}s)", flush=True)
        for r in results:
            if not r["ok"]:
                print(f"       FAIL {r['type']}"
                      f"{' ' + r.get('sel', '') if r.get('sel') else ''}: "
                      f"{r['detail'][:90]}", flush=True)
        by_spec.append({
            "id": spec["id"], "title": spec["title"],
            "asserts_passed": n_ok, "asserts_total": len(results),
            "repaired": did_repair,
            "failed": [{k: v for k, v in r.items() if k != "ok"}
                       for r in results if not r["ok"]],
            "gen_seconds": round(gen_s, 2), "tokens_predicted": tokens,
            "response": response, "extracted_html": html_doc,
        })

    score = total_pass / total_asserts if total_asserts else 0.0
    output = {
        "label": label,
        "timestamp": datetime.datetime.now().isoformat(),
        "model": gguf_name,
        "max_tokens": max_tokens,
        "temperature": BASE_TEMPERATURE,
        "seed": seed,
        "n_specs": len(specs),
        "repair": repair,
        "n_repaired": n_repaired,
        "asserts_passed": total_pass,
        "asserts_total": total_asserts,
        "score": round(score, 4),
        "by_spec": by_spec,
    }
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_path = EVAL_DIR / f"results_design_{label}_{ts}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\n[bench_design] {label}: {total_pass}/{total_asserts} asserts "
          f"= {score:.1%}  -> {out_path.name}", flush=True)
    return output


def _safe_stdout():
    """Windows cp1252: evita que un print() de texto no-ASCII crashee el run
    (el JSON se escribe tras el loop). Ver bench_bfcl_slice._safe_stdout."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _safe_stdout()
    ap = argparse.ArgumentParser(description="Cognia design benchmark (eje 3)")
    ap.add_argument("--check-only", action="store_true",
                    help="self-test del checker + validacion de specs, sin modelo")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--label", default="design")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--repair", action="store_true",
                    help="brazo v1: UN reintento por spec con los requisitos "
                         "incumplidos como feedback (el assert = traceback del "
                         "diseño); se adopta solo si mejora el conteo")
    args = ap.parse_args()

    errors = validate_specs()
    if errors:
        print("SPECS INVALIDAS:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    n_asserts = sum(len(full_asserts(s)) for s in SPECS)
    print(f"[bench_design] {len(SPECS)} specs validas, {n_asserts} asserts")

    if args.check_only:
        n_ok, n_total, fails = run_selftest()
        print(f"[selftest] {n_ok}/{n_total} casos del checker OK")
        for f in fails:
            print("  FAIL", f)
        sys.exit(0 if not fails else 1)

    specs = SPECS[:args.limit] if args.limit else SPECS
    run_benchmark(specs, args.label, max_tokens=args.max_tokens,
                  seed=args.seed, repair=args.repair)


if __name__ == "__main__":
    main()
