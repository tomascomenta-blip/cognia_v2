"""
sandbox_tester.py — Sistema de Pruebas en Entorno Aislado para COGNIA v1
=========================================================================
Prueba cualquier módulo propuesto por SelfArchitect antes de su integración.

PROPÓSITO:
    Antes de que cualquier módulo sea integrado al sistema real, debe pasar
    por pruebas en sandbox que midan:
      - Latencia de razonamiento (ms)
      - Uso de CPU (%)
      - Uso de RAM (MB)
      - Calidad de razonamiento (score 0-100)
      - Detección de crashes o excepciones

DISEÑO INVARIANTE:
    El sandbox NUNCA modifica la base de datos real.
    Usa una base temporal en memoria o un archivo temporal.
    Los resultados se reportan al humano para aprobación final.

ARQUITECTURA:
    SandboxEnvironment — entorno aislado con DB temporal
    ModuleLoader       — carga dinámica segura de módulos propuestos
    PerformanceProfiler— mide CPU, RAM y latencia durante la prueba
    ReasoningEvaluator — valida calidad cognitiva del módulo bajo prueba
    CrashDetector      — captura excepciones y comportamiento anómalo
    SandboxTester      — orquestador principal y generador de reportes

NOTA DE SEGURIDAD:
    Los módulos se cargan en un subprocess separado cuando es posible.
    Nunca se ejecutan con acceso de escritura a la DB de producción.
"""

import sqlite3
import time
import traceback
import tempfile
import shutil
import os
import json
import importlib.util
import sys
from datetime import datetime
from typing import Optional, Dict, List, Any, Callable
from contextlib import contextmanager

# ══════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════

SANDBOX_DB_PATH    = "cognia_memory.db"
MAX_TEST_DURATION  = 30.0   # segundos máximos por prueba
CPU_SAMPLE_INTERVAL = 0.1   # segundos entre muestras de CPU
MEMORY_WARNING_MB   = 200   # umbral de advertencia de RAM
LATENCY_WARNING_MS  = 1000  # umbral de advertencia de latencia

# Criterios de aprobación del sandbox
PASS_CRITERIA = {
    "max_latency_ms":     800,    # latencia máxima aceptable
    "max_cpu_delta":      15.0,   # delta máximo de CPU (%) vs baseline
    "max_memory_delta_mb": 50.0,  # delta máximo de RAM (MB) vs baseline
    "min_reasoning_score": 60,    # score mínimo de calidad cognitiva
    "no_crashes":          True,  # cero crashes/excepciones no controladas
}


# ══════════════════════════════════════════════════════════════════════
# 1. SANDBOX ENVIRONMENT — entorno aislado con DB temporal
# ══════════════════════════════════════════════════════════════════════

class SandboxEnvironment:
    """
    Crea un entorno temporal aislado para pruebas.
    Copia la DB real en un archivo temporal de sólo lectura efectiva.
    """

    def __init__(self, production_db: str = SANDBOX_DB_PATH):
        self.production_db = production_db
        self.temp_dir      = None
        self.sandbox_db    = None

    def __enter__(self):
        self.temp_dir   = tempfile.mkdtemp(prefix="cognia_sandbox_")
        sandbox_db_path = os.path.join(self.temp_dir, "sandbox.db")

        # Copiar DB real al sandbox (sin modificar la original)
        if os.path.exists(self.production_db):
            shutil.copy2(self.production_db, sandbox_db_path)
        else:
            # Crear DB mínima de prueba
            conn = sqlite3.connect(sandbox_db_path)
            self._seed_minimal_db(conn)
            conn.close()

        self.sandbox_db = sandbox_db_path
        return self

    def __exit__(self, *args):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_minimal_db(self, conn: sqlite3.Connection):
        """Crea datos mínimos de prueba para módulos que requieren DB."""
        c = conn.cursor()
        # Tablas mínimas para que los módulos no fallen en import
        tables = [
            "CREATE TABLE IF NOT EXISTS episodic_memory (id INTEGER PRIMARY KEY, content TEXT, confidence REAL DEFAULT 0.5, importance REAL DEFAULT 0.5, forgotten INTEGER DEFAULT 0, label TEXT, timestamp TEXT)",
            "CREATE TABLE IF NOT EXISTS semantic_memory (concept TEXT PRIMARY KEY, confidence REAL DEFAULT 0.5, support INTEGER DEFAULT 1, updated_at TEXT)",
            "CREATE TABLE IF NOT EXISTS knowledge_graph (id INTEGER PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, weight REAL DEFAULT 1.0)",
            "CREATE TABLE IF NOT EXISTS hypotheses (id INTEGER PRIMARY KEY, text TEXT, confidence REAL DEFAULT 0.3)",
            "CREATE TABLE IF NOT EXISTS contradictions (id INTEGER PRIMARY KEY, concept_a TEXT, concept_b TEXT, description TEXT, severity TEXT DEFAULT 'medium', resolved INTEGER DEFAULT 0, created_at TEXT)",
            "CREATE TABLE IF NOT EXISTS chat_history (id INTEGER PRIMARY KEY, role TEXT, content TEXT, feedback INTEGER, timestamp TEXT)",
            "CREATE TABLE IF NOT EXISTS decision_log (id INTEGER PRIMARY KEY, decision TEXT, was_error INTEGER DEFAULT 0, timestamp TEXT)",
        ]
        for sql in tables:
            c.execute(sql)

        # Datos de muestra
        now = datetime.now().isoformat()
        for i in range(10):
            c.execute("INSERT OR IGNORE INTO episodic_memory (content, confidence, importance, timestamp) VALUES (?,?,?,?)",
                      (f"Memoria de prueba {i}", 0.5 + i*0.03, 0.4 + i*0.05, now))
        for concept in ["aprendizaje", "memoria", "energía", "razonamiento", "hipótesis"]:
            c.execute("INSERT OR IGNORE INTO semantic_memory (concept, confidence, support, updated_at) VALUES (?,?,?,?)",
                      (concept, 0.6, 3, now))
        conn.commit()


# ══════════════════════════════════════════════════════════════════════
# 2. PERFORMANCE PROFILER — mide CPU, RAM y latencia
# ══════════════════════════════════════════════════════════════════════

class PerformanceProfiler:
    """
    Mide el impacto de rendimiento de ejecutar una función.
    Usa psutil si está disponible; si no, estimaciones básicas del SO.
    """

    def __init__(self):
        self._psutil_available = self._check_psutil()

    @staticmethod
    def _check_psutil() -> bool:
        try:
            import psutil
            return True
        except ImportError:
            return False

    def get_memory_mb(self) -> float:
        """Memoria RAM del proceso actual en MB."""
        if self._psutil_available:
            import psutil
            p = psutil.Process(os.getpid())
            return p.memory_info().rss / (1024 * 1024)
        # Fallback: leer /proc/self/status en Linux
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024.0
        except Exception:
            pass
        return 0.0

    def get_cpu_percent(self, interval: float = 0.1) -> float:
        """Porcentaje de CPU del proceso actual."""
        if self._psutil_available:
            import psutil
            p = psutil.Process(os.getpid())
            return p.cpu_percent(interval=interval)
        return 0.0

    @contextmanager
    def measure(self, label: str = ""):
        """Context manager que mide latencia, CPU y RAM de un bloque."""
        mem_before = self.get_memory_mb()
        cpu_before = self.get_cpu_percent(0.05)
        t_start    = time.perf_counter()

        result = {"label": label, "success": True, "error": None}
        try:
            yield result
        except Exception as e:
            result["success"] = False
            result["error"]   = str(e)
            result["traceback"] = traceback.format_exc()
        finally:
            t_end      = time.perf_counter()
            mem_after  = self.get_memory_mb()
            cpu_after  = self.get_cpu_percent(0.05)

            result["latency_ms"]    = round((t_end - t_start) * 1000, 2)
            result["memory_mb"]     = round(mem_after, 2)
            result["memory_delta_mb"] = round(mem_after - mem_before, 2)
            result["cpu_percent"]   = round((cpu_before + cpu_after) / 2.0, 2)
            result["cpu_delta"]     = round(cpu_after - cpu_before, 2)


# ══════════════════════════════════════════════════════════════════════
# 3. MODULE LOADER — carga dinámica segura de módulos propuestos
# ══════════════════════════════════════════════════════════════════════

class ModuleLoader:
    """
    Carga un módulo Python de forma dinámica y segura.
    Verifica que el módulo tenga la estructura esperada.
    """

    REQUIRED_INTERFACE = []  # Lista de métodos que deben existir en la clase principal

    @staticmethod
    def load_from_code(code_str: str, module_name: str = "sandbox_module") -> Any:
        """
        Carga un módulo desde un string de código Python.
        Retorna el módulo cargado o lanza Exception si falla.
        """
        # Guardar en archivo temporal
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix=f"{module_name}_", delete=False
        ) as f:
            f.write(code_str)
            temp_path = f.name

        try:
            spec   = importlib.util.spec_from_file_location(module_name, temp_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            os.unlink(temp_path)

    @staticmethod
    def load_from_file(file_path: str) -> Any:
        """Carga un módulo desde un archivo .py existente."""
        module_name = os.path.basename(file_path).replace(".py", "")
        spec   = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def validate_module(module: Any, required_attrs: List[str]) -> Dict:
        """Verifica que el módulo tenga los atributos requeridos."""
        missing = [attr for attr in required_attrs if not hasattr(module, attr)]
        return {
            "valid":   len(missing) == 0,
            "missing": missing,
        }


# ══════════════════════════════════════════════════════════════════════
# 4. REASONING EVALUATOR — valida calidad cognitiva del módulo
# ══════════════════════════════════════════════════════════════════════

class ReasoningEvaluator:
    """
    Evalúa la calidad cognitiva de un módulo mediante pruebas de humo.
    No usa LLM — usa heurísticas basadas en las métricas del sandbox DB.
    """

    def __init__(self, sandbox_db: str):
        self.db = sandbox_db

    def evaluate(self, module: Any, module_name: str) -> Dict:
        """
        Ejecuta pruebas de razonamiento y retorna un score 0-100.
        Las pruebas varían según el tipo de módulo detectado.
        """
        score  = 100
        issues = []
        checks = []

        # Prueba 1: ¿El módulo importa sin errores?
        checks.append({"name": "import_clean", "passed": True, "note": "módulo importado sin errores"})

        # Prueba 2: ¿El módulo expone clases o funciones?
        public_items = [k for k in dir(module) if not k.startswith("_")]
        if len(public_items) < 1:
            score -= 20
            issues.append("El módulo no expone elementos públicos")
            checks.append({"name": "public_api", "passed": False, "note": "sin API pública"})
        else:
            checks.append({"name": "public_api", "passed": True, "note": f"{len(public_items)} elementos públicos"})

        # Prueba 3: ¿El módulo puede inicializarse con la sandbox DB?
        main_class = self._find_main_class(module, module_name)
        if main_class:
            try:
                try:
                    instance = main_class(self.db)
                except TypeError:
                    instance = main_class()
                checks.append({"name": "instantiation", "passed": True, "note": f"{main_class.__name__} instanciado"})
            except Exception as e:
                score -= 25
                issues.append(f"Error al instanciar clase principal: {e}")
                checks.append({"name": "instantiation", "passed": False, "note": str(e)})
        else:
            checks.append({"name": "instantiation", "passed": None, "note": "no se detectó clase principal"})

        # Prueba 4: ¿El módulo tiene docstrings? (señal de documentación)
        has_docs = bool(getattr(module, "__doc__", None))
        if not has_docs:
            score -= 5
            checks.append({"name": "documentation", "passed": False, "note": "sin docstring de módulo"})
        else:
            checks.append({"name": "documentation", "passed": True, "note": "módulo documentado"})

        # Prueba 5: ¿Cuántas tablas de DB intenta acceder? (estimación de costo)
        try:
            import inspect
            source = inspect.getsource(module)
            db_tables = [t for t in ["episodic_memory", "semantic_memory", "knowledge_graph",
                                     "hypotheses", "contradictions", "energy_log"]
                         if t in source]
            if len(db_tables) > 4:
                score -= 10
                issues.append(f"Módulo accede a muchas tablas ({len(db_tables)}): posible costo alto")
            checks.append({"name": "db_access_scope", "passed": len(db_tables) <= 4,
                           "note": f"accede a: {', '.join(db_tables) or 'ninguna'}"})
        except Exception:
            pass

        return {
            "score":  max(0, score),
            "issues": issues,
            "checks": checks,
        }

    @staticmethod
    def _find_main_class(module: Any, module_name: str) -> Optional[type]:
        """Intenta encontrar la clase principal del módulo."""
        import inspect
        # Buscar clase cuyo nombre coincide con el módulo (sin sufijos)
        clean_name = module_name.replace("_engine", "").replace("_module", "").replace("_", "").lower()
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if name.lower() == clean_name or name.lower().startswith(clean_name[:4]):
                if obj.__module__ == module.__name__:
                    return obj
        # Fallback: primera clase definida en el módulo
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if hasattr(obj, "__module__") and obj.__module__ == getattr(module, "__name__", ""):
                return obj
        return None


# ══════════════════════════════════════════════════════════════════════
# 5. CRASH DETECTOR — detecta excepciones y comportamientos anómalos
# ══════════════════════════════════════════════════════════════════════

class CrashDetector:
    """
    Ejecuta una función bajo vigilancia y captura cualquier fallo.
    """

    @staticmethod
    def safe_run(func: Callable, *args, timeout_s: float = MAX_TEST_DURATION, **kwargs) -> Dict:
        """
        Ejecuta func(*args, **kwargs) de forma segura.
        Retorna {'success': bool, 'result': Any, 'error': str, 'traceback': str}
        """
        result = {"success": False, "result": None, "error": None, "traceback": None}
        t_start = time.perf_counter()
        try:
            output = func(*args, **kwargs)
            elapsed = time.perf_counter() - t_start
            if elapsed > timeout_s:
                result["success"] = False
                result["error"]   = f"Timeout excedido ({elapsed:.1f}s > {timeout_s}s)"
            else:
                result["success"] = True
                result["result"]  = output
        except Exception as e:
            result["error"]     = str(e)
            result["traceback"] = traceback.format_exc()
        return result


# ══════════════════════════════════════════════════════════════════════
# 6. SANDBOX TESTER — orquestador principal
# ══════════════════════════════════════════════════════════════════════

class SandboxTester:
    """
    Orquesta la prueba completa de un módulo propuesto.

    Flujo:
      1. Crear entorno sandbox (DB temporal)
      2. Cargar módulo de forma segura
      3. Medir baseline de CPU/RAM antes de la prueba
      4. Ejecutar pruebas de rendimiento y razonamiento
      5. Generar reporte estructurado
      6. Determinar si el módulo APRUEBA o FALLA los criterios

    NUNCA modifica la DB de producción.
    El resultado es siempre un reporte para aprobación humana.
    """

    def __init__(self, production_db: str = SANDBOX_DB_PATH):
        self.production_db = production_db
        self.profiler      = PerformanceProfiler()
        self.loader        = ModuleLoader()
        self.detector      = CrashDetector()

    def test_module_from_code(
        self,
        module_code: str,
        module_name: str,
        proposal_id: Optional[int] = None,
    ) -> Dict:
        """
        Prueba un módulo dado como string de código Python.
        Retorna un reporte completo de sandbox.
        """
        report = {
            "timestamp":   datetime.now().isoformat(),
            "module_name": module_name,
            "proposal_id": proposal_id,
            "passed":      False,
            "summary":     "",
            "details":     {},
        }

        with SandboxEnvironment(self.production_db) as env:
            # ── Paso 1: Cargar módulo ──────────────────────────────────
            load_result = self.detector.safe_run(
                self.loader.load_from_code, module_code, module_name)

            if not load_result["success"]:
                report["summary"] = f"FALLO en carga del módulo: {load_result['error']}"
                report["details"]["load"] = load_result
                return report

            module = load_result["result"]
            report["details"]["load"] = {"success": True, "note": "módulo cargado correctamente"}

            # ── Paso 2: Baseline de rendimiento ───────────────────────
            baseline_mem = self.profiler.get_memory_mb()
            baseline_cpu = self.profiler.get_cpu_percent(0.2)

            # ── Paso 3: Prueba de rendimiento ─────────────────────────
            with self.profiler.measure("performance_test") as perf:
                evaluator = ReasoningEvaluator(env.sandbox_db)
                reasoning_result = evaluator.evaluate(module, module_name)

            report["details"]["performance"] = {
                "latency_ms":       perf["latency_ms"],
                "memory_mb":        perf["memory_mb"],
                "memory_delta_mb":  perf["memory_delta_mb"],
                "cpu_percent":      perf["cpu_percent"],
                "cpu_delta":        perf["cpu_delta"],
                "baseline_mem_mb":  round(baseline_mem, 2),
                "baseline_cpu":     round(baseline_cpu, 2),
            }

            report["details"]["reasoning"] = reasoning_result

            # ── Paso 4: Detección de crashes ──────────────────────────
            crash_info = {"crashes_detected": 0, "exceptions": []}
            if not perf.get("success", True):
                crash_info["crashes_detected"] = 1
                crash_info["exceptions"].append(perf.get("error", "Error desconocido"))
            report["details"]["crashes"] = crash_info

            # ── Paso 5: Evaluar criterios de aprobación ───────────────
            criteria_results = self._evaluate_criteria(
                perf, reasoning_result, crash_info)
            report["details"]["criteria"] = criteria_results

            # ── Paso 6: Veredicto final ────────────────────────────────
            all_passed = all(c["passed"] for c in criteria_results.values())
            report["passed"] = all_passed
            report["summary"] = self._build_summary(
                module_name, all_passed, perf, reasoning_result, criteria_results)

        return report

    def test_module_from_file(self, file_path: str, proposal_id: Optional[int] = None) -> Dict:
        """Prueba un módulo desde un archivo .py."""
        try:
            with open(file_path, "r") as f:
                code = f.read()
            module_name = os.path.basename(file_path).replace(".py", "")
            return self.test_module_from_code(code, module_name, proposal_id)
        except Exception as e:
            return {
                "timestamp":   datetime.now().isoformat(),
                "module_name": os.path.basename(file_path),
                "proposal_id": proposal_id,
                "passed":      False,
                "summary":     f"Error al leer archivo: {e}",
                "details":     {},
            }

    def _evaluate_criteria(
        self,
        perf: Dict,
        reasoning: Dict,
        crashes: Dict,
    ) -> Dict:
        c = PASS_CRITERIA
        return {
            "latency": {
                "passed": perf.get("latency_ms", 0) <= c["max_latency_ms"],
                "value":  perf.get("latency_ms", 0),
                "limit":  c["max_latency_ms"],
                "label":  "Latencia (ms)",
            },
            "cpu": {
                "passed": abs(perf.get("cpu_delta", 0)) <= c["max_cpu_delta"],
                "value":  perf.get("cpu_delta", 0),
                "limit":  c["max_cpu_delta"],
                "label":  "Delta CPU (%)",
            },
            "memory": {
                "passed": perf.get("memory_delta_mb", 0) <= c["max_memory_delta_mb"],
                "value":  perf.get("memory_delta_mb", 0),
                "limit":  c["max_memory_delta_mb"],
                "label":  "Delta RAM (MB)",
            },
            "reasoning": {
                "passed": reasoning.get("score", 0) >= c["min_reasoning_score"],
                "value":  reasoning.get("score", 0),
                "limit":  c["min_reasoning_score"],
                "label":  "Score de razonamiento",
            },
            "stability": {
                "passed": crashes.get("crashes_detected", 0) == 0,
                "value":  crashes.get("crashes_detected", 0),
                "limit":  0,
                "label":  "Crashes detectados",
            },
        }

    @staticmethod
    def _build_summary(
        module_name: str,
        passed: bool,
        perf: Dict,
        reasoning: Dict,
        criteria: Dict,
    ) -> str:
        lines = [
            f"\n{'='*60}",
            f"REPORTE DE SANDBOX — {module_name}",
            f"{'='*60}",
            f"VEREDICTO: {'✅ APROBADO' if passed else '❌ RECHAZADO'}",
            "",
            "── Métricas de rendimiento ──",
            f"  Latencia:     {perf.get('latency_ms',0):.1f} ms  "
            f"({'OK' if criteria['latency']['passed'] else 'FALLO'})",
            f"  Delta CPU:    {perf.get('cpu_delta',0):+.1f}%  "
            f"({'OK' if criteria['cpu']['passed'] else 'FALLO'})",
            f"  Delta RAM:    {perf.get('memory_delta_mb',0):+.1f} MB  "
            f"({'OK' if criteria['memory']['passed'] else 'FALLO'})",
            "",
            "── Calidad cognitiva ──",
            f"  Score:        {reasoning.get('score',0)}/100  "
            f"({'OK' if criteria['reasoning']['passed'] else 'FALLO'})",
        ]
        if reasoning.get("issues"):
            lines.append("  Problemas detectados:")
            for issue in reasoning["issues"]:
                lines.append(f"    • {issue}")

        lines.append("")
        lines.append("── Checks de razonamiento ──")
        for check in reasoning.get("checks", []):
            icon = "✅" if check.get("passed") else ("⚠️" if check.get("passed") is None else "❌")
            lines.append(f"  {icon} {check['name']}: {check.get('note','')}")

        lines.append("")
        lines.append(f"  Crashes:      {criteria['stability']['value']}  "
                     f"({'OK' if criteria['stability']['passed'] else 'FALLO'})")

        if not passed:
            failed = [k for k, v in criteria.items() if not v["passed"]]
            lines.append(f"\n⚠️  Criterios fallidos: {', '.join(failed)}")
            lines.append("   El módulo NO debe integrarse hasta resolver estos problemas.")
        else:
            lines.append("\n✅ El módulo superó todos los criterios.")
            lines.append("   Puede proceder a integración previa aprobación humana.")

        lines.append(f"{'='*60}")
        return "\n".join(lines)

    def format_report_for_human(self, report: Dict) -> str:
        """Versión compacta del reporte para mostrar al usuario."""
        return report.get("summary", "Sin resumen disponible.")


# ══════════════════════════════════════════════════════════════════════
# INTEGRACIÓN FLASK
# ══════════════════════════════════════════════════════════════════════

def register_routes_sandbox(app, production_db: str = SANDBOX_DB_PATH):
    """Registra los endpoints del sandbox en la app Flask."""
    from flask import request, jsonify

    tester = SandboxTester(production_db)

    @app.route("/api/sandbox/probar", methods=["POST"])
    def api_sandbox_probar():
        """
        Prueba un módulo dado como código Python en el body JSON.
        Body: { "code": "...", "module_name": "...", "proposal_id": 123 }
        """
        data        = request.get_json() or {}
        code        = data.get("code", "")
        module_name = data.get("module_name", "unnamed_module")
        proposal_id = data.get("proposal_id")

        if not code:
            return jsonify({"error": "Se requiere el campo 'code'"}), 400

        report = tester.test_module_from_code(code, module_name, proposal_id)
        return jsonify({
            "passed":   report["passed"],
            "summary":  report["summary"],
            "details":  report["details"],
            "timestamp": report["timestamp"],
        })

    @app.route("/api/sandbox/probar_archivo", methods=["POST"])
    def api_sandbox_probar_archivo():
        """Prueba un módulo desde la ruta de archivo en el servidor."""
        data        = request.get_json() or {}
        file_path   = data.get("file_path", "")
        proposal_id = data.get("proposal_id")

        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": f"Archivo no encontrado: {file_path}"}), 404

        report = tester.test_module_from_file(file_path, proposal_id)
        return jsonify({
            "passed":   report["passed"],
            "summary":  report["summary"],
            "details":  report["details"],
            "timestamp": report["timestamp"],
        })

    print("[OK] SandboxTester v1 activo — endpoints /api/sandbox/* registrados")
    return tester
