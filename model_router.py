"""
model_router.py — Enrutamiento inteligente de modelos para Cognia
=================================================================
Detecta automáticamente el tipo de tarea y asigna el modelo correcto.

MODOS:
  modo_codigo   → qwen2.5-coder:7b-instruct-q4_K_M
                  (HTML, CSS, JS, Python, SQL, debugging, refactoring, etc.)
  modo_general  → modelo configurado en COGNIA_MODEL (llama3.2 u otro)

INTEGRACIÓN:
  Se usa como reemplazo directo de llamar_ollama() en respuestas_articuladas.py.
  El LanguageEngine lo llama transparentemente vía get_model_router().

EXTENSIBILIDAD:
  Agregar un nuevo modo: añadir entrada en MODEL_REGISTRY y reglas en
  _RULES. Sin cambiar ningún otro módulo.
"""

import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from logger_config import get_logger, log_slow

logger = get_logger(__name__)

# ── Registro de modelos ────────────────────────────────────────────────────────

MODEL_REGISTRY: dict[str, dict] = {
    "modo_codigo": {
        "model":       os.environ.get("COGNIA_CODE_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M"),
        "description": "Especializado en generación y análisis de código",
        "max_ram_gb":  5.0,
        "temperature": 0.2,    # menor temperatura → código más preciso
    },
    "modo_general": {
        "model":       os.environ.get("COGNIA_MODEL", "llama3.2"),
        "description": "Conversación general, razonamiento, memoria",
        "max_ram_gb":  3.5,
        "temperature": 0.7,
    },
    # Punto de extensión: agregar más modos aquí
    # "modo_math": {
    #     "model": "deepseek-math:7b-q4",
    #     "description": "Razonamiento matemático",
    #     "max_ram_gb": 5.0,
    #     "temperature": 0.1,
    # },
}

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# ── Reglas de detección (ordenadas de más específica a más general) ────────────

# Cada regla: (modo, descripcion, pattern_regex | keyword_list, peso)
# Se evalúan en orden; la primera que hace match gana.
_RULES: list[tuple[str, str, object, float]] = [

    # ── Patrones de código explícitos ─────────────────────────────────
    ("modo_codigo", "bloque_codigo_markdown",
     re.compile(r"```\s*(python|javascript|js|html|css|sql|typescript|ts|bash)\b",
                re.IGNORECASE), 1.0),

    ("modo_codigo", "etiqueta_html_detectada",
     re.compile(r"<(!DOCTYPE|html|head|body|div|span|script|style|form|input|button|"
                r"table|tr|td|th|ul|li|nav|header|footer|section|article|canvas|svg)",
                re.IGNORECASE), 0.95),

    ("modo_codigo", "selector_css_detectado",
     re.compile(r"[\.\#][a-zA-Z][\w\-]*\s*\{|@media\s|@keyframes\s|"
                r":\s*(hover|focus|active|before|after)\b", re.IGNORECASE), 0.95),

    ("modo_codigo", "funcion_python_detectada",
     re.compile(r"\bdef\s+\w+\s*\(|\bclass\s+\w+[\s:(]|\bimport\s+\w+|"
                r"\bfrom\s+\w+\s+import\b|\bif\s+__name__\s*==", re.IGNORECASE), 0.90),

    ("modo_codigo", "sql_detectado",
     re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|DROP\s+TABLE|"
                r"ALTER\s+TABLE|JOIN|WHERE|GROUP BY|ORDER BY)\b",
                re.IGNORECASE), 0.90),

    ("modo_codigo", "javascript_detectado",
     re.compile(r"\b(const|let|var)\s+\w+\s*=|\bfunction\s+\w+\s*\(|"
                r"=>\s*\{|\.addEventListener\(|document\.|console\.",
                re.IGNORECASE), 0.88),

    # ── Intenciones de código por keywords ────────────────────────────
    ("modo_codigo", "intent_generar_codigo",
     ["escribe el código", "escribir código", "genera una función", "genera el código",
      "create a function", "write a function", "write the code", "generate code",
      "write a class", "implementa ", "implement a",
      "crea un componente", "create a component",
      "escribe un script", "write a script",
      "crea una clase", "create a class"], 0.85),

    ("modo_codigo", "intent_debuggear",
     ["debug", "debuggear", "por qué falla", "por que falla", "why is this failing",
      "error en el código", "este código no funciona", "this code doesn't work",
      "fix this code", "arregla este código", "encuentra el bug", "find the bug",
      "traceback", "stack trace", "exception", "error line"], 0.85),

    ("modo_codigo", "intent_explicar_codigo",
     ["explica este código", "explain this code", "qué hace este código",
      "que hace este codigo", "what does this code do", "cómo funciona este código",
      "como funciona este codigo", "analyze this code", "analiza este código",
      "review my code", "revisa mi código"], 0.82),

    ("modo_codigo", "intent_refactorizar",
     ["refactor", "refactoriza", "mejora este código", "improve this code",
      "optimiza", "optimize", "clean up this code", "limpia este código",
      "make this more efficient", "hazlo más eficiente"], 0.82),

    ("modo_codigo", "intent_lenguajes",
     ["en python", "in python", "en javascript", "in javascript", "en html",
      "in html", "con css", "with css", "en sql", "in sql",
      "en typescript", "in typescript", "con react", "with react",
      "con flask", "with flask", "con django", "with django",
      "con fastapi", "con node", "with node"], 0.80),

    # ── Keywords de lenguaje solos (sin preposición) ──────────────────
    # "función Python", "código JavaScript", "script Python", etc.
    ("modo_codigo", "keyword_lenguaje_solo",
     re.compile(
         r"\b(python|javascript|typescript|html5?|css3?|sql|react|"
         r"flask|django|fastapi|jquery|nodejs?)\b",
         re.IGNORECASE
     ), 0.78),
]


# ── Dataclass de decisión ──────────────────────────────────────────────────────

@dataclass
class RouterDecision:
    """Resultado del análisis del ModelRouter."""
    mode:        str              # "modo_codigo" | "modo_general"
    model:       str              # nombre del modelo Ollama
    confidence:  float            # 0.0–1.0
    reason:      str              # por qué se eligió este modo
    temperature: float
    triggered_rules: list[str] = field(default_factory=list)
    routing_ms:  float = 0.0


# ── Clase principal ────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Enruta preguntas al modelo más adecuado.

    Uso básico:
        router = ModelRouter()
        decision = router.route("escribe una función Python para calcular fibonacci")
        # decision.mode == "modo_codigo"
        # decision.model == "qwen2.5-coder:7b-instruct-q4_K_M"

    Con contexto de código adicional:
        decision = router.route(pregunta, code_context="def foo(): ...")
    """

    def __init__(self, rules: list = None):
        """
        Args:
            rules: lista de reglas custom. Si None usa _RULES por defecto.
        """
        self._rules = rules or _RULES
        # Cache LRU real con OrderedDict (O(1) eviction, no FIFO)
        # FIX: el cache FIFO original tenía hit rate ~0% con consultas variadas
        from collections import OrderedDict
        self._cache: OrderedDict = OrderedDict()
        self._max_cache = 128  # aumentado de 32 a 128

    # ── API pública ────────────────────────────────────────────────────

    def route(self, question: str, code_context: str = "") -> RouterDecision:
        """
        Analiza la pregunta y devuelve la decisión de enrutamiento.

        Args:
            question:     texto de la pregunta/prompt del usuario
            code_context: código adicional en el prompt (snippets, ejemplos)

        Returns:
            RouterDecision con modo, modelo, confianza y razón
        """
        t0 = time.perf_counter()

        # Cache hit
        cache_key = (question[:200] + code_context[:100])
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Combinar pregunta + contexto de código para el análisis
        full_text = question
        if code_context:
            full_text = f"{question}\n{code_context}"

        # Evaluar reglas
        best_mode  = "modo_general"
        best_conf  = 0.0
        best_reason = "sin coincidencias — usando modelo general"
        triggered  = []

        for mode, rule_name, pattern, weight in self._rules:
            if self._matches(full_text, pattern):
                triggered.append(rule_name)
                if weight > best_conf:
                    best_conf   = weight
                    best_mode   = mode
                    best_reason = rule_name
                # Early exit: alta confianza alcanzada
                if best_conf >= 0.95:
                    break

        # Si hay múltiples reglas de código, subir confianza ligeramente
        codigo_hits = sum(1 for t in triggered if t.startswith("intent_") or
                          t in ("bloque_codigo_markdown", "funcion_python_detectada",
                                "etiqueta_html_detectada"))
        if codigo_hits >= 2 and best_mode == "modo_codigo":
            best_conf = min(1.0, best_conf + 0.05)

        config = MODEL_REGISTRY[best_mode]
        elapsed = (time.perf_counter() - t0) * 1000

        decision = RouterDecision(
            mode=         best_mode,
            model=        config["model"],
            confidence=   round(best_conf, 3),
            reason=       best_reason,
            temperature=  config["temperature"],
            triggered_rules = triggered[:5],    # top 5 para logging
            routing_ms=   round(elapsed, 2),
        )

        logger.info(
            "Decisión de enrutamiento",
            extra={
                "op":      "model_router.route",
                "context": (
                    f"mode={decision.mode} model={decision.model} "
                    f"conf={decision.confidence:.2f} reason={decision.reason} "
                    f"triggered={triggered[:3]} ms={elapsed:.1f}"
                ),
            },
        )

        # Guardar en cache con eviction LRU O(1)
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
        else:
            self._cache[cache_key] = decision
            if len(self._cache) > self._max_cache:
                self._cache.popitem(last=False)  # eliminar LRU (el más antiguo)
            return decision

        return decision

    def get_model_for_mode(self, mode: str) -> str:
        """Devuelve el nombre del modelo para un modo dado."""
        return MODEL_REGISTRY.get(mode, MODEL_REGISTRY["modo_general"])["model"]

    def list_modes(self) -> list[dict]:
        """Devuelve todos los modos disponibles con su descripción."""
        return [
            {"mode": k, **v}
            for k, v in MODEL_REGISTRY.items()
        ]

    def add_rule(self, mode: str, rule_name: str,
                 pattern: object, weight: float = 0.80):
        """
        Agrega una regla personalizada en tiempo de ejecución.
        Punto de extensión principal para nuevos modos/lenguajes.

        Args:
            mode:      modo al que enrutar ("modo_codigo", "modo_general", o nuevo)
            rule_name: identificador descriptivo de la regla
            pattern:   regex compilado O lista de keywords
            weight:    peso de confianza (0.0–1.0)
        """
        if mode not in MODEL_REGISTRY:
            logger.warning(
                f"Modo '{mode}' no registrado en MODEL_REGISTRY. "
                "Agrega el modelo antes de añadir reglas.",
                extra={"op": "model_router.add_rule", "context": f"mode={mode}"},
            )
        # Insertar al inicio para que tenga prioridad sobre las reglas base
        self._rules.insert(0, (mode, rule_name, pattern, weight))
        # Invalidar cache porque las reglas cambiaron
        self._cache.clear()
        logger.info(
            f"Regla añadida: {rule_name} → {mode}",
            extra={"op": "model_router.add_rule",
                   "context": f"weight={weight} total_rules={len(self._rules)}"},
        )

    def register_model(self, mode: str, model_name: str,
                       description: str = "", max_ram_gb: float = 5.0,
                       temperature: float = 0.5):
        """
        Registra un nuevo modelo/modo en el registry.
        Llamar antes de add_rule() para nuevos modos.
        """
        MODEL_REGISTRY[mode] = {
            "model":       model_name,
            "description": description,
            "max_ram_gb":  max_ram_gb,
            "temperature": temperature,
        }
        logger.info(
            f"Modelo registrado: {mode} → {model_name}",
            extra={"op": "model_router.register_model",
                   "context": f"ram={max_ram_gb}GB temp={temperature}"},
        )

    # ── Helpers privados ───────────────────────────────────────────────

    @staticmethod
    def _matches(text: str, pattern: object) -> bool:
        """
        Evalúa si el texto hace match contra el patrón.
        Acepta regex compilado O lista de keywords.
        """
        if hasattr(pattern, "search"):
            # Es un regex compilado
            return bool(pattern.search(text))
        elif isinstance(pattern, (list, tuple)):
            # Es lista de keywords — búsqueda case-insensitive
            text_lower = text.lower()
            return any(kw.lower() in text_lower for kw in pattern)
        return False


# ── Singleton ──────────────────────────────────────────────────────────────────

_ROUTER_INSTANCE: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    """Devuelve la instancia singleton del ModelRouter."""
    global _ROUTER_INSTANCE
    if _ROUTER_INSTANCE is None:
        _ROUTER_INSTANCE = ModelRouter()
        logger.info(
            "ModelRouter inicializado",
            extra={"op": "model_router.get_model_router",
                   "context": f"modos={list(MODEL_REGISTRY.keys())} reglas={len(_RULES)}"},
        )
    return _ROUTER_INSTANCE


# ── Función de envoltura para llamar_ollama con enrutamiento ───────────────────

def llamar_ollama_routed(
    prompt:     str,
    question:   str = "",
    num_predict: int = 280,
    structured:  bool = False,
    tipo:        str = "general",
    pregunta:    str = "",
    code_context: str = "",
) -> str:
    """
    Reemplaza directamente a llamar_ollama() en respuestas_articuladas.py.
    Misma firma externa, pero enruta al modelo correcto antes de llamar.

    Esta función importa llamar_ollama internamente para evitar imports circulares.
    """
    import urllib.request
    import json

    router = get_model_router()
    # Usar 'pregunta' o 'question' como texto de análisis (compatibilidad)
    query_text = pregunta or question or prompt[:300]
    decision   = router.route(query_text, code_context=code_context)

    # Si es modo_codigo, ajustar temperatura y num_predict
    if decision.mode == "modo_codigo":
        # El modelo de código necesita más tokens para generar código completo
        num_predict = max(num_predict, 800)
        temperature = decision.temperature
    else:
        temperature = MODEL_REGISTRY["modo_general"]["temperature"]

    # Construir payload con el modelo seleccionado por el router
    system_prompt = _build_system_prompt_for_mode(decision.mode, tipo)

    payload = json.dumps({
        "model":   decision.model,
        "prompt":  prompt,
        "system":  system_prompt,
        "stream":  True,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }).encode("utf-8")

    # FIX: timeout adaptativo por modo (antes era 180s fijo para todo)
    _TIMEOUT_MAP = {"modo_codigo": 120, "modo_general": 60}
    _request_timeout = _TIMEOUT_MAP.get(decision.mode, 60)

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    t0 = time.time()
    logger.info(
        f"Llamando a Ollama",
        extra={
            "op":      "model_router.llamar_ollama_routed",
            "context": (
                f"model={decision.model} mode={decision.mode} "
                f"num_predict={num_predict} tipo={tipo}"
            ),
        },
    )

    resultado = []
    try:
        with urllib.request.urlopen(req, timeout=_request_timeout) as r:
            for linea in r:
                if not linea.strip():
                    continue
                try:
                    chunk = json.loads(linea.decode("utf-8"))
                except Exception:
                    continue
                token = chunk.get("response", "")
                if token:
                    resultado.append(token)
                if chunk.get("done"):
                    elapsed = time.time() - t0
                    logger.info(
                        f"Ollama respondió",
                        extra={
                            "op":      "model_router.llamar_ollama_routed",
                            "context": (
                                f"model={decision.model} "
                                f"elapsed={elapsed:.1f}s tokens={len(resultado)}"
                            ),
                        },
                    )
                    break
    except Exception as exc:
        logger.error(
            f"Error llamando a Ollama con modelo {decision.model}",
            extra={"op":      "model_router.llamar_ollama_routed",
                   "context": str(exc)},
        )
        raise

    return "".join(resultado).strip()


def _build_system_prompt_for_mode(mode: str, tipo: str) -> str:
    """Construye el system prompt adecuado para cada modo."""
    base = (
        "Eres Cognia, una IA con memoria episódica y grafo de conocimiento. "
        "Usa el contexto de memoria dado. "
        "Responde en el mismo idioma de la pregunta."
    )
    if mode == "modo_codigo":
        return (
            "Eres Cognia, un asistente experto en programación. "
            "Genera código limpio, funcional y bien documentado. "
            "Usa el contexto de memoria para conocer el estilo del proyecto. "
            "snake_case para Python, docstrings en español. "
            "Si hay un error, explica la causa y la solución. "
            "Responde en el mismo idioma de la pregunta."
        )
    if tipo == "tutorial":
        return base + " Pasos numerados (1. 2. 3.). Máximo 5 pasos de 1 oración cada uno."
    if tipo == "comparacion":
        return base + " 2-3 diferencias clave. Máximo 2 párrafos."
    if tipo == "lista":
        return base + " Lista máximo 5 ítems con 1 oración cada uno."
    return base + " Máximo 2 párrafos breves y directos."


# ── Tests básicos ──────────────────────────────────────────────────────────────

def _test_router_codigo():
    """Test 1: detecta preguntas de código correctamente."""
    router = ModelRouter()
    casos_codigo = [
        "escribe una función Python para invertir una lista",
        "```python\ndef foo(): pass```",
        "por qué falla este código: <div class='nav'>",
        "refactoriza esta función para que sea más eficiente",
        "SELECT * FROM users WHERE id = 1",
        "const x = document.getElementById('btn')",
    ]
    for pregunta in casos_codigo:
        d = router.route(pregunta)
        assert d.mode == "modo_codigo", (
            f"FALLO: '{pregunta[:50]}' → {d.mode} (esperado modo_codigo)"
        )
        print(f"  ✅ código detectado: '{pregunta[:50]}' → {d.model} (conf={d.confidence:.2f})")


def _test_router_general():
    """Test 2: no clasifica como código lo que no lo es."""
    router = ModelRouter()
    casos_general = [
        "cuéntame sobre la historia del jazz",
        "qué es la memoria episódica",
        "cómo estás hoy",
        "explica la teoría de la relatividad",
    ]
    for pregunta in casos_general:
        d = router.route(pregunta)
        assert d.mode == "modo_general", (
            f"FALLO: '{pregunta[:50]}' → {d.mode} (esperado modo_general)"
        )
        print(f"  ✅ general detectado: '{pregunta[:50]}' → {d.model}")


def _test_router_extension():
    """Test 3: se puede agregar un nuevo modo en tiempo de ejecución."""
    router = ModelRouter()
    # Registrar un nuevo modo ficticio
    router.register_model(
        "modo_math", "deepseek-math:7b-q4",
        description="Razonamiento matemático", max_ram_gb=5.0, temperature=0.1
    )
    router.add_rule(
        "modo_math", "intent_matematica",
        ["demuestra que", "calcula la integral", "resuelve la ecuación"],
        weight=0.90,
    )
    d = router.route("demuestra que la suma de los ángulos de un triángulo es 180°")
    assert d.mode == "modo_math", f"FALLO: esperado modo_math, obtenido {d.mode}"
    print(f"  ✅ extensión funciona: modo_math detectado (conf={d.confidence:.2f})")
    # Limpiar para no afectar otros tests
    del MODEL_REGISTRY["modo_math"]


def run_tests():
    """Ejecuta todos los tests del ModelRouter."""
    print("\n🧪 Tests ModelRouter:")
    _test_router_codigo()
    _test_router_general()
    _test_router_extension()
    print("✅ Todos los tests pasaron.\n")


if __name__ == "__main__":
    run_tests()

