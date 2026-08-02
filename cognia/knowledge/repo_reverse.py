# -*- coding: utf-8 -*-
"""Ingeniería inversa de repos: de un repo (local o GitHub) a su especificación.

Idea (gitreverse invertido, mandato 2026-08-01): gitreverse sintetiza un prompt
vago con GitHub API + README + LLM obligatorio. Aquí se invierte cada debilidad:
repos LOCALES sin red ni claves (GitHub vía `git clone --depth 1`, sin API),
análisis PROFUNDO determinista (repo_map con PageRank + code_nav + entry points
+ manifiestos + imports AST), y el LLM solo redacta la sección "Prompt
reconstruido" — la arquitectura/deps/entradas salen del AST y no pueden
alucinarse. Sin LLM SIEMPRE hay especificación heurística no vacía.

Restricción de capa: CERO imports de `shattering` y cero LLM en este módulo.
El refinado llega como callable inyectado (`infer_fn`) desde el wrapper del
agente (cognia/agent/repo_reverse_tool.py), que usa la vía interna `_orch`.
100% testeable sin red y sin modelo.
"""
from __future__ import annotations

import ast
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

from cognia.knowledge.code_graph import (
    _SKIP_DIRS,
    _archivos_py,
    _imports_de,
    _modulo_de,
)
from cognia.knowledge.code_nav import formatear, vecindad
from cognia.knowledge.repo_map import repo_map

_SKIP = set(_SKIP_DIRS) | {"tests", "test", "docs", "examples", ".github",
                           "build", ".venv", ".idea"}
MAX_README = 6000          # corte del README para el análisis
MAX_MUESTRA_LINEAS = 40    # líneas por muestra de código
DEGRADADO = "[DEGRADADO]"  # espejo de shattering.orchestrator.DEGRADADO (56);
                           # literal a propósito para NO importar shattering
                           # desde knowledge/

_URL_GITHUB = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_OWNER_REPO = re.compile(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$")
# línea que es SOLO una URL (p.ej. el asset github.com/user-attachments/...
# que algunos README ponen antes de la primera frase): no es prosa
_SOLO_URL = re.compile(r"^<?(?:https?://|www\.)\S+>?$")


def _saltar_dir(nombre: str) -> bool:
    """Dirs que no aportan señal al análisis (venv*, ocultos, _SKIP)."""
    return (nombre in _SKIP or nombre.startswith(".")
            or nombre.startswith("venv") or nombre.endswith(".egg-info"))


def _parsear_entrada(entrada: str) -> tuple:
    """('local', ruta) si el path existe; ('github', 'owner/repo') si es URL
    github.com u 'owner/repo' (quita .git, rechaza otros hosts).
    ValueError con mensaje explicativo en cualquier otro caso."""
    e = (entrada or "").strip().strip('"').strip("'")
    if not e:
        raise ValueError("entrada vacia: pasa una ruta local o una URL de GitHub")
    p = Path(e)
    if p.is_dir():
        return ("local", e)
    if p.exists():
        # existe pero es un ARCHIVO: sin esto, analizar_repo lanza
        # NotADirectoryError (WinError 267, críptico) que escapa al wrapper
        raise ValueError(
            f"{e!r} es un archivo, no un directorio: pasa la RAIZ del repo "
            f"(p.ej. {p.resolve().parent}).")
    m = _URL_GITHUB.match(e)
    if m:
        return ("github", f"{m.group(1)}/{m.group(2)}")
    if e.startswith(("http://", "https://")) or "github.com" in e:
        raise ValueError(
            f"URL no soportada: {e!r}. Solo repos de github.com "
            f"(https://github.com/owner/repo) o rutas locales existentes.")
    m = _OWNER_REPO.match(e)
    if m:
        return ("github", f"{m.group(1)}/{m.group(2)}")
    raise ValueError(
        f"no existe la ruta local {e!r} y no parece un repo de GitHub "
        f"(owner/repo o https://github.com/owner/repo).")


def _clonar(owner_repo: str, dir_clones: Path) -> tuple:
    """git clone --depth 1 sin API REST (sin rate limit, sin token). Si el
    destino ya existe lo REUSA con aviso visible y borrable (mejora vs la
    cache eterna de gitreverse). Retorna (raiz, aviso)."""
    dir_clones = Path(dir_clones)
    destino = dir_clones / owner_repo.replace("/", "_")
    if destino.is_dir() and any(destino.iterdir()):
        mtime = datetime.datetime.fromtimestamp(
            destino.stat().st_mtime).isoformat(timespec="seconds")
        return (destino, f"clon cacheado del {mtime}; borra {destino} "
                         f"para refrescar")
    dir_clones.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{owner_repo}.git"
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(destino)],
            capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        raise RuntimeError(
            f"no pude clonar {owner_repo}: git no esta instalado. "
            f"Usa una ruta local o instala git.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"no pude clonar {owner_repo}: timeout de 180s. "
            f"Usa una ruta local o revisa la red.")
    if proc.returncode != 0:
        raise RuntimeError(
            f"no pude clonar {owner_repo}: {(proc.stderr or '').strip()[:300]}. "
            f"Usa una ruta local o instala git.")
    return (destino, "")


def detectar_paquetes(raiz: Path, max_paquetes: int = 8) -> tuple:
    """Dirs directos de raiz con __init__.py (paquetes reales); si no hay,
    dirs directos que contengan .py; excluye _SKIP; ordena por nº de .py desc.
    Si tampoco hay subdirs candidatos pero la raiz misma tiene *.py (repo
    plano), la raiz se trata como paquete único: se devuelve "." (para que
    _archivos_py/repo_map caminen la raiz) más los stems de los .py (para que
    _imports_de cuente `import hermano` como interno y no como dep externa).
    Tupla vacía si el repo no tiene Python organizable (no es error)."""
    raiz = Path(raiz)
    candidatos = [d for d in raiz.iterdir()
                  if d.is_dir() and not _saltar_dir(d.name)]
    paquetes = [d for d in candidatos if (d / "__init__.py").is_file()]
    if not paquetes:
        paquetes = [d for d in candidatos if any(d.rglob("*.py"))]
    if not paquetes:
        stems = sorted(p.stem for p in raiz.glob("*.py"))
        if stems:
            return (".",) + tuple(stems)

    def n_py(d):
        return sum(1 for _ in d.rglob("*.py"))
    paquetes.sort(key=lambda d: (-n_py(d), d.name))
    return tuple(d.name for d in paquetes[:max_paquetes])


def _leer(path: Path) -> str:
    # utf-8-sig: si el archivo trae BOM (U+FEFF), lo quita — con utf-8 pelado
    # el BOM llega a ast.parse como "invalid non-printable character" y el
    # módulo se cae del grafo; sin BOM se comporta idéntico a utf-8.
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _tiene_guard_main(tree) -> bool:
    """AST: hay un `if __name__ == "__main__":` a nivel de módulo."""
    for n in tree.body:
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            t = n.test
            if (isinstance(t.left, ast.Name) and t.left.id == "__name__"
                    and t.comparators
                    and isinstance(t.comparators[0], ast.Constant)
                    and t.comparators[0].value == "__main__"):
                return True
    return False


def _manifiestos(raiz: Path, avisos: list) -> dict:
    """Parsea pyproject.toml / package.json / requirements.txt; cada fallo
    suma a avisos, jamás silencio."""
    out = {}
    pp = raiz / "pyproject.toml"
    if pp.is_file():
        try:
            import tomllib
            out["pyproject"] = tomllib.loads(_leer(pp))
        except Exception as exc:
            avisos.append(f"pyproject.toml ilegible: {exc}")
    pj = raiz / "package.json"
    if pj.is_file():
        try:
            out["package_json"] = json.loads(_leer(pj))
        except Exception as exc:
            avisos.append(f"package.json ilegible: {exc}")
    req = raiz / "requirements.txt"
    if req.is_file():
        try:
            out["requirements"] = [
                ln.strip() for ln in _leer(req).splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        except Exception as exc:
            avisos.append(f"requirements.txt ilegible: {exc}")
    return out


def _deps_declaradas(manifiestos: dict) -> list:
    """Nombres de dependencias declaradas en los manifiestos."""
    deps = []
    proy = manifiestos.get("pyproject", {}).get("project", {})
    for d in proy.get("dependencies", []) or []:
        deps.append(re.split(r"[<>=!~\[; ]", d, 1)[0].strip())
    pj = manifiestos.get("package_json", {})
    deps.extend((pj.get("dependencies") or {}).keys())
    for r in manifiestos.get("requirements", []) or []:
        deps.append(re.split(r"[<>=!~\[; ]", r, 1)[0].strip())
    return sorted({d for d in deps if d})


def _entry_points(raiz: Path, manifiestos: dict, guards: list,
                  mains: list) -> list:
    """Puntos de entrada evidenciados: __main__.py, guards AST, scripts de
    manifiestos, main/app/cli.py en raiz, Dockerfile CMD/ENTRYPOINT."""
    eps = []
    for mod in mains:
        eps.append(f"python -m {mod}  (__main__.py)")
    for mod in guards:
        eps.append(f"python -m {mod}  (guard __main__)")
    scripts = manifiestos.get("pyproject", {}).get("project", {}).get(
        "scripts", {}) or {}
    for nombre, target in scripts.items():
        eps.append(f"console_script: {nombre} = {target}")
    pj = manifiestos.get("package_json", {})
    for nombre, cmd in (pj.get("scripts") or {}).items():
        eps.append(f"npm run {nombre}: {cmd}")
    if pj.get("main"):
        eps.append(f"package.json main: {pj['main']}")
    if pj.get("bin"):
        eps.append(f"package.json bin: {pj['bin']}")
    for f in ("main.py", "app.py", "cli.py"):
        if (raiz / f).is_file():
            eps.append(f"python {f}  (script en raiz)")
    dk = raiz / "Dockerfile"
    if dk.is_file():
        try:
            for ln in _leer(dk).splitlines():
                s = ln.strip()
                if s.upper().startswith(("CMD ", "ENTRYPOINT ")):
                    eps.append(f"Dockerfile: {s[:120]}")
        except OSError:
            pass
    # dedupe estable
    vistos, out = set(), []
    for e in eps:
        if e not in vistos:
            vistos.add(e)
            out.append(e)
    return out


def analizar_repo(raiz: Path, max_modulos: int = 12,
                  max_muestras: int = 4) -> dict:
    """Análisis determinista del repo, sin LLM ni red. Ver claves en docstring
    del módulo / la orden de trabajo. Todas las lecturas utf-8 + replace."""
    raiz = Path(raiz).resolve()
    avisos = []

    # inventario de lenguajes por extensión (os.walk saltando _SKIP y venv*)
    lenguajes, n_archivos = {}, 0
    import os
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = [d for d in dirnames if not _saltar_dir(d)]
        for f in filenames:
            n_archivos += 1
            ext = Path(f).suffix.lower()
            if ext:
                lenguajes[ext] = lenguajes.get(ext, 0) + 1
    lenguajes = dict(sorted(lenguajes.items(),
                            key=lambda kv: -kv[1])[:6])
    n_py = lenguajes.get(".py", 0)

    # README
    readme = ""
    for nombre in ("README.md", "README.rst", "README.txt", "readme.md",
                   "README"):
        p = raiz / nombre
        if p.is_file():
            readme = _leer(p)[:MAX_README]
            break
    if not readme:
        avisos.append("sin README: el objetivo se infiere solo del inventario")

    manifiestos = _manifiestos(raiz, avisos)
    paquetes = detectar_paquetes(raiz)

    # pasada AST única sobre los paquetes: guards main, __main__.py, imports
    # externos (top-level fuera de paquetes y de la stdlib de Python 3.12)
    guards, mains, imports_ext = [], [], set()
    if paquetes:
        stdlib = sys.stdlib_module_names
        for path in _archivos_py(raiz, paquetes):
            try:
                tree = ast.parse(_leer(path))
            except SyntaxError as exc:
                avisos.append(f"sintaxis invalida en {path.name}: {exc.msg}")
                continue
            mod = _modulo_de(path, raiz)
            if path.name == "__main__.py":
                mains.append(mod.rsplit(".", 1)[0] if "." in mod else mod)
            elif _tiene_guard_main(tree):
                guards.append(mod)
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        imports_ext.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    imports_ext.add(n.module.split(".")[0])
        imports_ext = {m for m in imports_ext
                       if m not in paquetes and m not in stdlib
                       and not m.startswith("_")}
    else:
        avisos.append("sin paquetes Python organizables: sin grafo AST")

    declaradas = _deps_declaradas(manifiestos)
    deps_externas = sorted(
        {f"{d} (declarada)" for d in declaradas}
        | {f"{m} (importada)" for m in sorted(imports_ext)})

    entry_points = _entry_points(raiz, manifiestos, sorted(guards),
                                 sorted(set(mains)))

    # mapa PageRank + vecindades de los 3 módulos top + muestras de código
    mapa, vecindades, muestras = None, "", []
    if paquetes:
        mapa = repo_map(raiz=raiz, paquetes=paquetes, max_modulos=max_modulos)
        if not mapa["modulos"]:
            avisos.append("repo_map no encontro modulos parseables")
        partes = []
        for mod in mapa["modulos"][:3]:
            try:
                partes.append(formatear(
                    vecindad(mod, raiz=raiz, paquetes=paquetes)))
            except Exception as exc:
                avisos.append(f"vecindad de {mod} fallo: {exc}")
        vecindades = "\n".join(partes)
        for mod in mapa["modulos"][:max_muestras]:
            rel = mod.replace(".", "/")
            for cand in (raiz / (rel + ".py"), raiz / rel / "__init__.py"):
                if cand.is_file():
                    texto = "\n".join(
                        _leer(cand).splitlines()[:MAX_MUESTRA_LINEAS])
                    muestras.append((str(cand.relative_to(raiz)), texto))
                    break

    return {
        "nombre": raiz.name,
        "raiz": str(raiz),
        "paquetes": paquetes,
        "n_archivos": n_archivos,
        "n_py": n_py,
        "lenguajes": lenguajes,
        "readme": readme,
        "manifiestos": manifiestos,
        "entry_points": entry_points,
        "deps_externas": deps_externas,
        "mapa": mapa,
        "vecindades": vecindades,
        "muestras": muestras,
        "avisos": avisos,
    }


def _objetivo_de(analisis: dict) -> str:
    """Objetivo determinista: primeras frases del README + description de
    manifiestos. Nunca vacío (fallback por inventario)."""
    partes = []
    readme = (analisis.get("readme") or "").strip()
    if readme:
        # primeras líneas de prosa (saltando títulos, badges, vacías y
        # líneas que son solo una URL, p.ej. assets al tope del README)
        prosa = [ln.strip() for ln in readme.splitlines()
                 if ln.strip() and not ln.strip().startswith(("#", "[!", "<"))
                 and not _SOLO_URL.match(ln.strip())]
        if prosa:
            partes.append(" ".join(prosa[:4])[:600])
    desc = (analisis.get("manifiestos", {}).get("pyproject", {})
            .get("project", {}).get("description"))
    if desc:
        partes.append(f"(pyproject) {desc}")
    desc_js = analisis.get("manifiestos", {}).get("package_json",
                                                  {}).get("description")
    if desc_js:
        partes.append(f"(package.json) {desc_js}")
    if not partes:
        lens = ", ".join(f"{k}:{v}" for k, v in
                         analisis.get("lenguajes", {}).items()) or "sin codigo"
        partes.append(
            f"Proyecto {analisis['nombre']}: {analisis['n_archivos']} "
            f"archivos, lenguajes {lens}; sin README ni metadatos, "
            f"especificacion minima por inventario.")
    return "\n".join(partes)


def _features_de(analisis: dict) -> list:
    """Features EVIDENCIADAS: encabezados del README, scripts, módulos top."""
    feats = []
    for ln in (analisis.get("readme") or "").splitlines():
        s = ln.strip()
        if s.startswith("##") and len(s) > 3:
            feats.append(s.lstrip("#").strip())
    for e in analisis.get("entry_points", []):
        if e.startswith(("console_script:", "npm run ")):
            feats.append(e)
    mapa = analisis.get("mapa")
    if mapa and mapa.get("modulos"):
        feats.append("modulos nucleo: " + ", ".join(mapa["modulos"][:6]))
    return feats[:12]


def _render(analisis: dict, modo_label: str, prompt_texto: str,
            aviso_modo: str = "") -> str:
    """Render único de la especificación (ambos modos comparten esqueleto:
    todo determinista salvo la sección 'Prompt reconstruido')."""
    a = analisis
    lens = ", ".join(f"{k} ({v})" for k, v in a.get("lenguajes", {}).items())
    lineas = [
        f"# Especificación reconstruida: {a['nombre']}",
        f"_Origen: {a.get('origen_desc', a['raiz'])}. Modo: {modo_label}._",
        "",
        "## Objetivo del proyecto",
        _objetivo_de(a),
        "",
        "## Alcance funcional",
    ]
    feats = _features_de(a)
    if feats:
        lineas.extend(f"- {f}" for f in feats)
    else:
        lineas.append("- (sin features evidenciadas mas alla del inventario)")
    lineas += ["", "## Stack y dependencias",
               f"- Lenguajes por conteo de extensiones: {lens or '(sin archivos con extension)'}"]
    deps = a.get("deps_externas", [])
    if deps:
        lineas.extend(f"- {d}" for d in deps[:20])
    else:
        lineas.append("- (sin dependencias detectadas)")
    lineas += ["", "## Arquitectura observada"]
    mapa = a.get("mapa")
    if mapa and mapa.get("texto"):
        lineas.append(f"Mapa de {mapa['n_modulos']} modulos (orden PageRank, "
                      f"modulo [usado_por=N] + simbolos):")
        lineas.append(mapa["texto"])
        if a.get("vecindades"):
            lineas += ["", "Vecindades de los modulos nucleo:",
                       a["vecindades"]]
    else:
        lineas.append("(repo sin Python organizable: sin grafo AST; "
                      "inventario de lenguajes arriba)")
    lineas += ["", "## Puntos de entrada"]
    eps = a.get("entry_points", [])
    if eps:
        lineas.extend(f"- {e}" for e in eps)
    else:
        lineas.append("- (ninguno detectado)")
    lineas += ["", "## Prompt reconstruido (estilo gitreverse)", prompt_texto,
               "", "## Límites de esta especificación"]
    limites = list(a.get("avisos", []))
    if aviso_modo:
        limites.append(aviso_modo)
    limites.append(
        "Metodo: analisis estatico (AST + manifiestos + README truncado a "
        f"{MAX_README} chars); no se ejecuto el codigo, el comportamiento en "
        "runtime no esta verificado.")
    lineas.extend(f"- {l}" for l in limites)
    return "\n".join(lineas)


def spec_heuristica(analisis: dict, aviso_modo: str = "") -> str:
    """Especificación completa SIN LLM. GARANTÍA anti-vacío por construcción:
    siempre hay Objetivo (aunque sea por inventario) y Límites."""
    a = analisis
    objetivo = _objetivo_de(a).splitlines()[0][:200]
    feats = [f for f in _features_de(a) if not f.startswith("modulos nucleo")]
    deps = [d.split(" ")[0] for d in a.get("deps_externas", [])][:3]
    lens = list(a.get("lenguajes", {}).keys())
    stack = (lens[0].lstrip(".") if lens else "desconocido")
    plantilla = (f"[plantilla heurística — sin LLM]\n"
                 f"Construye {a['nombre']}: {objetivo} "
                 + (f"Debe incluir: {'; '.join(feats[:5])}. " if feats else "")
                 + f"Stack: {stack}"
                 + (f" + {', '.join(deps)}." if deps else "."))
    modo = ("HEURÍSTICO (backend LLM apagado)" if aviso_modo
            else "HEURÍSTICO SIN LLM")
    return _render(analisis, modo, plantilla, aviso_modo)


SYSTEM_PROMPT_REVERSE = """Eres un ingeniero inverso de software. Recibes el ANALISIS REAL de un repositorio:
modulos nucleo rankeados por importancia, simbolos que definen, dependencias,
puntos de entrada, extracto del README y muestras de codigo. Tu tarea: escribir
el mensaje que un usuario habria escrito a un agente de codigo (Cursor, Claude
Code, Codex) para construir ESTE proyecto desde cero de una sola vez.

Reglas:
- Escribe en el idioma del README; si no hay README, en espanol.
- 120 a 220 palabras, un solo bloque de texto, primera persona, tono
  conversacional ("Quiero...", "Construye...", "Necesito...").
- Centrado en el RESULTADO: que hace el proyecto, para quien, y las 3 a 6
  capacidades concretas que el analisis evidencia. Nunca rutas de archivos ni
  nombres de modulos internos.
- Menciona el stack SOLO si el analisis lo evidencia (lenguaje dominante o un
  framework presente en las dependencias). No inventes features, cifras ni
  tecnologias que no esten en el analisis recibido.
- Si el analisis es pobre (sin README, pocos modulos), quedate deliberadamente
  vago y hazlo sonar natural ("algo simple que...").
- Responde SOLO con el mensaje. Sin titulo, sin comillas, sin listas, sin
  explicacion antes ni despues.
"""


def construir_prompt_llm(analisis: dict) -> tuple:
    """(system, user) para el refinado. user <= 6000 chars (ventana chica)."""
    a = analisis
    mapa = a.get("mapa") or {}
    partes = [
        f"# Analisis del repo: {a['nombre']}",
        f"Lenguajes: {', '.join(f'{k}:{v}' for k, v in a['lenguajes'].items())}",
        f"Objetivo tentativo (README/manifiestos):\n{_objetivo_de(a)[:1500]}",
        f"Puntos de entrada:\n" + "\n".join(a['entry_points'][:8]),
        f"Dependencias externas: {', '.join(d.split(' ')[0] for d in a['deps_externas'][:15])}",
    ]
    if mapa.get("texto"):
        partes.append(f"Modulos nucleo (PageRank):\n{mapa['texto'][:1500]}")
    if a.get("vecindades"):
        partes.append(f"Vecindades:\n{a['vecindades'][:800]}")
    for ruta, texto in a.get("muestras", [])[:2]:
        partes.append(f"Muestra {ruta}:\n{texto[:600]}")
    user = "\n\n".join(partes)[:6000]
    return (SYSTEM_PROMPT_REVERSE, user)


def repo_a_prompt(entrada: str, infer_fn=None, max_modulos: int = 12,
                  dir_clones=None) -> dict:
    """Orquestador puro. infer_fn: callable(system, user) -> str, o None
    (modo sin LLM pedido explícitamente). Retorna {'texto' (NUNCA vacío),
    'modo': 'llm'|'heuristico'|'heuristico_degradado', 'aviso', 'analisis'}.
    ValueError/RuntimeError suben al caller (el wrapper los mapea)."""
    tipo, valor = _parsear_entrada(entrada)
    aviso = ""
    if tipo == "github":
        base = Path(dir_clones) if dir_clones else Path(".repo_reverse")
        raiz, aviso = _clonar(valor, base)
        origen_desc = f"clon superficial de {valor}"
    else:
        raiz = Path(valor)
        origen_desc = f"ruta local {raiz}"

    analisis = analizar_repo(raiz, max_modulos=max_modulos)
    analisis["origen_desc"] = origen_desc
    if aviso:
        analisis["avisos"].append(aviso)

    if infer_fn is None:
        return {"texto": spec_heuristica(analisis), "modo": "heuristico",
                "aviso": aviso, "analisis": analisis}

    system, user = construir_prompt_llm(analisis)
    salida = ""
    try:
        salida = (infer_fn(system, user) or "").strip()
    except Exception:
        salida = ""
    if not salida or DEGRADADO in salida[:200]:
        aviso_modo = ("backend local apagado: cognia install-model o arranca "
                      "Ollama; especificacion heuristica igualmente valida")
        aviso = (aviso + "; " if aviso else "") + aviso_modo
        return {"texto": spec_heuristica(analisis, aviso_modo=aviso_modo),
                "modo": "heuristico_degradado", "aviso": aviso,
                "analisis": analisis}

    # el LLM SOLO redacta el prompt reconstruido; el resto queda determinista
    texto = _render(analisis, "LLM refinado", salida)
    return {"texto": texto, "modo": "llm", "aviso": aviso,
            "analisis": analisis}
