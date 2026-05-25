"""
cognia/agents/workers/file_explorer.py — Phase 24

Explora proyectos en disco: árbol de archivos + símbolos Python vía ast.parse().
0 LLM calls. 0 dependencias externas. Solo stdlib.

Límites: MAX_FILES=500, MAX_DEPTH=6 para no bloquear en repos grandes.
Output almacenado en TaskScopedWorkingMemory (nunca en EpisodicMemory global).
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

MAX_FILES = 500
MAX_DEPTH = 6

_PY_EXTENSIONS  = {".py"}
_TEXT_EXTENSIONS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


@dataclass
class FileSymbols:
    path:      str
    functions: List[str] = field(default_factory=list)
    classes:   List[str] = field(default_factory=list)
    imports:   List[str] = field(default_factory=list)
    error:     Optional[str] = None


@dataclass
class ProjectIndex:
    root:        str
    files:       List[str]           # rutas relativas a root
    symbols:     Dict[str, FileSymbols]  # path → símbolos
    total_files: int
    truncated:   bool  # True si se alcanzó MAX_FILES


def explore(path: str) -> ProjectIndex:
    """
    Explora el directorio/archivo en path y retorna un ProjectIndex.
    Si path es un archivo .py, lo analiza directamente.
    Si path es un directorio, hace os.walk() con límites.
    """
    p = Path(path)

    if p.is_file():
        return _explore_file(p)

    if p.is_dir():
        return _explore_dir(p)

    return ProjectIndex(
        root=str(path),
        files=[],
        symbols={},
        total_files=0,
        truncated=False,
    )


def _explore_file(p: Path) -> ProjectIndex:
    symbols = {}
    if p.suffix in _PY_EXTENSIONS:
        sym = _parse_python(p)
        symbols[str(p)] = sym
    return ProjectIndex(
        root=str(p.parent),
        files=[str(p)],
        symbols=symbols,
        total_files=1,
        truncated=False,
    )


def _explore_dir(root: Path) -> ProjectIndex:
    files: List[str] = []
    symbols: Dict[str, FileSymbols] = {}
    truncated = False

    for dirpath, dirnames, filenames in os.walk(str(root)):
        # Calcular profundidad relativa
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= MAX_DEPTH:
            dirnames.clear()
            continue

        # Ignorar directorios irrelevantes
        dirnames[:] = [
            d for d in dirnames
            if d not in {".git", "__pycache__", ".venv", "venv", "node_modules",
                         ".mypy_cache", ".pytest_cache", "dist", "build", ".tox"}
        ]

        for fname in filenames:
            if len(files) >= MAX_FILES:
                truncated = True
                break
            fpath = Path(dirpath) / fname
            rel = str(fpath.relative_to(root))
            if fpath.suffix in _TEXT_EXTENSIONS:
                files.append(rel)
                if fpath.suffix in _PY_EXTENSIONS:
                    symbols[rel] = _parse_python(fpath)

        if truncated:
            break

    return ProjectIndex(
        root=str(root),
        files=files,
        symbols=symbols,
        total_files=len(files),
        truncated=truncated,
    )


def _parse_python(path: Path) -> FileSymbols:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return FileSymbols(path=str(path), error=f"SyntaxError:line:{e.lineno}")
    except OSError as e:
        return FileSymbols(path=str(path), error=f"IOError:{e}")

    functions, classes, imports = [], [], []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Solo funciones de primer nivel y métodos de clase directa
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.append(module)

    return FileSymbols(
        path=str(path),
        functions=functions[:50],   # cap para evitar outputs gigantes
        classes=classes[:20],
        imports=list(dict.fromkeys(imports))[:30],  # dedup + cap
    )


def index_to_dict(index: ProjectIndex) -> dict:
    """Serializa ProjectIndex a dict JSON-safe para guardar en TaskScopedWorkingMemory."""
    return {
        "root": index.root,
        "total_files": index.total_files,
        "truncated": index.truncated,
        "files": index.files[:100],   # cap para evitar explosión de contexto
        "python_files": [
            {
                "path": sym.path,
                "functions": sym.functions,
                "classes": sym.classes,
                "imports": sym.imports[:10],
                **({"error": sym.error} if sym.error else {}),
            }
            for sym in list(index.symbols.values())[:30]
        ],
    }
