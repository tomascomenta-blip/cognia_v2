"""
cognia_v3/training/tooluse/tasks_v2.py
=======================================
Banco PROGRAMÁTICO de tareas de TRAIN para escalar el dataset ACCION
(TEORIA Parte 4 §4.2 D2: 42 → ~150 tareas; multi-paso 0% accept es el techo
a romper, predicción E3: 0→≥40%).

En vez de ~100 dicts a mano: FAMILIAS parametrizadas × SUPERFICIES únicas
(nombres/valores/palabras). Cada tarea sale con:
  - prompt principal + PARÁFRASIS (diversidad léxica pre-registrada en §4.2:
    el generador de trayectorias es determinista, la variación va en el texto)
  - expert_steps (la secuencia correcta, ejecutable contra las tools reales)
  - verify (postcondición)

Higiene anti-contaminación:
  - superficies_prohibidas(): filenames/palabras/valores de la suite congelada
    G2A (cognia_v3/eval/suites/g2_accion_tasks.py) — el banco de train NO
    puede usarlos; check_superficies() falla si colisionan (test de regresión).
  - el fraseo de las plantillas difiere del de la suite (ver SPEC_SUITES.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path


# ── helpers de verificación (mismos patrones que tasks.py) ────────────────

def _read(ws: Path, name: str) -> str:
    p = ws / name
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _lines(text: str) -> list:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _has(t: str, needle: str) -> bool:
    return needle.lower() in t.lower()


def _json_load(ws: Path, name: str):
    try:
        return json.loads(_read(ws, name))
    except Exception:
        return None


def _py_ok(ws: Path, name: str) -> bool:
    import ast
    src = _read(ws, name)
    if not src:
        return False
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def _calc_has(t: str, value) -> bool:
    return bool(re.search(rf"=\s*{re.escape(str(value))}(?:\.0+)?\b", t))


# ── fábricas de familias ──────────────────────────────────────────────────

def fam_write(fid, fname, contenido, frases):
    return {
        "id": fid, "familia": "write",
        "prompts": [f.format(f=fname, c=contenido) for f in frases],
        "expert_steps": [("escribir_archivo", f"{fname} | {contenido}")],
        "verify": (lambda ws, t, a, _f=fname, _c=contenido:
                   _read(ws, _f).strip().lower() == _c.lower()),
    }


def fam_write_ml(fid, fname, lineas, frases):
    cont = "\n".join(lineas)
    lista = ", ".join(lineas)
    return {
        "id": fid, "familia": "write_ml",
        "prompts": [f.format(f=fname, lista=lista, n=len(lineas)) for f in frases],
        "expert_steps": [("escribir_archivo", f"{fname} | {cont}")],
        "verify": (lambda ws, t, a, _f=fname, _l=lineas:
                   [x.lower() for x in _lines(_read(ws, _f))] == [x.lower() for x in _l]),
    }


def fam_append_count(fid, fname, base, appends, frases):
    n = 1 + len(appends)
    steps = [("escribir_archivo", f"{fname} | {base}")]
    steps += [("apendar_archivo", f"{fname} | {x}") for x in appends]
    steps += [("contar_lineas", fname)]
    return {
        "id": fid, "familia": "append_count",
        "prompts": [f.format(f=fname, base=base, apps=", despues ".join(f"'{x}'" for x in appends), n=n)
                    for f in frases],
        "expert_steps": steps,
        "verify": (lambda ws, t, a, _f=fname, _n=n:
                   len(_lines(_read(ws, _f))) == _n and _has(t, f"{_n} lineas")),
    }


def fam_read_confirm(fid, fname, contenido, frases):
    return {
        "id": fid, "familia": "read_confirm",
        "prompts": [f.format(f=fname, c=contenido) for f in frases],
        "expert_steps": [("escribir_archivo", f"{fname} | {contenido}"),
                         ("leer_archivo", fname)],
        "verify": (lambda ws, t, a, _f=fname, _c=contenido:
                   _c in _read(ws, _f) and _has(t, _c)),
    }


def fam_copy(fid, origen, contenido, destinos, frases):
    steps = [("escribir_archivo", f"{origen} | {contenido}")]
    steps += [("copiar_archivo", f"{origen} | {d}") for d in destinos]
    return {
        "id": fid, "familia": "copy",
        "prompts": [f.format(o=origen, c=contenido, d=" y despues a ".join(destinos))
                    for f in frases],
        "expert_steps": steps,
        "verify": (lambda ws, t, a, _c=contenido, _ds=destinos:
                   all(_read(ws, d).strip().lower() == _c.lower() for d in _ds)),
    }


def fam_json(fid, fname, obj, descripcion, verifica, frases):
    return {
        "id": fid, "familia": "json",
        "prompts": [f.format(f=fname, desc=descripcion) for f in frases],
        "expert_steps": [("escribir_archivo", f"{fname} | {json.dumps(obj, ensure_ascii=False)}"),
                         ("json_validar", fname)],
        "verify": (lambda ws, t, a, _f=fname, _v=verifica:
                   _v(_json_load(ws, _f)) and _has(t, "json valido")),
    }


def fam_py_func(fid, fname, firma, cuerpo, defname, frases):
    src = f"def {firma}:\n    {cuerpo}"
    return {
        "id": fid, "familia": "py_func",
        "prompts": [f.format(f=fname, firma=firma, cuerpo=cuerpo) for f in frases],
        "expert_steps": [("escribir_archivo", f"{fname} | {src}"),
                         ("py_validar", fname)],
        "verify": (lambda ws, t, a, _f=fname, _d=defname:
                   _py_ok(ws, _f) and f"def {_d}" in _read(ws, _f) and _has(t, "sintaxis ok")),
    }


def fam_py_run(fid, fname, expr, resultado, frases):
    return {
        "id": fid, "familia": "py_run",
        "prompts": [f.format(f=fname, expr=expr) for f in frases],
        "expert_steps": [("escribir_archivo", f"{fname} | print({expr})"),
                         ("py_validar", fname),
                         ("ejecutar", f"__PYTHON__ {fname}")],
        "verify": (lambda ws, t, a, _f=fname, _r=resultado:
                   _py_ok(ws, _f) and _has(t, str(_r))),
    }


def fam_calc(fid, expr_humano, expr_tool, resultado, frases):
    return {
        "id": fid, "familia": "calc",
        "prompts": [f.format(e=expr_humano) for f in frases],
        "expert_steps": [("calcular", expr_tool)],
        "verify": (lambda ws, t, a, _r=resultado: _calc_has(t, _r)),
        "answer": str(resultado),
    }


def fam_calc_save(fid, expr_humano, expr_tool, resultado, fname, frases):
    return {
        "id": fid, "familia": "calc_save",
        "prompts": [f.format(e=expr_humano, f=fname) for f in frases],
        "expert_steps": [("calcular", expr_tool),
                         ("escribir_archivo", f"{fname} | {resultado}")],
        "verify": (lambda ws, t, a, _f=fname, _r=resultado: str(_r) in _read(ws, _f)),
    }


def fam_search(fid, fname, relleno, palabra, frases):
    return {
        "id": fid, "familia": "search",
        "prompts": [f.format(f=fname, p=palabra) for f in frases],
        "expert_steps": [("escribir_archivo", f"{fname} | {relleno} {palabra} {relleno}"),
                         ("buscar", palabra)],
        "verify": (lambda ws, t, a, _f=fname, _p=palabra:
                   _p.lower() in _read(ws, _f).lower() and _has(t, _p)
                   and not _has(t, "sin resultados")),
    }


def fam_listar(fid, archivos, frases):
    steps = [("escribir_archivo", f"{f} | x") for f in archivos]
    steps += [("listar", ".")]
    return {
        "id": fid, "familia": "listar",
        "prompts": [f.format(fs=", ".join(archivos), n=len(archivos)) for f in frases],
        "expert_steps": steps,
        "verify": (lambda ws, t, a, _fs=archivos:
                   all((ws / f).is_file() for f in _fs) and _has(t, "resultado listar")),
    }


def fam_arbol(fid, subruta, frases):
    return {
        "id": fid, "familia": "arbol",
        "prompts": [f.format(f=subruta) for f in frases],
        "expert_steps": [("escribir_archivo", f"{subruta} | x"),
                         ("arbol", ".")],
        "verify": (lambda ws, t, a, _f=subruta:
                   (ws / _f).is_file() and _has(t, "resultado arbol")),
    }


def fam_anotar(fid, pares, frases):
    steps = [("anotar", f"{k} | {v}") for k, v in pares]
    steps += [("notas", "")]
    kv = " y ".join(f"'{k}' con '{v}'" for k, v in pares)
    return {
        "id": fid, "familia": "anotar",
        "prompts": [f.format(kv=kv) for f in frases],
        "expert_steps": steps,
        "verify": (lambda ws, t, a, _ps=pares:
                   all(f"{k}: {v}".lower() in t.lower() for k, v in _ps)),
    }


def fam_kg(fid, hechos, sujeto, objeto_clave, frases):
    steps = [("kg_agregar", f"{s} | {r} | {o}") for s, r, o in hechos]
    steps += [("kg_buscar", sujeto)]
    hh = " y ".join(f"{s} {r} {o}" for s, r, o in hechos)
    return {
        "id": fid, "familia": "kg", "needs_kg": True,
        "prompts": [f.format(hechos=hh, s=sujeto) for f in frases],
        "expert_steps": steps,
        "verify": (lambda ws, t, a, _o=objeto_clave:
                   _has(t, _o) and not _has(t, "sin hechos")),
    }


def fam_shell(fid, token, frases):
    return {
        "id": fid, "familia": "shell",
        "prompts": [f.format(tok=token) for f in frases],
        "expert_steps": [("ejecutar", f"echo {token}")],
        "verify": (lambda ws, t, a, _tok=token:
                   bool(re.search(rf"resultado ejecutar:\s*[^\n]*{re.escape(_tok)}", t, re.IGNORECASE))),
    }


# ── frases por familia (paráfrasis; fraseo ≠ suite G2A) ───────────────────

FR_WRITE = [
    "Necesito un archivo {f} cuyo contenido exacto sea: {c}",
    "Genera {f} y adentro pone solamente: {c}",
    "Arma el archivo {f} con este texto: {c}",
]
FR_WRITE_ML = [
    "Necesito {f} con {n} lineas, en este orden: {lista} (una por renglon).",
    "Genera {f}; su contenido son estas {n} lineas: {lista}.",
]
FR_APPEND_COUNT = [
    "Arma {f} con la linea '{base}', sumale al final {apps}, y termina midiendo cuantas lineas quedaron.",
    "Crea {f} que arranque con '{base}'; agregale {apps} al final y despues medi el total de lineas.",
]
FR_READ_CONFIRM = [
    "Genera {f} con el texto {c} y abrilo despues para verificar que quedo bien.",
    "Necesito {f} conteniendo {c}; despues mostrame su contenido para chequearlo.",
]
FR_COPY = [
    "Arma {o} con el texto {c} y duplicalo a {d}.",
    "Genera {o} (contenido: {c}); despues hace una copia hacia {d}.",
]
FR_JSON = [
    "Necesito {f} con JSON bien formado: {desc}. Chequea que sea valido al final.",
    "Genera {f} conteniendo {desc} en JSON correcto, y verificalo.",
]
FR_PY_FUNC = [
    "Programa {f} con una funcion {firma} cuyo cuerpo haga: {cuerpo}. Chequea la sintaxis al final.",
    "Necesito {f} definiendo {firma} ({cuerpo}); despues verifica que compile.",
]
FR_PY_RUN = [
    "Programa {f} para que muestre {expr}; chequea la sintaxis y corre el script con python {f}.",
    "Genera {f} que haga print de {expr}, verifica que compile y ejecutalo: python {f}.",
]
FR_CALC = [
    "Resolvé {e} con la calculadora y da el numero.",
    "Necesito el resultado de {e}; usa la herramienta de calculo.",
    "Computa {e} y decime cuanto da.",
]
FR_CALC_SAVE = [
    "Computa {e} y deja el resultado numerico dentro de {f}.",
    "Resolvé {e} con la calculadora; el numero va guardado en {f}.",
]
FR_SEARCH = [
    "Arma {f} incluyendo la palabra {p} en su texto; despues rastrea '{p}' en la carpeta actual.",
    "Genera {f} que mencione {p}, y busca esa palabra en el directorio.",
]
FR_LISTAR = [
    "Genera {n} archivos ({fs}) y despues mostra que hay en la carpeta actual.",
    "Arma los archivos {fs}; al final enumera el contenido del directorio.",
]
FR_ARBOL = [
    "Genera {f} (va en una subcarpeta) y despues mostra la estructura de directorios.",
    "Necesito {f} creado; al final dibuja el arbol de la carpeta actual.",
]
FR_ANOTAR = [
    "Apunta en tu memoria de trabajo {kv}; al final revisa lo apuntado.",
    "Memoriza (en notas de trabajo) {kv} y mostra tus apuntes despues.",
]
FR_KG = [
    "Carga en el grafo de conocimiento: {hechos}. Despues consulta el grafo por {s}.",
    "Al grafo de conocimiento sumale {hechos}; luego fijate que dice sobre {s}.",
]
FR_SHELL = [
    "Corre en la shell: echo {tok}",
    "Lanza el comando echo {tok} en la terminal.",
]


# ── banco: superficies únicas (≠ tasks.py train, ≠ suite G2A) ─────────────

TASKS_V2 = [
    # write simple (6)
    fam_write("v2_write_recado", "recado.txt", "llamar al plomero", FR_WRITE),
    fam_write("v2_write_lema", "lema.txt", "hecho es mejor que perfecto", FR_WRITE),
    fam_write("v2_write_pin", "pin.txt", "4482", FR_WRITE),
    fam_write("v2_write_titulo", "titulo.txt", "cronicas del rio", FR_WRITE),
    fam_write("v2_write_sub2", "notas/idea.txt", "prototipo en marcha", FR_WRITE),
    fam_write("v2_write_alias", "alias.txt", "halcon nocturno", FR_WRITE),
    # write multiline (5)
    fam_write_ml("v2_ml_menu", "menu.txt", ["sopa", "guiso", "flan"], FR_WRITE_ML),
    fam_write_ml("v2_ml_equipo", "equipo.txt", ["ana", "bruno", "carla", "dario"], FR_WRITE_ML),
    fam_write_ml("v2_ml_rutina", "rutina.txt", ["correr", "estirar"], FR_WRITE_ML),
    fam_write_ml("v2_ml_meses", "trimestre.txt", ["enero", "febrero", "marzo"], FR_WRITE_ML),
    fam_write_ml("v2_ml_niveles", "niveles.txt", ["bajo", "medio", "alto", "critico", "maximo"], FR_WRITE_ML),
    # append + count (6)
    fam_append_count("v2_ac_visitas", "visitas.txt", "visita uno", ["visita dos"], FR_APPEND_COUNT),
    fam_append_count("v2_ac_turnos", "turnos.txt", "turno a", ["turno b", "turno c"], FR_APPEND_COUNT),
    fam_append_count("v2_ac_gastos", "gastos.txt", "gasto inicial", ["gasto luz", "gasto agua", "gasto gas"], FR_APPEND_COUNT),
    fam_append_count("v2_ac_hitos", "hitos.txt", "hito alfa", ["hito beta"], FR_APPEND_COUNT),
    fam_append_count("v2_ac_notasclase", "clase.txt", "unidad 1", ["unidad 2", "unidad 3"], FR_APPEND_COUNT),
    fam_append_count("v2_ac_stock", "stock.txt", "caja 10", ["caja 20"], FR_APPEND_COUNT),
    # read confirm (4)
    fam_read_confirm("v2_rc_serie", "serie.txt", "serie_zx_81", FR_READ_CONFIRM),
    fam_read_confirm("v2_rc_folio", "folio.txt", "folio_772", FR_READ_CONFIRM),
    fam_read_confirm("v2_rc_lote", "lote.txt", "lote_norte_3", FR_READ_CONFIRM),
    fam_read_confirm("v2_rc_ticket", "ticket.txt", "ticket_azul_9", FR_READ_CONFIRM),
    # copy (4)
    fam_copy("v2_cp_manual", "manual.txt", "guia rapida", ["manual_v2.txt"], FR_COPY),
    fam_copy("v2_cp_carta", "carta.txt", "estimado equipo", ["carta_final.txt"], FR_COPY),
    fam_copy("v2_cp_doble", "matriz.txt", "patron base", ["espejo1.txt", "espejo2.txt"], FR_COPY),
    fam_copy("v2_cp_borr", "borrador2.txt", "texto preliminar", ["definitivo.txt"], FR_COPY),
    # json (5)
    fam_json("v2_js_puerto", "servidor.json", {"puerto_alt": 3000},
             'la clave "puerto_alt" valiendo 3000',
             lambda d: isinstance(d, dict) and d.get("puerto_alt") == 3000, FR_JSON),
    fam_json("v2_js_lista", "impares.json", [1, 3, 5, 7],
             "una lista con los numeros 1, 3, 5 y 7",
             lambda d: d == [1, 3, 5, 7], FR_JSON),
    fam_json("v2_js_user", "perfil.json", {"usuario": {"nombre": "rio", "nivel": 4}},
             'la clave "usuario" como objeto con "nombre" igual a "rio" y "nivel" igual a 4',
             lambda d: isinstance(d, dict) and d.get("usuario", {}).get("nivel") == 4, FR_JSON),
    fam_json("v2_js_activo", "switches.json", {"modo_noche": True},
             'la clave "modo_noche" valiendo true',
             lambda d: isinstance(d, dict) and d.get("modo_noche") is True, FR_JSON),
    fam_json("v2_js_mixto", "resumen.json", {"items": 12, "listo": False},
             'las claves "items" valiendo 12 y "listo" valiendo false',
             lambda d: isinstance(d, dict) and d.get("items") == 12 and d.get("listo") is False, FR_JSON),
    # py func (4)
    fam_py_func("v2_pf_doble", "duplicar.py", "duplicar(x)", "return x * 2", "duplicar", FR_PY_FUNC),
    fam_py_func("v2_pf_saludo", "bienvenida.py", "bienvenida(nombre)", "return 'hola ' + nombre", "bienvenida", FR_PY_FUNC),
    fam_py_func("v2_pf_signo", "signo.py", "signo(n)", "return 1 if n >= 0 else -1", "signo", FR_PY_FUNC),
    fam_py_func("v2_pf_ultimo", "cola.py", "ultimo(xs)", "return xs[-1]", "ultimo", FR_PY_FUNC),
    # py run (4)
    fam_py_run("v2_pr_area", "area.py", "7 * 12", 84, FR_PY_RUN),
    fam_py_run("v2_pr_cubo", "cubo.py", "4 ** 3", 64, FR_PY_RUN),
    fam_py_run("v2_pr_resto", "resto.py", "97 % 10", 7, FR_PY_RUN),
    fam_py_run("v2_pr_suma", "sumatoria.py", "sum(range(10))", 45, FR_PY_RUN),
    # calc (6)
    fam_calc("v2_ca_mul", "26 por 34", "26 * 34", 884, FR_CALC),
    fam_calc("v2_ca_div", "1440 dividido 16", "1440 / 16", 90, FR_CALC),
    fam_calc("v2_ca_pow", "6 elevado a la 4", "6 ** 4", 1296, FR_CALC),
    fam_calc("v2_ca_mod", "el resto de 777 entre 11", "777 % 11", 7, FR_CALC),
    fam_calc("v2_ca_expr", "(300 / 4) + 25", "(300 / 4) + 25", 100, FR_CALC),
    fam_calc("v2_ca_resta", "2026 menos 1987", "2026 - 1987", 39, FR_CALC),
    # calc + save (4)
    fam_calc_save("v2_cs_iva", "210 por 1.21", "210 * 1.21", "254.1", "con_iva.txt", FR_CALC_SAVE),
    fam_calc_save("v2_cs_mitad", "8642 dividido 2", "8642 / 2", "4321", "mitad.txt", FR_CALC_SAVE),
    fam_calc_save("v2_cs_cuad", "33 por 33", "33 * 33", "1089", "area33.txt", FR_CALC_SAVE),
    fam_calc_save("v2_cs_dias", "365 por 3", "365 * 3", "1095", "trienio.txt", FR_CALC_SAVE),
    # search (4)
    fam_search("v2_se_faro", "bitacora_mar.txt", "avistamiento cerca del", "FARO", FR_SEARCH),
    fam_search("v2_se_cometa", "cielo.txt", "registro del", "COMETA", FR_SEARCH),
    fam_search("v2_se_puma", "fauna.txt", "huellas de", "PUMA", FR_SEARCH),
    fam_search("v2_se_ambar", "minerales.txt", "muestra de", "AMBAR", FR_SEARCH),
    # listar / arbol (4)
    fam_listar("v2_li_tres", ["norte.txt", "sur.txt", "este.txt"], FR_LISTAR),
    fam_listar("v2_li_dos", ["acta1.txt", "acta2.txt"], FR_LISTAR),
    fam_arbol("v2_ar_datos", "datos/crudo.txt", FR_ARBOL),
    fam_arbol("v2_ar_src", "src/main.txt", FR_ARBOL),
    # anotar (4)
    fam_anotar("v2_an_clima", [("clima", "soleado")], FR_ANOTAR),
    fam_anotar("v2_an_doble", [("puerta", "izquierda"), ("piso", "tercero")], FR_ANOTAR),
    fam_anotar("v2_an_ref", [("referencia", "expediente 88")], FR_ANOTAR),
    fam_anotar("v2_an_tema", [("tema", "riego")], FR_ANOTAR),
    # kg (4)
    fam_kg("v2_kg_tango", [("tango", "is_a", "danza")], "tango", "danza", FR_KG),
    fam_kg("v2_kg_ceibo", [("ceibo", "is_a", "arbol"), ("ceibo", "has_property", "flor roja")],
           "ceibo", "arbol", FR_KG),
    fam_kg("v2_kg_ander", [("anden", "part_of", "estacion")], "anden", "estacion", FR_KG),
    fam_kg("v2_kg_cobre", [("cobre", "used_for", "cables")], "cobre", "cables", FR_KG),
    # shell (2)
    fam_shell("v2_sh_eco1", "senal_verde_v2", FR_SHELL),
    fam_shell("v2_sh_eco2", "puente_activo", FR_SHELL),
]


def superficies_prohibidas() -> set:
    """Filenames y palabras clave de la suite congelada G2A: el train NO puede
    usarlas (higiene held-out). Extraídas del banco de la suite, no a mano."""
    import importlib
    mod = importlib.import_module("cognia_v3.eval.suites.g2_accion_tasks")
    fn_re = re.compile(r"\b[\w./-]+\.(?:txt|json|py)\b")
    prohibidas = set()
    for t in mod.TASKS:
        prohibidas |= set(x.lower() for x in fn_re.findall(t["prompt"]))
        for _, args in t["expert_steps"]:
            prohibidas |= set(x.lower() for x in fn_re.findall(args))
    return prohibidas


def check_superficies() -> list:
    """Colisiones train-v2 vs suite G2A (lista vacía = limpio)."""
    proh = superficies_prohibidas()
    fn_re = re.compile(r"\b[\w./-]+\.(?:txt|json|py)\b")
    malas = []
    for t in TASKS_V2:
        usadas = set()
        for p in t["prompts"]:
            usadas |= set(x.lower() for x in fn_re.findall(p))
        for _, args in t["expert_steps"]:
            usadas |= set(x.lower() for x in fn_re.findall(args))
        hit = usadas & proh
        if hit:
            malas.append((t["id"], sorted(hit)))
    return malas


def by_id(task_id: str):
    for t in TASKS_V2:
        if t["id"] == task_id:
            return t
    return None
