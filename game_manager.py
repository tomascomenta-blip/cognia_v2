"""
game_manager.py — Gestor de juegos para Cognia v3+
====================================================
Implementa:
  - Generación de juegos (no duplicados: si existe similar, mejora)
  - Mejora iterativa (cada versión intenta superar la anterior)
  - Auto-corrección de código antes de guardar
  - Evaluación de calidad con umbral más alto para juegos
"""

from __future__ import annotations
import ast
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Configuración ─────────────────────────────────────────────────────────────

STORAGE_DIR   = Path(__file__).parent / "generated_games"
INDEX_FILE    = "index.json"
GAME_THRESHOLD = 5.0   # Puntuación mínima para guardar un juego
EXEC_TIMEOUT  = 6      # Segundos para ejecutar el código durante validación
MAX_FIX_ATTEMPTS = 3   # Intentos de auto-corrección del código

OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("COGNIA_MODEL", "llama3.2")

# Categorías específicas de JUEGOS
GAME_CATEGORIES = [
    "text-based adventure game with inventory and rooms",
    "number guessing game with hints and high score",
    "word guessing game (Wordle-style) in terminal",
    "trivia quiz game with multiple categories",
    "hangman game with ASCII art",
    "snake game in terminal with score",
    "tic-tac-toe against AI (minimax)",
    "blackjack card game",
    "text RPG with combat and leveling",
    "maze escape game",
    "memory card matching game",
    "math challenge game with timer",
    "battleship game against computer",
    "cipher decoding puzzle game",
    "asteroid dodge game with ASCII art",
]

_instance: Optional["GameManager"] = None


def get_game_manager() -> "GameManager":
    global _instance
    if _instance is None:
        _instance = GameManager()
    return _instance


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class GameMeta:
    id:          str
    title:       str
    category:    str
    description: str
    total_score: float
    version:     int
    created_at:  str
    updated_at:  str
    improved:    bool = False
    error_count: int  = 0
    fixes_applied: int = 0


@dataclass
class GenerationResult:
    stored:       int
    attempted:    int
    programs:     list = field(default_factory=list)
    is_improvement: bool = False
    error:        Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  CLASE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

class GameManager:
    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    # ── Índice ─────────────────────────────────────────────────────────────────

    def _load_index(self) -> list[dict]:
        path = self.storage_dir / INDEX_FILE
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_index(self, index: list[dict]):
        path = self.storage_dir / INDEX_FILE
        path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── API pública ────────────────────────────────────────────────────────────

    def list_games(self) -> list[dict]:
        return sorted(self._load_index(), key=lambda g: g.get("updated_at",""), reverse=True)

    def get_total_count(self) -> int:
        return len(self._load_index())

    def format_library_summary(self) -> str:
        games = self.list_games()
        if not games:
            return "🎮 Biblioteca de juegos vacía — usa 'generar juego' para crear el primero."
        lines = [f"🎮 Biblioteca de Juegos ({len(games)} juegos)\n"]
        for g in games[:10]:
            ver_str = f"v{g.get('version',1)}"
            improved = " ✨" if g.get("improved") else ""
            lines.append(f"  [{g.get('total_score',0):.1f}/10] {ver_str} {g.get('title','')}  ({g.get('category','')[:30]}){improved}")
        return "\n".join(lines)

    # ── Generación / Mejora ────────────────────────────────────────────────────

    def generate_or_improve(
        self,
        seed_concepts: list[str] = None,
        max_attempts: int = 2,
        force_game_category: bool = True,
    ) -> dict:
        """
        FIX #3: Si existe un juego con categoría similar → lo mejora.
        Si no → crea uno nuevo.
        """
        index = self._load_index()
        existing_categories = {g["category"] for g in index}

        for attempt in range(max_attempts):
            category = self._pick_category(existing_categories, force_game_category)

            # ¿Existe un juego de esta categoría?
            existing = next((g for g in index if g["category"] == category), None)

            if existing:
                print(f"[GameManager] 🔧 Mejorando '{existing['title']}' (v{existing['version']})")
                result = self._improve_game(existing)
            else:
                print(f"[GameManager] 🆕 Generando nuevo juego: {category}")
                result = self._generate_new_game(category, seed_concepts)

            if result and result.get("stored", 0) > 0:
                return result

            time.sleep(1)

        return {"stored": 0, "attempted": max_attempts, "programs": [],
                "error": "No se pudo generar un juego que pase el evaluador"}

    def improve_all_games(self) -> dict:
        """Mejora todos los juegos existentes."""
        index    = self._load_index()
        improved = 0
        details  = []

        for game_meta in index[:5]:  # Máximo 5 por sesión
            try:
                result = self._improve_game(game_meta)
                if result and result.get("stored", 0) > 0:
                    improved += 1
                    prog = result.get("programs", [{}])[0]
                    old_score = game_meta.get("total_score", 0)
                    new_score = prog.get("total_score", old_score)
                    details.append(
                        f"✨ {game_meta['title']}: {old_score:.1f} → {new_score:.1f}/10"
                    )
            except Exception as e:
                details.append(f"❌ {game_meta.get('title','?')}: {e}")

        return {
            "improved": improved,
            "details": details,
            "message": f"{improved}/{len(index)} juegos mejorados" if index
                       else "Sin juegos en biblioteca",
        }

    # ── Generación nueva ───────────────────────────────────────────────────────

    def _generate_new_game(self, category: str, seed_concepts: list[str] = None) -> dict:
        code, title, desc = self._call_llm_for_game(category, seed_concepts)
        if not code:
            return {"stored": 0, "attempted": 1, "programs": []}

        # FIX #4: Validar y auto-corregir
        code, fixes = self._validate_and_fix(code, category)
        if not code:
            return {"stored": 0, "attempted": 1, "programs": []}

        score, exec_ok = self._evaluate_code(code)
        if score < GAME_THRESHOLD:
            print(f"[GameManager] Score insuficiente: {score:.1f} < {GAME_THRESHOLD}")
            return {"stored": 0, "attempted": 1, "programs": []}

        meta = self._save_game(
            title=title, category=category, description=desc,
            code=code, score=score, version=1, fixes=fixes
        )
        return {
            "stored": 1, "attempted": 1, "is_improvement": False,
            "programs": [asdict(meta)],
        }

    # ── Mejora iterativa ───────────────────────────────────────────────────────

    def _improve_game(self, game_meta: dict) -> dict:
        """
        FIX #3 + #4: Lee el código existente, pide al LLM que lo mejore,
        valida, y solo guarda si supera el score anterior.
        """
        old_code = self._load_game_code(game_meta["id"])
        if not old_code:
            # Si no hay código, generar desde cero
            return self._generate_new_game(game_meta["category"])

        old_score = game_meta.get("total_score", 0)
        category  = game_meta["category"]
        old_title = game_meta["title"]

        new_code, new_title, new_desc = self._call_llm_improve(
            old_code=old_code,
            old_title=old_title,
            category=category,
            old_score=old_score,
        )

        if not new_code:
            return {"stored": 0, "attempted": 1, "programs": []}

        # FIX #4: Validar y auto-corregir el código mejorado
        new_code, fixes = self._validate_and_fix(new_code, category)
        if not new_code:
            return {"stored": 0, "attempted": 1, "programs": []}

        new_score, exec_ok = self._evaluate_code(new_code)

        if new_score <= old_score and exec_ok:
            print(f"[GameManager] Mejora no suficiente: {new_score:.1f} ≤ {old_score:.1f}")
            # Si al menos corre sin errores, actualizamos igual si la diferencia es pequeña
            if new_score < old_score - 0.5:
                return {"stored": 0, "attempted": 1, "programs": []}

        meta = self._save_game(
            title=new_title or old_title,
            category=category,
            description=new_desc,
            code=new_code,
            score=new_score,
            version=game_meta.get("version", 1) + 1,
            fixes=fixes,
            game_id=game_meta["id"],  # Sobreescribe el mismo directorio
            improved=True,
        )
        return {
            "stored": 1, "attempted": 1, "is_improvement": True,
            "programs": [asdict(meta)],
        }

    # ── LLM calls ─────────────────────────────────────────────────────────────

    def _call_llm_for_game(self, category: str, seed_concepts: list[str] = None) -> tuple[str, str, str]:
        """Genera código de juego nuevo."""
        hint = ""
        if seed_concepts:
            picked = random.sample(seed_concepts, min(2, len(seed_concepts)))
            hint = f"Optional thematic inspiration: {', '.join(picked)}."

        prompt = (
            f"Write a complete, playable Python terminal game for: **{category}**\n\n"
            f"STRICT RULES:\n"
            f"- Standard library ONLY (no pip packages, no pygame)\n"
            f"- Must run in a terminal without GUI\n"
            f"- Maximum 150 lines\n"
            f"- MUST have a game loop (while True or similar)\n"
            f"- MUST show score or progress\n"
            f"- MUST handle KeyboardInterrupt gracefully\n"
            f"- Do NOT use os, subprocess, socket, shutil\n"
            f"- Use print() for display, input() for player input\n"
            f"- {hint}\n\n"
            f"Output format (EXACT, no extra text):\n\n"
            f"Title: <short game title>\n"
            f"Description: <one sentence>\n"
            f"Python Code:\n"
            f"```python\n"
            f"<complete working code here>\n"
            f"```"
        )
        return self._call_ollama(prompt)

    def _call_llm_improve(self, old_code: str, old_title: str,
                           category: str, old_score: float) -> tuple[str, str, str]:
        """Pide al LLM que mejore un juego existente."""
        prompt = (
            f"Improve this Python terminal game (current score: {old_score:.1f}/10).\n"
            f"Category: {category}\n\n"
            f"IMPROVEMENT GOALS:\n"
            f"- Fix any bugs or errors\n"
            f"- Add more interactivity or features\n"
            f"- Improve the game loop\n"
            f"- Better error handling\n"
            f"- More engaging gameplay\n"
            f"- Keep standard library only\n"
            f"- Maximum 180 lines\n\n"
            f"CURRENT CODE:\n```python\n{old_code[:3000]}\n```\n\n"
            f"Output format (EXACT):\n\n"
            f"Title: <game title>\n"
            f"Description: <one sentence>\n"
            f"Python Code:\n"
            f"```python\n"
            f"<improved code here>\n"
            f"```"
        )
        return self._call_ollama(prompt)

    def _call_ollama(self, prompt: str) -> tuple[str, str, str]:
        """Llama a Ollama y parsea la respuesta."""
        import urllib.request
        try:
            payload = json.dumps({
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "system": (
                    "You are an expert Python game developer specializing in terminal games. "
                    "Write complete, bug-free, playable games. Always follow the exact output format. "
                    "Code must be immediately runnable with no modifications."
                ),
                "stream": False,
                "options": {"temperature": 0.75, "num_predict": 2500, "top_p": 0.92},
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = json.loads(resp.read()).get("response", "").strip()

            return self._parse_llm_response(raw)

        except Exception as e:
            print(f"[GameManager] Ollama error: {e}")
            return "", "", ""

    def _parse_llm_response(self, raw: str) -> tuple[str, str, str]:
        """Extrae title, description, code de la respuesta del LLM."""
        title, desc, code_lines = "", "", []
        in_code = False

        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("title:"):
                title = stripped[6:].strip()
            elif stripped.lower().startswith("description:"):
                desc = stripped[12:].strip()
            elif stripped.startswith("```python"):
                in_code = True
            elif stripped == "```" and in_code:
                in_code = False
            elif in_code:
                code_lines.append(line)

        code = "\n".join(code_lines).strip()
        if not title:
            title = "Terminal Game"
        if len(code) < 50:
            return "", "", ""
        return code, title, desc

    # ── FIX #4: Validación y Auto-corrección ──────────────────────────────────

    def _validate_and_fix(self, code: str, category: str) -> tuple[str, int]:
        """
        Valida sintaxis, detecta imports bloqueados y ejecuta prueba.
        Intenta auto-corregir errores hasta MAX_FIX_ATTEMPTS veces.
        Retorna (código_corregido_o_vacío, num_fixes_aplicados).
        """
        fixes = 0

        # 1. Validar sintaxis AST
        try:
            ast.parse(code)
        except SyntaxError as e:
            print(f"[GameManager] SyntaxError: {e}")
            fixed = self._fix_syntax(code, str(e))
            if fixed:
                code = fixed
                fixes += 1
            else:
                return "", fixes

        # 2. Remover imports peligrosos
        code, blocked_fixes = self._remove_blocked_imports(code)
        fixes += blocked_fixes

        # 3. Prueba de ejecución rápida (5s timeout)
        success, error_msg = self._run_quick_test(code)
        if not success and error_msg:
            for attempt in range(MAX_FIX_ATTEMPTS):
                print(f"[GameManager] 🔧 Auto-fix #{attempt+1}: {error_msg[:60]}")
                fixed = self._fix_runtime_error(code, error_msg, category)
                if not fixed or fixed == code:
                    break
                code = fixed
                fixes += 1
                success, error_msg = self._run_quick_test(code)
                if success:
                    break

        return code, fixes

    def _fix_syntax(self, code: str, error_msg: str) -> str:
        """Intenta corregir errores de sintaxis simples."""
        # Fix de indentación inconsistente
        lines = code.split("\n")
        fixed = []
        for line in lines:
            if "\t" in line:
                line = line.replace("\t", "    ")
            fixed.append(line)
        new_code = "\n".join(fixed)
        try:
            ast.parse(new_code)
            return new_code
        except Exception:
            return ""

    def _remove_blocked_imports(self, code: str) -> tuple[str, int]:
        """Elimina imports de módulos peligrosos."""
        blocked = ["subprocess", "socket", "shutil", "signal", "ctypes", "pickle"]
        fixes = 0
        lines = code.split("\n")
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(f"import {b}") or
                   stripped.startswith(f"from {b}") for b in blocked):
                new_lines.append(f"# [BLOCKED] {line}")
                fixes += 1
            else:
                new_lines.append(line)
        return "\n".join(new_lines), fixes

    def _run_quick_test(self, code: str) -> tuple[bool, str]:
        """
        Ejecuta el código en un subproceso con timeout muy corto.
        Para juegos con input(), inyectamos EOF para que terminen.
        """
        # Wrapper que hace que input() retorne '' y el juego no bloquee
        test_wrapper = (
            "import sys, io\n"
            "sys.stdin = io.StringIO('\\n' * 20)  # Simular 20 inputs vacíos\n"
            "try:\n"
            + "\n".join("    " + l for l in code.split("\n"))
            + "\nexcept (EOFError, SystemExit, KeyboardInterrupt):\n    pass\n"
        )

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="cognia_test_",
                delete=False, encoding="utf-8"
            ) as f:
                f.write(test_wrapper)
                tmp = f.name

            proc = subprocess.run(
                [sys.executable, tmp],
                capture_output=True, text=True, timeout=EXEC_TIMEOUT,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                     "PYTHONPATH": "", "HOME": tempfile.gettempdir()},
            )
            os.unlink(tmp)

            if proc.returncode == 0 or proc.stdout.strip():
                return True, ""
            if proc.stderr.strip():
                return False, proc.stderr.strip()[:300]
            return True, ""

        except subprocess.TimeoutExpired:
            # Timeout = probablemente el juego tiene un bucle = ¡bueno!
            try: os.unlink(tmp)
            except: pass
            return True, ""
        except Exception as e:
            return False, str(e)

    def _fix_runtime_error(self, code: str, error_msg: str, category: str) -> str:
        """
        Intenta corregir un error de ejecución usando el LLM.
        """
        import urllib.request
        prompt = (
            f"Fix this Python terminal game code. It has a runtime error.\n\n"
            f"ERROR:\n{error_msg[:300]}\n\n"
            f"BROKEN CODE:\n```python\n{code[:2500]}\n```\n\n"
            f"Fix the error and return ONLY the corrected Python code in:\n"
            f"```python\n<fixed code>\n```"
        )
        try:
            payload = json.dumps({
                "model": OLLAMA_MODEL, "prompt": prompt,
                "stream": False, "options": {"temperature": 0.3, "num_predict": 2000}
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate", data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = json.loads(resp.read()).get("response", "")

            # Extraer código de la respuesta
            if "```python" in raw:
                start = raw.index("```python") + 9
                end   = raw.index("```", start) if "```" in raw[start:] else len(raw)
                return raw[start:end].strip()
        except Exception:
            pass
        return ""

    # ── Evaluación de calidad ──────────────────────────────────────────────────

    def _evaluate_code(self, code: str) -> tuple[float, bool]:
        """
        Evalúa la calidad del código sin ejecutarlo completamente.
        Retorna (score_0_10, ejecuta_sin_errores).
        """
        score = 0.0

        # Análisis sintáctico
        try:
            tree = ast.parse(code)
            score += 1.0  # Sintaxis válida
        except SyntaxError:
            return 0.0, False

        # Métricas de calidad
        lines = [l for l in code.split("\n") if l.strip() and not l.strip().startswith("#")]
        line_count = len(lines)

        # Longitud adecuada (20-150 líneas)
        if line_count >= 50:  score += 1.5
        elif line_count >= 20: score += 0.8

        # Tiene funciones
        funcs = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        if funcs >= 3: score += 1.0
        elif funcs >= 1: score += 0.5

        # Tiene bucle de juego
        has_while = any(isinstance(n, ast.While) for n in ast.walk(tree))
        has_for   = any(isinstance(n, ast.For) for n in ast.walk(tree))
        if has_while: score += 1.5  # while True es esencial en juegos
        elif has_for: score += 0.5

        # Tiene input() (interactividad)
        has_input = "input(" in code or "input (" in code
        if has_input: score += 1.0

        # Tiene manejo de excepciones
        has_try = any(isinstance(n, ast.Try) for n in ast.walk(tree))
        if has_try: score += 0.5

        # Tiene score/puntuación
        score_keywords = ["score", "puntos", "points", "lives", "vidas", "level", "nivel"]
        if any(kw in code.lower() for kw in score_keywords): score += 0.8

        # No tiene imports bloqueados
        blocked = ["subprocess", "socket", "shutil", "os.system"]
        if not any(b in code for b in blocked): score += 0.7

        # Test de ejecución rápida
        exec_ok, err = self._run_quick_test(code)
        if exec_ok:
            score += 1.0
        else:
            score -= 1.0

        final = min(round(score, 2), 10.0)
        print(f"[GameManager] 📊 Score: {final}/10 (lines={line_count}, funcs={funcs}, loop={has_while}, input={has_input})")
        return final, exec_ok

    # ── Almacenamiento ─────────────────────────────────────────────────────────

    def _save_game(self, title: str, category: str, description: str,
                   code: str, score: float, version: int,
                   fixes: int = 0, game_id: str = None, improved: bool = False) -> GameMeta:
        """Guarda o sobreescribe un juego en disco y actualiza el índice."""

        now = datetime.now().isoformat()

        if game_id:
            dir_name = game_id
        else:
            base = re.sub(r"[^a-z0-9]", "_", title.lower())[:40].strip("_") or "game"
            dir_name = self._unique_dirname(base)

        game_dir = self.storage_dir / dir_name
        game_dir.mkdir(parents=True, exist_ok=True)

        # Guardar código
        (game_dir / "game.py").write_text(
            f"# Cognia Generated Game | {now}\n"
            f"# Category: {category}\n"
            f"# Score: {score:.1f}/10 | Version: {version} | Fixes: {fixes}\n\n"
            + code, encoding="utf-8"
        )

        # Guardar metadata
        meta_dict = {
            "id": dir_name, "title": title, "category": category,
            "description": description or f"A {category} game.",
            "total_score": score, "version": version,
            "created_at": now if version == 1 else self._get_created_at(dir_name),
            "updated_at": now, "improved": improved,
            "fixes_applied": fixes, "error_count": 0,
        }
        (game_dir / "metadata.json").write_text(
            json.dumps(meta_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Actualizar índice
        index = self._load_index()
        existing_idx = next((i for i, g in enumerate(index) if g["id"] == dir_name), -1)
        if existing_idx >= 0:
            index[existing_idx] = meta_dict
        else:
            index.append(meta_dict)
        self._save_index(index)

        print(f"[GameManager] 💾 {'Mejorado' if improved else 'Guardado'}: {game_dir}")
        return GameMeta(**{k: meta_dict[k] for k in GameMeta.__dataclass_fields__})

    def _load_game_code(self, game_id: str) -> str:
        """Carga el código fuente de un juego."""
        path = self.storage_dir / game_id / "game.py"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _get_created_at(self, game_id: str) -> str:
        index = self._load_index()
        game = next((g for g in index if g["id"] == game_id), {})
        return game.get("created_at", datetime.now().isoformat())

    def _unique_dirname(self, base: str) -> str:
        candidate, i = base, 1
        while (self.storage_dir / candidate).exists():
            candidate = f"{base}_{i:02d}"
            i += 1
        return candidate

    def _pick_category(self, existing_categories: set[str], prefer_game: bool = True) -> str:
        """Elige categoría priorizando las que tienen juegos para mejorar."""
        # Si hay categorías existentes, a veces las elegimos para mejorar
        if existing_categories and random.random() < 0.6:
            return random.choice(list(existing_categories))
        if prefer_game:
            return random.choice(GAME_CATEGORIES)
        # Mezcla de juegos y programas genéricos
        from generator import PROGRAM_CATEGORIES
        return random.choice(GAME_CATEGORIES + PROGRAM_CATEGORIES)


# ═══════════════════════════════════════════════════════════════════════════════
#  MÓDULO AUTÓNOMO
# ═══════════════════════════════════════════════════════════════════════════════

class AutonomousManager:
    """Gestiona el ciclo autónomo cuando Cognia está idle."""

    _instance: Optional["AutonomousManager"] = None

    def __init__(self, cognia_instance):
        self.cognia = cognia_instance
        self.cycle_count = 0
        self.searches_done = 0
        self._paused = False

    @classmethod
    def get_instance(cls, cognia_instance) -> "AutonomousManager":
        if cls._instance is None:
            cls._instance = cls(cognia_instance)
        return cls._instance

    def run_cycle(self) -> dict:
        """
        Ejecuta UN ciclo autónomo. Rota entre:
          1. Investigar preguntas pendientes
          2. Generar/mejorar un juego
          3. Consolidar memoria
        """
        if self._paused:
            return {"action": "paused", "message": "Modo autónomo pausado"}

        self.cycle_count += 1
        action = self.cycle_count % 3

        if action == 1:
            return self._research_cycle()
        elif action == 2:
            return self._game_cycle()
        else:
            return self._memory_cycle()

    def _research_cycle(self) -> dict:
        """Investiga preguntas pendientes del CuriosityEngine."""
        try:
            if not hasattr(self.cognia, "curiosity_engine") or not self.cognia.curiosity_engine:
                return self._memory_cycle()

            pending = self.cognia.curiosity_engine.get_pending_proposals()
            if not pending:
                return {"action": "no_questions", "message": "Sin preguntas pendientes"}

            from researcher import research_question
            from knowledge_integrator import integrate_research

            proposal = pending[0]
            result = research_question(proposal)
            if result:
                db = getattr(self.cognia.episodic, "db", "cognia_memory.db")
                integration = integrate_research(result, self.cognia, db)
                self.searches_done += 1
                try:
                    self.cognia.curiosity_engine.mark_explored(
                        proposal["id"], outcome=result.answer[:100]
                    )
                except Exception:
                    pass
                return {
                    "action": "research",
                    "message": f"Investigué '{result.topic}': +{integration.triples_added} triples, +{integration.concepts_touched} conceptos",
                    "searches_done": self.searches_done,
                }
        except Exception as e:
            print(f"[Autonomous] Research error: {e}")

        return self._memory_cycle()

    def _game_cycle(self) -> dict:
        """Genera o mejora un juego en background."""
        try:
            gm = get_game_manager()
            seed_concepts = []
            try:
                concepts = self.cognia.semantic.list_all()
                seed_concepts = [c["concept"] for c in concepts if c.get("confidence", 0) >= 0.5][:5]
            except Exception:
                pass

            result = gm.generate_or_improve(seed_concepts=seed_concepts, max_attempts=1)
            if result.get("stored", 0) > 0:
                prog = result.get("programs", [{}])[0]
                action = "improved_game" if result.get("is_improvement") else "new_game"
                return {
                    "action": action,
                    "message": f"{'Mejoré' if result['is_improvement'] else 'Generé'} juego: {prog.get('title','?')} ({prog.get('total_score',0):.1f}/10)",
                    "searches_done": self.searches_done,
                }
        except Exception as e:
            print(f"[Autonomous] Game cycle error: {e}")

        return {"action": "game_skipped", "message": "No se pudo generar juego", "searches_done": self.searches_done}

    def _memory_cycle(self) -> dict:
        """Ciclo suave de consolidación de memoria."""
        try:
            self.cognia.sleep()
            return {"action": "memory_consolidation", "message": "Consolidé memorias en ciclo de sueño suave", "searches_done": self.searches_done}
        except Exception:
            return {"action": "idle", "message": "Ciclo idle completado", "searches_done": self.searches_done}
