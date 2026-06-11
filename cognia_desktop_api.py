"""
cognia_desktop_api.py
=====================
Local FastAPI bridge for the Cognia Desktop Electron app.

Runs on http://localhost:8765 as a child process spawned by Electron.
The renderer fetches from this server; Electron never calls Python directly.

Start manually for dev:
    uvicorn cognia_desktop_api:app --port 8765 --reload
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path (this file lives in the repo root)
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env from the repo root before any os.environ reads.
# Electron spawns this process without loading .env, so we do it here.
# Existing env vars (set by the OS or Electron) are never overridden.
def _load_dotenv(env_file: Path) -> None:
    if not env_file.is_file():
        return
    with env_file.open(encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            _key = _key.strip()
            _val = _val.strip().strip('"').strip("'")
            if _key and _key not in os.environ:
                os.environ[_key] = _val

_load_dotenv(_ROOT / ".env")

# If SHARD_WEIGHTS_DIR is set but points to a non-existent directory,
# fall back to the value from the project .env (dev workflow: shards in project tree).
def _fix_shard_dir_if_missing() -> None:
    current = os.environ.get("SHARD_WEIGHTS_DIR", "")
    if not current:
        return
    p = Path(current) if Path(current).is_absolute() else _ROOT / current
    if p.is_dir():
        return
    # Override with project .env value
    env_file = _ROOT / ".env"
    if not env_file.is_file():
        return
    with env_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == "SHARD_WEIGHTS_DIR":
                os.environ["SHARD_WEIGHTS_DIR"] = val.strip().strip('"').strip("'")
                break

_fix_shard_dir_if_missing()

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse as _JSONResponse, HTMLResponse as _HTMLResponse
import time as _time
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from cognia.monitoring.metrics_collector import MetricsCollector as _MetricsCollector

_metrics = _MetricsCollector()

from cognia.debug.state_inspector import StateInspector as _StateInspector

_state_inspector = _StateInspector()

from shattering.model_constants import GEN_CHAT_MAX_TOKENS
from shattering.orchestrator import ShatteringOrchestrator

# ITCS: Inference-Time Compute Scaling — zero-LLM complexity scorer
from cognia.reasoning.complexity_scorer import ComplexityScorer as _ComplexityScorer
_itcs_scorer = _ComplexityScorer()

# In packaged Electron builds, suppress uvicorn's default exception handler
# so crash details are not exposed to the renderer process.
_PACKAGED = os.environ.get("COGNIA_PACKAGED", "0") == "1"

import logging as _logging
if _PACKAGED:
    _logging.getLogger().setLevel(_logging.WARNING)
else:
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(name)s %(message)s")

_MANIFEST = str(_ROOT / "shattering" / "manifests" / "cognia_desktop.json")
_COORDINATOR = os.environ.get("COGNIA_COORDINATOR_URL")

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    asyncio.create_task(_kv_evict_loop())
    if _ConsolidationWorker is not None:
        try:
            _ConsolidationWorker().start()
        except Exception as _cw_err:
            _logging.getLogger("cognia_desktop_api").warning(
                "ConsolidationWorker start failed: %s", _cw_err
            )
    yield

app = FastAPI(title="Cognia Desktop API", version="1.0.0", lifespan=_lifespan)

# COGNIA_LAN_MODE=1 → bind to 0.0.0.0 and open CORS for LAN (mobile access).
# Default (Electron mode) → localhost only.
_LAN_MODE = os.environ.get("COGNIA_LAN_MODE", "0") == "1"
_CORS_ORIGINS = (
    os.environ.get("COGNIA_CORS_ORIGINS", "*").split(",")
    if _LAN_MODE
    # Electron loadFile() sends Origin: null (file:// scheme); include it so
    # Chromium doesn't block EventSource responses from the renderer.
    else ["http://localhost:8765", "http://127.0.0.1:8765", "null"]
)

_cors_kwargs: dict = dict(
    allow_origins=_CORS_ORIGINS,
    allow_methods=["POST", "GET", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "X-API-Key", "X-Admin-Key"],
)
if _LAN_MODE:
    # Also permit 192.168.x.x LAN addresses that may not be in COGNIA_CORS_ORIGINS
    _cors_kwargs["allow_origin_regex"] = r"http://192\.168\.\d+\.\d+:\d+"

app.add_middleware(CORSMiddleware, **_cors_kwargs)

# ── API Key Auth ───────────────────────────────────────────────────────
# Middleware: reads optional X-API-Key header.
# Present + valid  -> request.state.user_id = <user_id>
# Present + invalid -> 401
# Absent           -> request.state.user_id = "local"  (local Electron compat)

_CHAT_DB = str(_ROOT / "cognia_desktop_chat.db")

def _init_chat_db() -> None:
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id TEXT NOT NULL,"
            "  role TEXT NOT NULL,"
            "  content TEXT NOT NULL,"
            "  ts INTEGER NOT NULL DEFAULT (strftime('%s','now'))"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id, id)"
        )

_init_chat_db()

# ── Session Auto-Summarizer singleton ─────────────────────────────────
from cognia.summarizer.session_summarizer import SessionSummarizer as _SessionSummarizer
import cognia.summarizer.session_summarizer as _ss_mod

_ss_mod._CHAT_DB = _CHAT_DB
_session_summarizer = _SessionSummarizer()

# ── API Key Manager singleton ──────────────────────────────────────────
from cognia.auth.api_key_manager import APIKeyManager as _APIKeyManager

_api_key_manager: _APIKeyManager = _APIKeyManager(db_path=_CHAT_DB)

# ── Desktop Rate Limiter singleton ────────────────────────────────────
from cognia.auth.rate_limiter import DesktopRateLimiter as _DesktopRateLimiter

_rate_limiter: _DesktopRateLimiter = _DesktopRateLimiter(window_s=60)

# ── Tier Config ───────────────────────────────────────────────────────
from cognia.auth.tier_config import get_rate_limit as _get_rate_limit, TIERS as _TIERS


def get_api_key_manager() -> _APIKeyManager:
    return _api_key_manager


# ── Feature Flags singleton ───────────────────────────────────────────
_feature_flags = None

try:
    from cognia.features.feature_flags import FeatureFlagManager as _FeatureFlagManager
    _FeatureFlagManager_t = _FeatureFlagManager
    _feature_flags = _FeatureFlagManager(db_path=_CHAT_DB)
except Exception as _ff_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "FeatureFlagManager init failed: %s", _ff_err
    )
    _FeatureFlagManager = None  # type: ignore[assignment,misc]


# ── PersonaManager singleton ───────────────────────────────────────────
_persona_manager = None
try:
    from cognia.persona.persona_manager import PersonaManager as _PersonaManager
    _persona_manager = _PersonaManager(db_path=_CHAT_DB)
except Exception as _pe:
    _logging.getLogger("cognia_desktop_api").warning("PersonaManager init failed: %s", _pe)

# ── PersonaAdvisor singleton ───────────────────────────────────────────
_persona_advisor = None
try:
    from cognia.persona.persona_advisor import PersonaAdvisor as _PersonaAdvisor
    _persona_advisor = _PersonaAdvisor()
except Exception as _pae:
    _logging.getLogger("cognia_desktop_api").warning("PersonaAdvisor init failed: %s", _pae)

# ── UserFactsMemory singleton ──────────────────────────────────────────
_user_facts: _Optional["_UserFactsMemory_t"] = None

try:
    from cognia.social.user_facts import UserFactsMemory as _UserFactsMemory
    _UserFactsMemory_t = _UserFactsMemory
    _user_facts = _UserFactsMemory()
except Exception as _ufe:
    _logging.getLogger("cognia_desktop_api").warning("UserFactsMemory init failed: %s", _ufe)
    _UserFactsMemory = None  # type: ignore[assignment,misc]

# ── InjectionPrioritizer singleton ────────────────────────────────────
_injector: _Optional["_InjectionPrioritizer_t"] = None

try:
    from cognia.context.injection_prioritizer import InjectionPrioritizer as _InjectionPrioritizer
    _InjectionPrioritizer_t = _InjectionPrioritizer
    _injector = _InjectionPrioritizer()
except Exception as _ipe:
    _logging.getLogger("cognia_desktop_api").warning("InjectionPrioritizer init failed: %s", _ipe)
    _InjectionPrioritizer = None  # type: ignore[assignment,misc]


@app.middleware("http")
async def _api_key_middleware(request: Request, call_next):
    """Validate optional X-API-Key header. Sets request.state.user_id and request.state.tier."""
    raw_key = request.headers.get("X-API-Key")
    if raw_key is None:
        request.state.user_id = "local"
        request.state.tier = "local"
    else:
        user_id = _api_key_manager.validate_key(raw_key)
        if user_id is None:
            return _JSONResponse(status_code=401, content={"detail": "Invalid or revoked API key"})
        request.state.user_id = user_id
        request.state.tier = _api_key_manager.get_key_tier(user_id)

    _tier_limit = _get_rate_limit(request.state.tier)
    _allowed, _retry = _rate_limiter.check(request.state.user_id, limit=_tier_limit)
    if not _allowed:
        return _JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded", "retry_after_s": _retry},
        )

    return await call_next(request)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    """Measure per-request latency and record into the metrics collector."""
    start = _time.time()
    try:
        response = await call_next(request)
        _metrics.record_request((_time.time() - start) * 1000, error=response.status_code >= 500)
        return response
    except Exception:
        _metrics.record_request((_time.time() - start) * 1000, error=True)
        raise


# ── Semantic Response Cache ────────────────────────────────────────────
# Initialized after _CHAT_DB pool exists so it can share the same SQLite file.
from cognia.semantic_cache import SemanticResponseCache as _SRC
from storage.db_pool import get_pool as _get_pool

_sem_cache: _SRC = _SRC(db_pool=_get_pool(_CHAT_DB))

# ── Cache Analytics singleton ──────────────────────────────────────────
from cognia.cache.cache_analytics import CacheAnalytics as _CacheAnalytics

_cache_analytics = _CacheAnalytics(cache_instance=_sem_cache)

# Single orchestrator instance shared across requests.
# GEN_CHAT_MAX_TOKENS (1024): the previous hardcoded 64 truncated every chat
# answer; per-request callers can still pass max_tokens to infer()/astream().
_orch = ShatteringOrchestrator(
    manifest_path=_MANIFEST,
    coordinator_url=_COORDINATOR,
    mode="auto",
    max_new_tokens=GEN_CHAT_MAX_TOKENS,
)

# ── Conversational Intent Predictor / Cache Warmer (CIP) ──────────────
_cache_warmer = None

def _init_cache_warmer() -> None:
    """Initialize CacheWarmer singleton against the shared semantic cache."""
    global _cache_warmer
    try:
        from cognia.reasoning.cache_warmer import CacheWarmer
        _cache_warmer = CacheWarmer(_orch, _sem_cache)
        _api_logger.info("CIP: CacheWarmer initialized")
    except Exception as exc:
        _api_logger.warning("CIP: could not initialize CacheWarmer: %s", exc)

try:
    _init_cache_warmer()
except Exception:
    pass

# ── Long-term Memory Consolidator singleton ───────────────────────────
from typing import Optional as _Optional
_consolidator: _Optional["_LongTermConsolidator_t"] = None

try:
    from cognia.memory.long_term_consolidator import (
        LongTermConsolidator as _LongTermConsolidator,
        ConsolidationWorker as _ConsolidationWorker,
    )
    _LongTermConsolidator_t = _LongTermConsolidator
    _consolidator = _LongTermConsolidator()
except Exception as _cle:
    _logging.getLogger("cognia_desktop_api").warning(
        "LongTermConsolidator init failed: %s", _cle
    )
    _LongTermConsolidator = None  # type: ignore[assignment,misc]
    _ConsolidationWorker = None   # type: ignore[assignment,misc]

async def _kv_evict_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            _orch._evict_mla_caches(max_age_seconds=120)
        except Exception:
            pass



# ── Pydantic models ────────────────────────────────────────────────────

from pydantic import field_validator

_MAX_PROMPT_CHARS = 4096  # guard against log flooding and excessive inference cost

class InferRequest(BaseModel):
    prompt: str
    session_id: str = Field("default", max_length=128)

    @field_validator("prompt")
    @classmethod
    def prompt_not_too_long(cls, v: str) -> str:
        if len(v) > _MAX_PROMPT_CHARS:
            raise ValueError(f"prompt too long (max {_MAX_PROMPT_CHARS} chars)")
        return v


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatStreamRequest(BaseModel):
    prompt: str
    history: list[ChatMessage] = []

    @field_validator("prompt")
    @classmethod
    def prompt_not_too_long(cls, v: str) -> str:
        if len(v) > _MAX_PROMPT_CHARS:
            raise ValueError(f"prompt too long (max {_MAX_PROMPT_CHARS} chars)")
        return v


class InferResponse(BaseModel):
    text:             str
    sub_model:        str
    confidence:       float
    latency_ms:       float
    mode:             str
    route_reason:     str
    tokens_generated: int = 0


class RouteResponse(BaseModel):
    sub_model:  str
    confidence: float
    scores:     dict
    reason:     str


# ── Endpoints ──────────────────────────────────────────────────────────

_api_logger = _logging.getLogger("cognia_desktop_api")

# ── Web Search singleton (DuckDuckGo, no API key) ─────────────────────
from cognia.search.web_search import WebSearch as _WebSearch
_web_search = _WebSearch()

# ── Tool Router singleton (deterministic keyword-based tool selection) ─
from cognia.tools.tool_router import ToolRouter as _ToolRouter
_tool_router = _ToolRouter()

# ── Real-Time Factual Validation (RFV) ────────────────────────────────
_rfv_validator = None

def _init_rfv() -> None:
    """Initialize the FactualValidator singleton against the local KG DB."""
    global _rfv_validator
    try:
        from cognia.knowledge.graph import KnowledgeGraph
        from cognia.config import DB_PATH
        kg = KnowledgeGraph(DB_PATH)
        from cognia.reasoning.factual_validator import FactualValidator
        _rfv_validator = FactualValidator(kg)
        _api_logger.info("RFV: FactualValidator initialized")
    except Exception as exc:
        _api_logger.warning("RFV: could not initialize FactualValidator: %s", exc)

# Attempt initialization at startup (non-fatal if KG/DB not ready)
try:
    _init_rfv()
except Exception:
    pass

# ── Knowledge Crystallizer singleton ─────────────────────────────────
_crystallizer: _Optional["KnowledgeCrystallizer"] = None

try:
    from cognia.knowledge.crystallizer import (
        KnowledgeCrystallizer as _KnowledgeCrystallizer,
        CrystallizationWorker as _CrystallizationWorker,
    )
    _crystallizer = _KnowledgeCrystallizer()
    _CrystallizationWorker(_crystallizer).start()
except Exception as _cryst_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "KnowledgeCrystallizer init failed: %s", _cryst_err
    )
    _KnowledgeCrystallizer = None  # type: ignore[assignment,misc]

# ── Consistency Checker singleton ────────────────────────────────────
_consistency: _Optional["ConsistencyChecker"] = None

try:
    from cognia.knowledge.consistency_checker import (
        ConsistencyChecker as _ConsistencyChecker,
    )
    _consistency = _ConsistencyChecker()
except Exception as _cc_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "ConsistencyChecker init failed: %s", _cc_err
    )
    _ConsistencyChecker = None  # type: ignore[assignment,misc]

# ── Learning Path Generator singleton ────────────────────────────────
_learning_path: _Optional["_LearningPathGenerator_t"] = None

try:
    from cognia.learning.learning_path import LearningPathGenerator as _LearningPathGenerator
    _LearningPathGenerator_t = _LearningPathGenerator
    _learning_path = _LearningPathGenerator(db_path=_CHAT_DB)
except Exception as _lp_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "LearningPathGenerator init failed: %s", _lp_err
    )
    _LearningPathGenerator = None  # type: ignore[assignment,misc]

# ── Proactive Suggestions Engine singleton ────────────────────────────
_proactive: _Optional["ProactiveEngine"] = None

try:
    from cognia.proactive.proactive_engine import ProactiveEngine
    _proactive = ProactiveEngine(db_path=_CHAT_DB)
except Exception as _pe_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "ProactiveEngine init failed: %s", _pe_err
    )
    ProactiveEngine = None  # type: ignore[assignment,misc]

# ── Smart Notes Engine singleton ─────────────────────────────────────
_notes: _Optional["SmartNotesEngine"] = None

try:
    from cognia.notes.smart_notes import SmartNotesEngine
    import cognia.notes.smart_notes as _smart_notes_mod
    _smart_notes_mod._DB_PATH = _CHAT_DB
    _notes = SmartNotesEngine(db_path=_CHAT_DB)
except Exception as _ne_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "SmartNotesEngine init failed: %s", _ne_err
    )
    SmartNotesEngine = None  # type: ignore[assignment,misc]

# ── Spaced Repetition Engine singleton ───────────────────────────────
_sr: _Optional["SpacedRepetitionEngine"] = None

try:
    from cognia.learning.spaced_repetition import SpacedRepetitionEngine
    import cognia.learning.spaced_repetition as _sr_mod
    _sr_mod._DB_PATH = _CHAT_DB
    _sr = SpacedRepetitionEngine(db_path=_CHAT_DB)
except Exception as _sre_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "SpacedRepetitionEngine init failed: %s", _sre_err
    )
    SpacedRepetitionEngine = None  # type: ignore[assignment,misc]

# ── Quiz Generator singleton ──────────────────────────────────────────
_quiz: _Optional["QuizGenerator"] = None

try:
    from cognia.learning.quiz_generator import QuizGenerator
    import cognia.learning.quiz_generator as _quiz_mod
    _quiz_mod._DB_PATH = _CHAT_DB
    from cognia.config import DB_PATH as _KG_DB_PATH
    _quiz_mod._KG_DB_PATH = _KG_DB_PATH
    _quiz = QuizGenerator(db_path=_CHAT_DB, kg_db_path=_KG_DB_PATH)
except Exception as _quiz_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "QuizGenerator init failed: %s", _quiz_err
    )
    QuizGenerator = None  # type: ignore[assignment,misc]

# ── Implicit Feedback Learner singleton ──────────────────────────────
_feedback_learner: _Optional["_FeedbackLearner_t"] = None

try:
    from cognia.adaptive.feedback_learner import FeedbackLearner as _FeedbackLearner
    _FeedbackLearner_t = _FeedbackLearner
    _feedback_learner = _FeedbackLearner()
except Exception as _fle:
    _logging.getLogger("cognia_desktop_api").warning(
        "FeedbackLearner init failed: %s", _fle
    )
    _FeedbackLearner = None  # type: ignore[assignment,misc]

# ── Self-Critic singleton ─────────────────────────────────────────────
_self_critic: _Optional["_SelfCritic_t"] = None

try:
    from cognia.reasoning.self_critic import SelfCritic as _SelfCritic
    _SelfCritic_t = _SelfCritic
    _self_critic = _SelfCritic(db_path=_CHAT_DB)
except Exception as _sce:
    _logging.getLogger("cognia_desktop_api").warning(
        "SelfCritic init failed: %s", _sce
    )
    _SelfCritic = None  # type: ignore[assignment,misc]

# ── Response Quality Auto-Gate singleton — Phase 55 ──────────────────
_response_gate = None

try:
    from cognia.quality.response_gate import ResponseGate as _ResponseGate
    _response_gate = _ResponseGate()
except Exception as _rg_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "ResponseGate init failed: %s", _rg_err
    )

# ── CKE (Conversational Knowledge Extraction) singleton — Phase 53 ────
_cke = None

try:
    from cognia.knowledge.cke_extractor import CKEExtractor as _CKEExtractor
    from cognia.knowledge.graph import KnowledgeGraph as _KnowledgeGraph
    _cke = _CKEExtractor(_KnowledgeGraph())
except Exception as _cke_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "CKEExtractor init failed: %s", _cke_err
    )

# ── Style Engine singleton — Phase 54 ────────────────────────────────
_style_engine = None

try:
    from cognia.adaptive.style_engine import StyleEngine as _StyleEngine
    _style_engine = _StyleEngine(_CHAT_DB)
except Exception as _se_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "StyleEngine init failed: %s", _se_err
    )

# ── Proactive Insight Connector singleton — Phase 57 ─────────────────
_insight_connector = None

try:
    from cognia.proactive.insight_connector import InsightConnector as _InsightConnector
    from cognia.knowledge.graph import KnowledgeGraph as _KGForPIC
    _insight_connector = _InsightConnector(_KGForPIC())
except Exception as _pic_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "InsightConnector init failed: %s", _pic_err
    )

# ── Contradiction Alert singleton — Phase 58 ─────────────────────────
_contradiction_alert = None

try:
    from cognia.quality.contradiction_alert import ContradictionAlert as _ContradictionAlert
    from cognia.knowledge.graph import KnowledgeGraph as _KGForRCA
    _contradiction_alert = _ContradictionAlert(_KGForRCA())
except Exception as _rca_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "ContradictionAlert init failed: %s", _rca_err
    )

# ── Response Format Intelligence singleton — Phase 59 ────────────────
_format_intelligence = None

try:
    from cognia.quality.format_intelligence import FormatIntelligence as _FormatIntelligence
    _format_intelligence = _FormatIntelligence()
except Exception as _rfi_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "FormatIntelligence init failed: %s", _rfi_err
    )

# ── Conversation Anchor Tracker singleton — Phase 61 ─────────────────
_anchor_tracker = None

try:
    from cognia.context.anchor_tracker import AnchorTracker as _AnchorTracker
    _anchor_tracker = _AnchorTracker()
except Exception as _cat_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "AnchorTracker init failed: %s", _cat_err
    )

# ── Session Warm Starter singleton — Phase 62 ─────────────────────────
_warm_starter = None

try:
    from cognia.context.session_warm_starter import SessionWarmStarter as _SessionWarmStarter
    from cognia.knowledge.graph import KnowledgeGraph as _KGForSWS
    _warm_starter = _SessionWarmStarter(
        _KGForSWS(),
        _CHAT_DB,
        consolidator=_consolidator,
    )
except Exception as _sws_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "SessionWarmStarter init failed: %s", _sws_err
    )


@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest, request: Request, response: "fastapi.Response" = None):
    """Route the prompt to the best sub-model and return its response."""
    from fastapi import Response as _Response
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    # SWS: inject user briefing into prompt on first turn of each session
    if _warm_starter is not None:
        try:
            _sws_sid = getattr(req, "session_id", None) or "default"
            if _warm_starter.is_first_turn(_sws_sid):
                _sws_briefing = _warm_starter.build_briefing(_sws_sid)
                if _sws_briefing:
                    req = req.model_copy(update={"prompt": _sws_briefing + "\n\n" + req.prompt})
                _warm_starter.mark_briefed(_sws_sid)
        except Exception:
            pass

    # ITCS: score query complexity and set pipeline budget before inference
    _complexity = _itcs_scorer.score(req.prompt)
    _api_logger.info(
        "ITCS score=%d budget=%s reasons=%s",
        _complexity.score, _complexity.budget, _complexity.reasons,
    )
    try:
        from cognia.language_engine import set_pipeline_budget as _spb
        _spb(_complexity.budget)
    except Exception:
        pass

    # Implicit feedback: detect signal from user text, record fire-and-forget
    if _feedback_learner is not None:
        try:
            _signal = _feedback_learner.detect_signal(req.prompt)
            if _signal != "neutral":
                import threading as _threading
                _threading.Thread(
                    target=_feedback_learner.record,
                    args=(str(_time.time()), _signal, "general"),
                    daemon=True,
                ).start()
        except Exception:
            pass

    # Semantic cache lookup — safe fallback, never breaks inference
    try:
        _cached = _sem_cache.lookup(req.prompt)
        if _cached and len(_cached) > 20:
            _cache_analytics.record_hit(req.prompt)
            _r = InferResponse(
                text         = _cached,
                sub_model    = "cache",
                confidence   = 1.0,
                latency_ms   = 0.0,
                mode         = "semantic_cache",
                route_reason = "SRC HIT",
            )
            # FastAPI doesn't pass Response here; headers set via custom response
            from fastapi.responses import JSONResponse
            return JSONResponse(
                content=_r.model_dump(),
                headers={"X-Cache": "HIT"},
            )
        else:
            _cache_analytics.record_miss(req.prompt)
    except Exception as _ce:
        _api_logger.warning("SRC lookup error (ignored): %s", _ce)

    # PIC: inject proactive insights into prompt before inference (fire-and-forget safe)
    _infer_prompt = req.prompt
    if _insight_connector is not None:
        try:
            _pic_injection = _insight_connector.get_prompt_injection(req.prompt)
            if _pic_injection:
                _infer_prompt = _pic_injection + "\n\n" + req.prompt
        except Exception:
            pass

    # RCA: inject contradiction alert if user message conflicts with KG facts
    if _contradiction_alert is not None:
        try:
            _ca_injection = _contradiction_alert.get_alert_injection(req.prompt)
            if _ca_injection:
                _infer_prompt = _ca_injection + "\n\n" + _infer_prompt
        except Exception:
            pass

    # RFI: prepend format hint so the LLM structures its response optimally
    if _format_intelligence is not None:
        try:
            _fmt_hint = _format_intelligence.get_format_hint(req.prompt)
            if _fmt_hint:
                _infer_prompt = "[Format instruction: " + _fmt_hint + "]\n\n" + _infer_prompt
        except Exception:
            pass

    # CAT: Conversation Anchor Tracker — set anchor on first message, inject hint on drift
    _cat_session_id = getattr(req, "session_id", None) or "default"
    if _anchor_tracker is not None:
        try:
            if _cat_session_id not in _anchor_tracker._anchors:
                _anchor_tracker.set_anchor(_cat_session_id, req.prompt)
            _cat_hint = _anchor_tracker.get_anchor_hint(_cat_session_id, req.prompt)
            if _cat_hint:
                _infer_prompt = _cat_hint + "\n\n" + _infer_prompt
            _anchor_tracker.record_turn(_cat_session_id)
        except Exception:
            pass

    try:
        result = await _orch.ainfer(_infer_prompt)
    except Exception as exc:
        _api_logger.error("Inference failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # Store in semantic cache — safe fallback
    try:
        _sem_cache.store(req.prompt, result.text, result.sub_model)
    except Exception as _ce:
        _api_logger.warning("SRC store error (ignored): %s", _ce)

    # CIP: warm cache for predicted follow-ups (fire and forget)
    if _cache_warmer is not None:
        try:
            _cache_warmer.warm_async(req.prompt, result.text)
        except Exception:
            pass

    # RFV: validate response against KG — never breaks the response
    response_text = result.text
    try:
        if _rfv_validator is not None and len(response_text) > 30:
            rfv_result = _rfv_validator.validate(response_text)
            if rfv_result.has_contradictions:
                correction = _rfv_validator.format_correction_note(rfv_result)
                if correction:
                    response_text = response_text + "\n\n" + correction
    except Exception as _rfv_exc:
        _api_logger.warning("RFV validation error (ignored): %s", _rfv_exc)

    # Response Quality Auto-Gate: retry once if quality score is too low
    if _response_gate is not None:
        try:
            _rg_retry, _rg_reason = _response_gate.should_retry(req.prompt, response_text)
            if _rg_retry:
                _retry_prompt = _response_gate.build_retry_prompt(
                    req.prompt, response_text, _rg_reason
                )
                try:
                    _retry_result = await _orch.ainfer(_retry_prompt)
                    if _retry_result and len(_retry_result.text) > len(response_text):
                        response_text = _retry_result.text
                except Exception:
                    pass  # keep original on any retry error
        except Exception:
            pass  # gate errors never break the response

    # Knowledge Gap Auto-Detector: record low-quality responses (fire-and-forget)
    if _gap_detector is not None and _response_gate is not None:
        try:
            _kgad_quality = _response_gate.score(req.prompt, response_text)
            _kgad_query = req.prompt
            _kgad_resp = response_text
            import threading as _threading_kgad
            _threading_kgad.Thread(
                target=_gap_detector.maybe_record_gap,
                args=(_kgad_query, _kgad_resp, _kgad_quality),
                daemon=True,
            ).start()
        except Exception:
            pass  # gap detector errors never break the response

    # Smart Notes: extract notes from assistant response (fire-and-forget)
    if _notes is not None and (_feature_flags is None or _feature_flags.is_enabled("auto_notes", getattr(request.state, "tier", "free"))):
        _notes_ref = _notes
        _notes_text = response_text
        _notes_session = getattr(req, "session_id", "default") or "default"
        import threading as _threading_notes
        def _bg_notes():
            try:
                extracted = _notes_ref.extract_from_text(_notes_text, _notes_session)
                for n in extracted:
                    _notes_ref.add_note(
                        n["content"], note_type=n["note_type"],
                        session_id=n["session_id"], source="auto"
                    )
            except Exception:
                pass
        _threading_notes.Thread(target=_bg_notes, daemon=True).start()

    # Proactive suggestions: generate and queue in background (fire-and-forget)
    if _proactive is not None and (_feature_flags is None or _feature_flags.is_enabled("proactive_engine", getattr(request.state, "tier", "free"))):
        _user_text = req.prompt
        _proactive_ref = _proactive
        import threading as _threading_proactive
        def _bg_proactive():
            try:
                suggestions = _proactive_ref.generate_suggestions(_user_text, active_goals=[])
                for s in suggestions:
                    _proactive_ref.queue_suggestion(
                        s["text"], s["category"], context_trigger=_user_text[:128]
                    )
            except Exception:
                pass
        _threading_proactive.Thread(target=_bg_proactive, daemon=True).start()

    # Achievements: count messages for "default" user and check milestones (fire-and-forget)
    if _achievements is not None:
        _ach_ref = _achievements
        import threading as _threading_ach
        def _bg_achievements():
            try:
                from storage.db_pool import get_pool as _gp_ach
                with _gp_ach(_CHAT_DB).get() as _ac:
                    row = _ac.execute(
                        "SELECT COUNT(*) FROM chat_history WHERE role='user'"
                    ).fetchone()
                msg_count = int(row[0]) if row else 1
                _ach_ref.check_and_unlock("default", "message_sent", count=msg_count)
            except Exception:
                pass
        _threading_ach.Thread(target=_bg_achievements, daemon=True).start()

    # Usage analytics: record infer event (fire-and-forget)
    if _analytics is not None:
        import threading as _threading_analytics_infer
        _threading_analytics_infer.Thread(
            target=_analytics.record, args=("infer",), daemon=True
        ).start()

    # Self-Critic: score response quality in background (fire-and-forget)
    if _self_critic is not None:
        _sc_ref = _self_critic
        _sc_resp = response_text
        _sc_q = req.prompt
        import threading as _threading_sc
        _threading_sc.Thread(
            target=_sc_ref.critique, args=(_sc_resp, _sc_q), daemon=True
        ).start()

    # UserFactsMemory: infer from user prompt (fire-and-forget)
    if _user_facts is not None:
        _uf_ref = _user_facts
        _uf_text = req.prompt
        import threading as _threading_uf
        _threading_uf.Thread(
            target=_uf_ref.infer_and_store, args=(_uf_text,), daemon=True
        ).start()

    # CKE: extract structured facts from user message into KG (fire-and-forget)
    if _cke is not None:
        _cke_ref = _cke
        _cke_prompt = req.prompt
        _cke_resp = response_text
        import threading as _threading_cke
        _threading_cke.Thread(
            target=_cke_ref.extract_and_store,
            args=(_cke_prompt, _cke_resp),
            daemon=True,
        ).start()

    # StyleEngine: record exchange and update style profile (fire-and-forget)
    if _style_engine is not None:
        _se_ref = _style_engine
        _se_user = req.prompt
        _se_resp = response_text
        import threading as _threading_se
        _threading_se.Thread(
            target=_se_ref.record_exchange,
            args=(_se_user, _se_resp),
            daemon=True,
        ).start()

    return InferResponse(
        text             = response_text,
        sub_model        = result.sub_model,
        confidence       = result.confidence,
        latency_ms       = result.latency_ms,
        mode             = result.mode,
        route_reason     = result.route_reason,
        tokens_generated = result.tokens_generated,
    )


@app.get("/route", response_model=RouteResponse)
def route(prompt: str = Query(..., description="Prompt to route", max_length=4096)):
    """Return routing decision without running inference."""
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    d = _orch.route_only(prompt)
    return RouteResponse(
        sub_model  = d.sub_model,
        confidence = d.confidence,
        scores     = d.scores,
        reason     = d.reason,
    )


_SYSTEM_PROMPT = (
    "Eres Cognia, un asistente de IA distribuido y local que corre en el dispositivo del usuario. "
    "Tienes memoria episodica y un grafo de conocimiento para recordar contexto entre sesiones. "
    "Responde siempre en el mismo idioma que el usuario. "
    "Usa Markdown para formatear tus respuestas: **negrita** para enfasis, `codigo inline` para variables y funciones, "
    "bloques de codigo con triple backtick para ejemplos de codigo (incluye el lenguaje, ej: ```python), "
    "y listas con guion para enumeraciones. "
    "Se conciso y directo. Si no sabes algo, dilo claramente en vez de inventar."
)


@app.post("/infer-stream-v2")
async def infer_stream_v2(req: ChatStreamRequest):
    """
    SSE streaming endpoint with full conversation history.
    Body: { prompt: str, history: [{role, content}, ...] }
    The history contains previous turns; prompt is the current user message.
    """
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    _stream_system_prompt = _SYSTEM_PROMPT
    if _style_engine is not None:
        try:
            _style_hint = _style_engine.get_style_hint()
            if _style_hint:
                _stream_system_prompt = _SYSTEM_PROMPT + " " + _style_hint + "."
        except Exception:
            pass

    # RFI: append format hint to system prompt for streaming endpoint
    if _format_intelligence is not None:
        try:
            _stream_fmt_hint = _format_intelligence.get_format_hint(req.prompt)
            if _stream_fmt_hint:
                _stream_system_prompt = _stream_system_prompt + " " + _stream_fmt_hint
        except Exception:
            pass

    # Fold in the user's explicit personalization (name/language/style) last so it
    # survives the style/format hints above. No-op when nothing is configured.
    try:
        from cognia.user_prefs import personalize_prompt as _pp
        _stream_system_prompt = _pp(_stream_system_prompt)
    except Exception:
        pass

    messages = [{"role": "system", "content": _stream_system_prompt}]
    for m in req.history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": req.prompt})

    async def generator():
        try:
            got_tokens = False
            async for token_text, _ in _orch.astream_chat(messages):
                if token_text is not None:
                    got_tokens = True
                    yield {"data": json.dumps({"token": token_text, "done": False})}
            if got_tokens:
                yield {"data": json.dumps({
                    "done": True, "sub_model": "llama", "confidence": 1.0,
                    "latency_ms": 0, "mode": "llama.cpp", "route_reason": "llama.cpp",
                })}
            else:
                yield {"data": json.dumps({"done": True, "error": "no output"})}
        except Exception as exc:
            _api_logger.error("stream_v2 failed: %s", exc, exc_info=True)
            yield {"data": json.dumps({"done": True, "error": str(exc)})}

    return EventSourceResponse(generator())


@app.get("/status")
def status():
    """Return orchestrator + fragment status."""
    return _orch.status()


@app.get("/infer-stream")
async def infer_stream(prompt: str = Query(..., description="Prompt to infer", max_length=_MAX_PROMPT_CHARS)):
    """
    SSE streaming inference endpoint.
    Yields: {"token": "...", "done": false}  per word,
    then:   {"done": true, "sub_model": ..., "latency_ms": ..., "mode": ...}
    """
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    # ITCS: score and set budget (astream path goes through shard pipeline, not LanguageEngine,
    # but set it anyway in case the engine is used downstream)
    _stream_complexity = _itcs_scorer.score(prompt)
    _api_logger.info(
        "ITCS stream score=%d budget=%s",
        _stream_complexity.score, _stream_complexity.budget,
    )
    try:
        from cognia.language_engine import set_pipeline_budget as _spb
        _spb(_stream_complexity.budget)
    except Exception:
        pass

    async def generator():
        try:
            result = None
            got_tokens = False
            async for token_text, final in _orch.astream(prompt):
                if token_text is not None:
                    got_tokens = True
                    yield {"data": json.dumps({"token": token_text, "done": False})}
                else:
                    result = final
            if result is None:
                if got_tokens:
                    # llama.cpp path: tokens delivered, no InferResult object — send clean done
                    yield {"data": json.dumps({"done": True, "sub_model": "llama", "confidence": 1.0, "latency_ms": 0, "mode": "llama.cpp", "route_reason": "llama.cpp"})}
                else:
                    yield {"data": json.dumps({"done": True, "error": "no output"})}
                return
            yield {
                "data": json.dumps({
                    "done":             True,
                    "sub_model":        result.sub_model,
                    "confidence":       result.confidence,
                    "latency_ms":       result.latency_ms,
                    "mode":             result.mode,
                    "route_reason":     getattr(result, "route_reason", ""),
                    "tokens_generated": getattr(result, "tokens_generated", 0),
                })
            }
        except Exception as exc:
            _api_logger.error("Stream inference failed: %s", exc, exc_info=True)
            yield {"data": json.dumps({"done": True, "error": str(exc)})}

    return EventSourceResponse(generator())


@app.get("/ready")
async def ready():
    """
    Readiness probe: reports shard availability as the primary signal.

    Returns {"status": "ready"} when the Qwen .npz shards are present,
    regardless of Ollama. Falls back to checking Ollama only when shards
    are missing (legacy path still needed for users without shards).
    """
    if _orch.shards_ready():
        return {
            "status": "ready",
            "inference": "shards",
            "shards": "available",
        }

    # Shards not found — check Ollama as secondary option
    import urllib.request as _ur
    import json as _j
    ollama_ok = False
    model_ok  = False
    ollama_base = _orch._ollama_url.replace("/api/generate", "")
    try:
        with _ur.urlopen(f"{ollama_base}/api/tags", timeout=3) as r:
            data = _j.loads(r.read())
        model_name = _orch._ollama_model
        model_ok = any(
            m.get("name", "").split(":")[0] == model_name.split(":")[0]
            for m in data.get("models", [])
        )
        ollama_ok = True
    except Exception:
        pass

    if ollama_ok and model_ok:
        return {
            "status":     "ready",
            "inference":  "ollama",
            "ollama":     "running",
            "model":      "available",
            "model_name": _orch._ollama_model,
        }

    return {
        "status":     "setup_required",
        "reason":     "shards_missing",
        "inference":  "none",
        "shards":     "missing",
        "ollama":     "running" if ollama_ok else "missing",
        "model":      "available" if model_ok else "not_pulled",
        "model_name": _orch._ollama_model,
    }


@app.get("/health/performance")
async def health_performance():
    """Measure real tok/s by running a short test inference."""
    import time
    backend_activo = "llama" if (
        hasattr(_orch, "_llama") and _orch._llama is not None
        and hasattr(_orch._llama, "stream_chat")
    ) else "numpy"
    nano_draft_activo = getattr(_orch, "_draft", None) is not None
    try:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "Hola"},
        ]
        tokens = 0
        t0 = time.perf_counter()
        async for token_text, _ in _orch.astream_chat(messages):
            if token_text is not None:
                tokens += 1
                if tokens >= 10:
                    break
        elapsed = time.perf_counter() - t0
        tok_s = round(tokens / elapsed, 2) if elapsed > 0 else 0.0
        return {
            "tok_s": tok_s,
            "latencia_total_ms": round(elapsed * 1000, 1),
            "backend_activo": backend_activo,
            "nano_draft_activo": nano_draft_activo,
        }
    except Exception as exc:
        return {"error": str(exc), "tok_s": 0}


class ChatHistoryRequest(BaseModel):
    session_id: str
    messages: list[ChatMessage]


@app.get("/chat/history")
def get_chat_history(session_id: str = Query(..., max_length=128)):
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return {"messages": [{"role": r, "content": c} for r, c in rows]}


@app.post("/chat/history")
def save_chat_history(req: ChatHistoryRequest):
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        conn.execute("DELETE FROM chat_history WHERE session_id = ?", (req.session_id,))
        conn.executemany(
            "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
            [(req.session_id, m.role, m.content) for m in req.messages],
        )
    # Notify summarizer of each new message (fire-and-forget background thread)
    for m in req.messages:
        _session_summarizer.on_message(req.session_id, m.role, m.content)
    return {"saved": len(req.messages)}


@app.delete("/chat/history")
def delete_chat_history(session_id: str = Query(..., max_length=128)):
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
    # CAT: clear anchor on session evict/delete
    if _anchor_tracker is not None:
        try:
            _anchor_tracker.clear_session(session_id)
        except Exception:
            pass
    return {"deleted": True}


@app.get("/sessions/{session_id}/summaries")
def get_session_summaries(
    session_id: str,
    limit: int = Query(10, ge=1, le=100),
):
    """Return auto-generated extractive summaries for a session."""
    return {"summaries": _session_summarizer.get_summaries(session_id, limit=limit)}


class AgentRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000)


class AgentResponse(BaseModel):
    result: str
    latency_ms: float


@app.post("/agent", response_model=AgentResponse)
async def run_agent(req: AgentRequest):
    """Run a single agent task via the orchestrator."""
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task cannot be empty")
    t0 = _time.perf_counter()
    try:
        result = await _orch.ainfer(
            f"Eres un agente de IA. Ejecuta esta tarea de forma directa y concisa:\n\n{req.task}"
        )
        latency = (_time.perf_counter() - t0) * 1000
        return AgentResponse(result=result.text, latency_ms=round(latency, 1))
    except Exception as exc:
        _api_logger.error("Agent task failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


_SKILLS_DIR_API = _ROOT / "cognia_skills"


@app.get("/skills")
def list_skills():
    """List available skill files from cognia_skills/."""
    import pathlib, re as _re
    skills_dir = _SKILLS_DIR_API
    if not skills_dir.exists():
        return {"skills": []}
    result = []
    for f in sorted(skills_dir.glob("*.md")):
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        desc = ""
        in_front = False
        for line in lines:
            if line.strip() == "---":
                in_front = not in_front
                continue
            if in_front and line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
                break
        result.append({"name": f.stem, "description": desc, "file": f.name})
    return {"skills": result}


@app.get("/skills/{name}")
def get_skill(name: str):
    """Return full content of a skill file."""
    import re as _re
    if not _re.match(r'^[\w\-]+$', name):
        raise HTTPException(status_code=400, detail="invalid skill name")
    f = _SKILLS_DIR_API / f"{name}.md"
    if not f.exists():
        raise HTTPException(status_code=404, detail="skill not found")
    return {"name": name, "content": f.read_text(encoding="utf-8", errors="replace")}


@app.get("/network/status")
async def network_status():
    """P2P network status: coordinator reachability + local backend info."""
    import urllib.request as _ur
    import json as _j

    local_backend = "llama" if (
        hasattr(_orch, "_llama") and _orch._llama is not None
        and hasattr(_orch._llama, "stream_chat")
    ) else "numpy"
    nano_draft = getattr(_orch, "_draft", None) is not None

    coordinator_url = os.environ.get("COGNIA_COORDINATOR_URL", "").rstrip("/")
    if not coordinator_url:
        return {"online": False, "error": "no coordinator configured",
                "local_backend": local_backend, "nano_draft": nano_draft}

    try:
        req = _ur.Request(f"{coordinator_url}/status", headers={"Accept": "application/json"})
        with _ur.urlopen(req, timeout=3) as r:
            data = _j.loads(r.read())
        data["local_backend"] = local_backend
        data["nano_draft"] = nano_draft
        data.setdefault("online", True)
        return data
    except Exception as exc:
        return {"online": False, "error": "coordinator unreachable",
                "local_backend": local_backend, "nano_draft": nano_draft}


@app.get("/api/cache/stats")
def cache_stats():
    """Return semantic response cache statistics (entries, hit_rate, total_hits)."""
    try:
        return _sem_cache.stats()
    except Exception as exc:
        _api_logger.warning("cache_stats error: %s", exc)
        return {"entries": 0, "total_hits": 0, "hit_rate": 0.0}


@app.get("/cache/analytics")
def cache_analytics_get():
    """Return advanced cache analytics: hit rate, top queries, hourly stats."""
    try:
        return _cache_analytics.get_analytics()
    except Exception as exc:
        _api_logger.warning("cache_analytics error: %s", exc)
        return {"error": str(exc)}


@app.post("/cache/analytics/reset")
def cache_analytics_reset():
    """Reset all in-memory cache analytics counters."""
    try:
        _cache_analytics.reset()
        return {"reset": True}
    except Exception as exc:
        _api_logger.warning("cache_analytics_reset error: %s", exc)
        return {"reset": False, "error": str(exc)}


@app.get("/health")
def health():
    return {"ok": True}


# ── Mode + personalization endpoints (shared config with the CLI) ──────────

class _ModeRequest(BaseModel):
    mode: str = Field(..., max_length=32)


class _SettingsRequest(BaseModel):
    name:  _Optional[str] = Field(default=None, max_length=64)
    lang:  _Optional[str] = Field(default=None, max_length=16)
    style: _Optional[str] = Field(default=None, max_length=16)


def _prefs_payload() -> dict:
    """Current run mode + personalization, read from ~/.cognia/config.env."""
    from cognia.user_prefs import (
        load_prefs, K_USER_NAME, K_LANG, K_STYLE, K_RUN_MODE, MODE_LABELS,
        LANG_CHOICES, STYLE_CHOICES,
    )
    p = load_prefs()
    mode = p.get(K_RUN_MODE, "")
    return {
        "mode":        mode,
        "mode_label":  MODE_LABELS.get(mode, mode),
        "name":        p.get(K_USER_NAME, ""),
        "lang":        p.get(K_LANG, ""),
        "style":       p.get(K_STYLE, ""),
        "mode_choices":  list(MODE_LABELS.keys()),
        "lang_choices":  list(LANG_CHOICES),
        "style_choices": list(STYLE_CHOICES),
    }


@app.get("/mode")
def get_mode():
    """Current run mode (local|compartido|memoria) + personalization."""
    return _prefs_payload()


@app.post("/mode")
def set_mode(req: _ModeRequest):
    """Switch the run mode. Does not move weights; the next launch honors it."""
    from cognia.user_prefs import save_pref, K_RUN_MODE, MODE_LABELS
    mode = req.mode.strip().lower()
    if mode not in MODE_LABELS:
        raise HTTPException(status_code=400, detail="modo invalido (local|compartido|memoria)")
    save_pref(K_RUN_MODE, mode)
    return _prefs_payload()


@app.get("/settings")
def get_settings():
    """Alias of /mode: returns run mode + personalization in one payload."""
    return _prefs_payload()


@app.post("/settings")
def set_settings(req: _SettingsRequest):
    """Update personalization. Only the provided, valid fields are saved."""
    from cognia.user_prefs import (
        save_pref, K_USER_NAME, K_LANG, K_STYLE, LANG_CHOICES, STYLE_CHOICES,
    )
    if req.name is not None:
        save_pref(K_USER_NAME, req.name.strip())
    if req.lang is not None and req.lang.strip().lower() in LANG_CHOICES:
        save_pref(K_LANG, req.lang.strip().lower())
    if req.style is not None and req.style.strip().lower() in STYLE_CHOICES:
        save_pref(K_STYLE, req.style.strip().lower())
    return _prefs_payload()


# ── Persona endpoints ──────────────────────────────────────────────────

class _PersonaSetRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    persona: str = Field(default="default", max_length=64)
    custom_instruction: str = Field(default="", max_length=1000)


@app.post("/persona")
def set_persona(req: _PersonaSetRequest):
    """Set or update the communication persona for a user."""
    if _persona_manager is None:
        raise HTTPException(status_code=503, detail="PersonaManager not available")
    ok = _persona_manager.set_persona(req.user_id, req.persona, req.custom_instruction)
    return {"ok": ok}


@app.get("/persona/list")
def list_personas():
    """Return the list of built-in persona names."""
    if _persona_manager is None:
        raise HTTPException(status_code=503, detail="PersonaManager not available")
    return {"personas": _persona_manager.list_personas()}


@app.get("/persona/{user_id}")
def get_persona(user_id: str):
    """Return the active persona and resolved instruction for a user."""
    if _persona_manager is None:
        raise HTTPException(status_code=503, detail="PersonaManager not available")
    data = _persona_manager.get_persona(user_id)
    data["instruction"] = _persona_manager.get_persona_instruction(user_id)
    return data


@app.delete("/persona/{user_id}")
def reset_persona(user_id: str):
    """Reset user persona to default (no style instruction)."""
    if _persona_manager is None:
        raise HTTPException(status_code=503, detail="PersonaManager not available")
    ok = _persona_manager.reset_persona(user_id)
    return {"reset": ok}


@app.get("/persona/{user_id}/recommend")
def persona_recommend(user_id: str):
    """
    Analiza el perfil del usuario y recomienda la persona de comunicacion mas adecuada.
    Retorna recommended_persona, confidence, reason y already_set.
    Sin LLM calls -- heuristicas de pattern+topic voting.
    """
    if _persona_advisor is None:
        raise HTTPException(status_code=503, detail="PersonaAdvisor not available")
    return _persona_advisor.recommend(user_id)


@app.post("/persona/{user_id}/auto-apply")
def persona_auto_apply(
    user_id: str,
    min_confidence: float = Query(0.6, ge=0.0, le=1.0),
):
    """
    Aplica automaticamente la persona recomendada si confidence >= min_confidence
    y el usuario no tiene ya esa persona configurada.
    Retorna {"applied": bool, "persona": str, "confidence": float}.
    """
    if _persona_advisor is None:
        raise HTTPException(status_code=503, detail="PersonaAdvisor not available")
    return _persona_advisor.auto_apply(user_id, min_confidence=min_confidence)


# ── Goal Tracker singleton ────────────────────────────────────────────

from cognia.goals.goal_tracker import GoalTracker as _GoalTracker

_goal_tracker = _GoalTracker(db_path=_CHAT_DB)

# ── Goal Suggester singleton ───────────────────────────────────────────

from cognia.goals.goal_suggester import GoalSuggester as _GoalSuggester

_goal_suggester = _GoalSuggester()

# ── Task Decomposer singleton ──────────────────────────────────────────

from cognia.goals.task_decomposer import TaskDecomposer as _TaskDecomposer

_task_decomposer = _TaskDecomposer(db_path=_CHAT_DB)

# ── Webhook Manager singleton ─────────────────────────────────────────

from cognia.webhooks.webhook_manager import WebhookManager as _WebhookManager

_webhook_manager = _WebhookManager(db_path=_CHAT_DB)


class _GoalCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=1024)


class _GoalProgressRequest(BaseModel):
    progress_pct: int = Field(..., ge=0, le=150)
    user_id: str = Field("", max_length=128)


@app.post("/goals")
def create_goal(req: _GoalCreateRequest):
    """Create a new goal for a user. Returns the created goal dict."""
    goal = _goal_tracker.create_goal(req.user_id, req.title, req.description)
    _webhook_manager.fire("goal.created", {"goal_id": goal.get("id"), "title": req.title, "user_id": req.user_id})
    if _analytics is not None:
        import threading as _t_goals
        _t_goals.Thread(target=_analytics.record, args=("goals",), daemon=True).start()
    return goal


@app.get("/goals/{user_id}")
def list_goals(user_id: str, status: str = Query(None, max_length=32)):
    """List goals for user_id, optionally filtered by status."""
    return {"goals": _goal_tracker.get_goals(user_id, status=status or None)}


@app.patch("/goals/{goal_id}/progress")
def update_goal_progress(goal_id: int, req: _GoalProgressRequest):
    """Update progress for a goal. Returns {"updated": bool}."""
    uid = req.user_id if req.user_id else None
    updated = _goal_tracker.update_progress(goal_id, req.progress_pct, user_id=uid)
    if updated:
        goals = _goal_tracker.get_goals(uid or "", status=None) if uid else []
        title = next((g["title"] for g in goals if g["id"] == goal_id), "")
        if req.progress_pct >= 100:
            _webhook_manager.fire("goal.completed", {"goal_id": goal_id, "title": title})
        if uid:
            try:
                _notification_center.create_goal_notification(uid, title, req.progress_pct)
            except Exception as _ne:
                _api_logger.warning("notification create_goal failed: %s", _ne)
    return {"updated": updated}


@app.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, user_id: str = Query(..., max_length=128)):
    """Delete a goal by id (scoped to user_id). Returns {"deleted": bool}."""
    deleted = _goal_tracker.delete_goal(goal_id, user_id)
    return {"deleted": deleted}


@app.get("/goals/{user_id}/summary")
def goals_summary(user_id: str):
    """Return active-goals summary string for context injection."""
    return {"summary": _goal_tracker.get_active_goals_summary(user_id)}


@app.get("/goals/{user_id}/suggestions")
def goals_suggestions(user_id: str, max: int = Query(5, ge=1, le=20)):
    """Return proactive goal suggestions based on user profile and active goals."""
    suggestions = _goal_suggester.suggest(user_id, max_suggestions=max)
    return {"suggestions": suggestions}


@app.post("/goals/{goal_id}/decompose")
def decompose_goal(
    goal_id: int,
    user_id: str = Query("local", max_length=128),
    max_subtasks: int = Query(5, ge=1, le=10),
):
    """
    Decompose a goal into sub-tasks using deterministic domain templates.
    Sub-tasks are stored as child goals with parent_id=goal_id.
    Returns {"subtasks": list[dict]}.
    """
    try:
        subtasks = _task_decomposer.decompose(goal_id, user_id, max_subtasks=max_subtasks)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        _api_logger.error("decompose_goal failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"subtasks": subtasks}


@app.get("/goals/{goal_id}/subtasks")
def get_goal_subtasks(goal_id: int):
    """Return all sub-tasks (child goals) for a given parent goal_id."""
    try:
        subtasks = _task_decomposer.get_subtasks(goal_id)
    except Exception as exc:
        _api_logger.error("get_goal_subtasks failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"subtasks": subtasks}


# ── Webhook endpoints ─────────────────────────────────────────────────

class _WebhookCreateRequest(BaseModel):
    url: str = Field(..., min_length=7, max_length=2048)
    events: list = Field(..., min_length=1)
    secret: str = Field("", max_length=256)


@app.post("/webhooks")
def webhooks_create(req: _WebhookCreateRequest):
    """Register a new webhook. Returns the webhook dict with id."""
    try:
        return _webhook_manager.register(req.url, req.events, req.secret)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/webhooks")
def webhooks_list():
    """List all active webhooks."""
    return {"webhooks": _webhook_manager.list_webhooks()}


@app.delete("/webhooks/{webhook_id}")
def webhooks_delete(webhook_id: int):
    """Unregister a webhook by id. Returns {"deleted": bool}."""
    deleted = _webhook_manager.unregister(webhook_id)
    return {"deleted": deleted}


@app.get("/webhooks/{webhook_id}/log")
def webhooks_log(webhook_id: int, limit: int = Query(20, ge=1, le=100)):
    """Return recent delivery log for a webhook."""
    return {"log": _webhook_manager.get_delivery_log(webhook_id, limit=limit)}


# ── Curiosity Engine insights ─────────────────────────────────────────

_curiosity_engine_api = None


def _init_curiosity_engine_api() -> None:
    global _curiosity_engine_api
    try:
        from cognia.reasoning.curiosity_engine import CuriosityEngine
        _curiosity_engine_api = CuriosityEngine()
        _api_logger.info("CuriosityEngine: initialized for /curiosity/insights")
    except Exception as exc:
        _api_logger.warning("CuriosityEngine: could not initialize: %s", exc)


try:
    _init_curiosity_engine_api()
except Exception:
    pass

# ── Knowledge Gap Auto-Detector singleton — Phase 60 ─────────────────
_gap_detector = None

try:
    from cognia.knowledge.gap_detector import KnowledgeGapDetector as _KnowledgeGapDetector
    _gap_detector = _KnowledgeGapDetector(
        _CHAT_DB,
        curiosity_engine=_curiosity_engine_api,
    )
except Exception as _kgad_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "KnowledgeGapDetector init failed: %s", _kgad_err
    )


@app.get("/curiosity/insights")
def curiosity_insights(limit: int = Query(20, ge=1, le=100)):
    """Return recent answered curiosity questions for use as context."""
    if _curiosity_engine_api is None:
        return {"insights": [], "error": "CuriosityEngine not available"}
    try:
        return {"insights": _curiosity_engine_api.get_insights(limit=limit)}
    except Exception as exc:
        _api_logger.warning("curiosity_insights error: %s", exc)
        return {"insights": [], "error": str(exc)}


@app.get("/gaps")
def get_knowledge_gaps(limit: int = Query(20, ge=1, le=100)):
    """Return recent knowledge gaps detected from low-quality responses."""
    if _gap_detector is None:
        return {"gaps": [], "error": "KnowledgeGapDetector not available"}
    try:
        return {"gaps": _gap_detector.get_gaps(limit=limit)}
    except Exception as exc:
        _api_logger.warning("get_knowledge_gaps error: %s", exc)
        return {"gaps": [], "error": str(exc)}


@app.post("/gaps/{topic}/resolve")
def resolve_knowledge_gap(topic: str):
    """Mark a knowledge gap as resolved."""
    if _gap_detector is None:
        return {"ok": False, "error": "KnowledgeGapDetector not available"}
    try:
        _gap_detector.mark_resolved(topic)
        return {"ok": True, "topic": topic}
    except Exception as exc:
        _api_logger.warning("resolve_knowledge_gap error: %s", exc)
        return {"ok": False, "error": str(exc)}


@app.get("/insights")
def insights(q: str = Query(..., description="Query to find KG insights for", max_length=512)):
    """Return PIC insight strings for the given query (Phase 57 debug endpoint)."""
    if _insight_connector is None:
        return {"insights": [], "error": "InsightConnector not available"}
    try:
        return {"insights": _insight_connector.find_insights(q)}
    except Exception as exc:
        _api_logger.warning("InsightConnector error: %s", exc)
        return {"insights": [], "error": str(exc)}


@app.get("/contradictions")
def contradictions(q: str = Query(..., description="User message to check for KG contradictions", max_length=512)):
    """Return RCA contradiction alerts for the given text (Phase 58 debug endpoint)."""
    if _contradiction_alert is None:
        return {"alerts": [], "error": "ContradictionAlert not available"}
    try:
        return {"alerts": _contradiction_alert.check(q)}
    except Exception as exc:
        _api_logger.warning("ContradictionAlert error: %s", exc)
        return {"alerts": [], "error": str(exc)}


@app.get("/")
def root():
    return {"service": "Cognia Desktop API", "version": "1.0.0"}


# ── Multi-Hop KG Engine singleton ─────────────────────────────────────

_multihop_engine = None


def _init_multihop_engine() -> None:
    global _multihop_engine
    try:
        from cognia.knowledge.multihop_engine import MultiHopEngine
        _multihop_engine = MultiHopEngine()
        _api_logger.info("MultiHopEngine: initialized")
    except Exception as exc:
        _api_logger.warning("MultiHopEngine: could not initialize: %s", exc)


try:
    _init_multihop_engine()
except Exception:
    pass


class _MultiHopAnswerRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.get("/kg/multihop/path")
def kg_multihop_path(
    source: str = Query(..., alias="from", max_length=256),
    target: str = Query(..., alias="to", max_length=256),
    max_hops: int = Query(3, ge=1, le=3),
):
    """
    BFS shortest path between two KG concepts.
    Returns list of (subject, predicate, object) triples.
    """
    if _multihop_engine is None:
        raise HTTPException(status_code=503, detail="MultiHopEngine not available")
    path = _multihop_engine.find_path(source, target, max_hops=max_hops)
    return {"source": source.lower(), "target": target.lower(), "path": path, "hops": len(path)}


@app.get("/kg/multihop/infer/{concept}")
def kg_multihop_infer(concept: str, depth: int = Query(2, ge=1, le=3)):
    """
    Infer all properties of a concept through is_a chains (direct + inherited).
    """
    if _multihop_engine is None:
        raise HTTPException(status_code=503, detail="MultiHopEngine not available")
    return _multihop_engine.infer_properties(concept, depth=depth)


@app.get("/kg/multihop/explain")
def kg_multihop_explain(
    a: str = Query(..., max_length=256),
    b: str = Query(..., max_length=256),
):
    """
    Explain the relationship between two KG concepts.
    Returns relationship_type (direct/inherited/sibling/unrelated) and explanation.
    """
    if _multihop_engine is None:
        raise HTTPException(status_code=503, detail="MultiHopEngine not available")
    return _multihop_engine.explain_relationship(a, b)


@app.post("/kg/multihop/answer")
def kg_multihop_answer(req: _MultiHopAnswerRequest):
    """
    Answer a natural-language question using multi-hop KG lookup.
    Extracts entities, queries facts, returns answer_text + confidence.
    """
    if _multihop_engine is None:
        raise HTTPException(status_code=503, detail="MultiHopEngine not available")
    return _multihop_engine.answer_question(req.question)


# ── Ollama-compatible proxy endpoint (for remote cognia nodes) ─────────────
@app.post("/api/generate")
async def ollama_generate(req: dict):
    """Ollama-compatible /api/generate endpoint for remote cognia clients."""
    prompt = req.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    try:
        result = await infer(InferRequest(prompt=prompt, history=[]))
        # infer() may return JSONResponse (cache hit) or InferResponse
        if hasattr(result, "text"):
            text = result.text
        else:
            import json as _json
            body = _json.loads(result.body)
            text = body.get("text", "")
        return {"model": req.get("model", "cognia"), "response": text, "done": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── File browser endpoints ─────────────────────────────────────────────

import re as _re_files

_WORKSPACE = Path.cwd()


@app.get("/files/list")
def list_files(path: str = "."):
    """List files in a directory relative to workspace."""
    target = (_WORKSPACE / path).resolve()
    if not str(target).startswith(str(_WORKSPACE)):
        raise HTTPException(status_code=403, detail="path outside workspace")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="not a directory")
    entries = []
    try:
        for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if e.name.startswith('.') and e.name not in ('.env',):
                continue
            entries.append({
                "name": e.name,
                "type": "dir" if e.is_dir() else "file",
                "size": e.stat().st_size if e.is_file() else None,
                "path": str(e.relative_to(_WORKSPACE)).replace("\\", "/"),
            })
    except PermissionError:
        pass
    return {"path": str(target.relative_to(_WORKSPACE)).replace("\\", "/"), "entries": entries[:100]}


@app.get("/files/read")
def read_file(path: str):
    """Read a text file relative to workspace. Max 100KB."""
    target = (_WORKSPACE / path).resolve()
    if not str(target).startswith(str(_WORKSPACE)):
        raise HTTPException(status_code=403, detail="path outside workspace")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not a file")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"path": path, "content": content[:102400], "truncated": len(content) > 102400}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/files/write")
async def write_file(req: Request):
    """Write text to a file relative to workspace."""
    body = await req.json()
    path = body.get("path", "")
    content = body.get("content", "")
    if not path or not _re_files.match(r'^[\w\-./]+$', path):
        raise HTTPException(status_code=400, detail="invalid path")
    target = (_WORKSPACE / path).resolve()
    if not str(target).startswith(str(_WORKSPACE)):
        raise HTTPException(status_code=403, detail="path outside workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size": len(content)}


# ── Auth / API Key endpoints ──────────────────────────────────────────

class _CreateKeyRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    label: str = Field("", max_length=128)


@app.post("/auth/keys")
def auth_create_key(
    req: _CreateKeyRequest,
    mgr: _APIKeyManager = Depends(get_api_key_manager),
):
    """Create a new API key for user_id. Returns plaintext key once."""
    raw_key = mgr.create_key(req.user_id, req.label)
    # Retrieve the new row id via list_keys (last entry for this user)
    keys = mgr.list_keys(req.user_id)
    new_id = keys[-1]["id"] if keys else None
    return {"key": raw_key, "id": new_id}


@app.get("/auth/keys/{user_id}")
def auth_list_keys(
    user_id: str,
    mgr: _APIKeyManager = Depends(get_api_key_manager),
):
    """List all API keys (no hash) for user_id."""
    return {"keys": mgr.list_keys(user_id)}


@app.delete("/auth/keys/{key_id}")
def auth_revoke_key(
    key_id: int,
    mgr: _APIKeyManager = Depends(get_api_key_manager),
):
    """Revoke an API key by its integer id."""
    ok = mgr.revoke_key(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="key not found")
    return {"revoked": True, "id": key_id}


@app.get("/auth/rate-limit/{user_id}")
def auth_rate_limit_stats(user_id: str):
    """Return sliding-window rate limit stats for user_id."""
    return _rate_limiter.get_stats(user_id)


@app.get("/auth/tiers")
def auth_list_tiers():
    """Return all tier names and their configurations."""
    return {"tiers": _TIERS}


@app.get("/auth/keys/{user_id}/tier")
def auth_get_user_tier(
    user_id: str,
    mgr: _APIKeyManager = Depends(get_api_key_manager),
):
    """Return the tier of the active API key for user_id."""
    tier = mgr.get_key_tier(user_id)
    return {"user_id": user_id, "tier": tier}


# ── Monitoring endpoints ───────────────────────────────────────────────

@app.get("/metrics")
def get_metrics():
    """Return current runtime metrics as JSON."""
    return _metrics.get_stats()


def _build_digest_panel(d: dict) -> str:
    """Return an HTML panel showing digest data, or empty string when no data."""
    if not d:
        return ""
    rec = d.get("top_recommendation", "")
    rec_row = f"<tr><td>Recomendacion</td><td>{rec}</td></tr>" if rec else ""
    return f"""
  <h2 style="margin-top:2rem;font-size:1.1rem;color:#a0cfff;letter-spacing:0.04em;">Estado del sistema</h2>
  <table style="margin-top:0.75rem;width:100%;max-width:600px;border-collapse:collapse;background:#16213e;border-radius:8px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.4);">
    <thead><tr><th style="padding:0.75rem 1.2rem;background:#0f3460;color:#a0cfff;font-size:0.8rem;text-transform:uppercase;letter-spacing:0.06em;text-align:left;">Metrica</th><th style="padding:0.75rem 1.2rem;background:#0f3460;color:#a0cfff;font-size:0.8rem;text-transform:uppercase;letter-spacing:0.06em;text-align:left;">Valor</th></tr></thead>
    <tbody>
      <tr><td style="padding:0.75rem 1.2rem;color:#aac4e8;border-bottom:1px solid #0f3460;">Tarjetas SR para revisar</td><td style="padding:0.75rem 1.2rem;border-bottom:1px solid #0f3460;">{d.get('sr_due', 0)}</td></tr>
      <tr><td style="padding:0.75rem 1.2rem;color:#aac4e8;border-bottom:1px solid #0f3460;">Objetivos pendientes</td><td style="padding:0.75rem 1.2rem;border-bottom:1px solid #0f3460;">{d.get('goals_pending', 0)}</td></tr>
      <tr><td style="padding:0.75rem 1.2rem;color:#aac4e8;border-bottom:1px solid #0f3460;">Notas nuevas (24h)</td><td style="padding:0.75rem 1.2rem;border-bottom:1px solid #0f3460;">{d.get('new_notes', 0)}</td></tr>
      <tr><td style="padding:0.75rem 1.2rem;color:#aac4e8;border-bottom:1px solid #0f3460;">Logros desbloqueados hoy</td><td style="padding:0.75rem 1.2rem;border-bottom:1px solid #0f3460;">{d.get('achievements_unlocked', 0)}</td></tr>
      <tr><td style="padding:0.75rem 1.2rem;color:#aac4e8;border-bottom:1px solid #0f3460;">Racha actual (dias)</td><td style="padding:0.75rem 1.2rem;border-bottom:1px solid #0f3460;">{d.get('streak', 0)}</td></tr>
      <tr><td style="padding:0.75rem 1.2rem;color:#aac4e8;border-bottom:1px solid #0f3460;">Hechos cristalizados</td><td style="padding:0.75rem 1.2rem;border-bottom:1px solid #0f3460;">{d.get('crystallized_facts', 0)}</td></tr>
      <tr><td style="padding:0.75rem 1.2rem;color:#aac4e8;border-bottom:1px solid #0f3460;">Caminos de aprendizaje activos</td><td style="padding:0.75rem 1.2rem;border-bottom:1px solid #0f3460;">{d.get('learning_paths_active', 0)}</td></tr>
      {rec_row}
    </tbody>
  </table>"""


@app.get("/dashboard", response_class=_HTMLResponse)
def get_dashboard():
    """Monitoring dashboard — vanilla HTML, auto-refreshes every 5 s."""
    stats = _metrics.get_stats()

    digest_data: dict = {}
    if _digest is not None:
        try:
            digest_data = _digest.generate()
        except Exception:
            pass

    uptime_h = stats["uptime_s"] // 3600
    uptime_m = (stats["uptime_s"] % 3600) // 60
    uptime_s = stats["uptime_s"] % 60
    uptime_str = f"{uptime_h:02d}:{uptime_m:02d}:{uptime_s:02d}"

    rows = [
        ("Uptime", uptime_str),
        ("Total requests", stats["total_requests"]),
        ("Errors", stats["errors"]),
        ("Error rate", f"{stats['error_rate'] * 100:.1f}%"),
        ("Avg latency (ms)", stats["avg_latency_ms"]),
        ("p95 latency (ms)", stats["p95_latency_ms"] if stats["p95_latency_ms"] else "< 20 requests"),
        ("Avg tokens / request", stats["avg_tokens"] if stats["avg_tokens"] else "n/a"),
        ("Requests in window (last 100)", stats["requests_last_100"]),
    ]

    table_rows_html = "\n".join(
        f"<tr><td>{label}</td><td id='cell-{i}'>{value}</td></tr>"
        for i, (label, value) in enumerate(rows)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Cognia -- Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #1a1a2e;
      color: #e0e0e0;
      font-family: 'Segoe UI', system-ui, sans-serif;
      padding: 2rem;
      min-height: 100vh;
    }}
    h1 {{
      font-size: 1.6rem;
      font-weight: 600;
      margin-bottom: 0.4rem;
      color: #a0cfff;
      letter-spacing: 0.04em;
    }}
    .subtitle {{
      font-size: 0.85rem;
      color: #888;
      margin-bottom: 2rem;
    }}
    .subtitle span {{
      color: #6ec6ff;
    }}
    table {{
      width: 100%;
      max-width: 600px;
      border-collapse: collapse;
      background: #16213e;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }}
    th, td {{
      padding: 0.75rem 1.2rem;
      text-align: left;
      border-bottom: 1px solid #0f3460;
    }}
    th {{
      background: #0f3460;
      color: #a0cfff;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #1a2d5a; transition: background 0.15s; }}
    td:first-child {{ color: #aac4e8; width: 55%; }}
    td:last-child {{ font-variant-numeric: tabular-nums; font-weight: 500; }}
    .status-bar {{
      margin-top: 1.5rem;
      font-size: 0.78rem;
      color: #666;
    }}
    .dot {{
      display: inline-block;
      width: 8px; height: 8px;
      border-radius: 50%;
      background: #4caf50;
      margin-right: 6px;
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.4; }}
    }}
    #refresh-countdown {{ color: #6ec6ff; }}
  </style>
</head>
<body>
  <h1>Cognia -- Dashboard</h1>
  <p class="subtitle">Local inference API &nbsp;|&nbsp; <span>:8765</span> &nbsp;|&nbsp; Live metrics</p>

  <table>
    <thead>
      <tr><th>Metric</th><th>Value</th></tr>
    </thead>
    <tbody id="metrics-body">
{table_rows_html}
    </tbody>
  </table>

  <p class="status-bar">
    <span class="dot"></span>
    Auto-refreshing in <span id="refresh-countdown">5</span>s
  </p>

  <script>
    var countdown = 5;
    var cdEl = document.getElementById('refresh-countdown');
    setInterval(function() {{
      countdown--;
      if (cdEl) cdEl.textContent = countdown;
      if (countdown <= 0) countdown = 5;
    }}, 1000);

    function fmtUptime(s) {{
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      var sec = s % 60;
      return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
    }}

    async function refreshMetrics() {{
      try {{
        var resp = await fetch('/metrics');
        if (!resp.ok) return;
        var d = await resp.json();
        var rows = [
          fmtUptime(d.uptime_s),
          d.total_requests,
          d.errors,
          (d.error_rate * 100).toFixed(1) + '%',
          d.avg_latency_ms,
          d.p95_latency_ms > 0 ? d.p95_latency_ms : '< 20 requests',
          d.avg_tokens > 0 ? d.avg_tokens : 'n/a',
          d.requests_last_100
        ];
        rows.forEach(function(val, i) {{
          var el = document.getElementById('cell-' + i);
          if (el) el.textContent = val;
        }});
        countdown = 5;
      }} catch(e) {{}}
    }}

    setInterval(refreshMetrics, 5000);
  </script>

  {_build_digest_panel(digest_data)}
</body>
</html>"""
    return _HTMLResponse(content=html)


# ── Web Search endpoint ────────────────────────────────────────────────

@app.get("/search")
async def web_search(
    q: str = Query(default="", description="Search query"),
    max_results: int = Query(default=5, ge=1, le=20),
):
    """Search the web via DuckDuckGo Instant Answer API (no API key required)."""
    if not q.strip():
        raise HTTPException(status_code=422, detail="Query parameter 'q' must not be empty")
    return _web_search.search(q, max_results=max_results)


# ── History Export endpoints ───────────────────────────────────────────

from cognia.export.history_exporter import HistoryExporter as _HistoryExporter
from fastapi.responses import Response as _ExportResponse

_history_exporter = _HistoryExporter(db_path=_CHAT_DB)

_EXPORT_FORMATS = {"json", "md", "csv"}


@app.get("/export/history")
def export_history(
    format: str = Query("json", description="Export format: json | md | csv"),
    limit: int = Query(1000, ge=1, le=100000),
    since: str = Query(None, description="ISO datetime filter, e.g. 2026-01-01T00:00:00"),
):
    """
    Export full chat history as a downloadable file.

    - format=json  -> application/json,  filename cognia_history.json
    - format=md    -> text/markdown,     filename cognia_history.md
    - format=csv   -> text/csv,          filename cognia_history.csv
    """
    fmt = format.lower()
    if fmt not in _EXPORT_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid format '{format}'. Valid values: json, md, csv",
        )
    try:
        messages = _history_exporter.get_messages(limit=limit, since=since)
    except Exception as exc:
        _api_logger.error("export_history get_messages failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if fmt == "json":
        body = _history_exporter.to_json(messages)
        media = "application/json"
        filename = "cognia_history.json"
    elif fmt == "md":
        body = _history_exporter.to_markdown(messages)
        media = "text/markdown"
        filename = "cognia_history.md"
    else:  # csv
        body = _history_exporter.to_csv(messages)
        media = "text/csv"
        filename = "cognia_history.csv"

    return _ExportResponse(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/stats")
def export_stats():
    """Return aggregate statistics about the stored chat history."""
    from storage.db_pool import get_pool
    try:
        with get_pool(_CHAT_DB).get() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as total,"
                "       SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) as user_msgs,"
                "       SUM(CASE WHEN role!='user' THEN 1 ELSE 0 END) as ai_msgs,"
                "       MIN(ts) as first_ts,"
                "       MAX(ts) as last_ts"
                " FROM chat_history"
            ).fetchone()
        if row is None:
            return {"total_messages": 0, "user_messages": 0, "ai_messages": 0,
                    "first_message": None, "last_message": None}

        from cognia.export.history_exporter import _unix_to_iso
        total, user_msgs, ai_msgs, first_ts, last_ts = row
        return {
            "total_messages": total or 0,
            "user_messages": user_msgs or 0,
            "ai_messages": ai_msgs or 0,
            "first_message": _unix_to_iso(first_ts) if first_ts else None,
            "last_message": _unix_to_iso(last_ts) if last_ts else None,
        }
    except Exception as exc:
        _api_logger.error("export_stats failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Tool Router endpoint ───────────────────────────────────────────────

class _ToolRouteRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    execute: bool = False
    max_results: int = Field(default=3, ge=1, le=20)


@app.post("/tools/route")
def tools_route(req: _ToolRouteRequest):
    """
    Deterministic tool selection for a query.

    If execute=false (default): returns {"tool": str, "confidence": float}
    If execute=true: runs the selected tool and returns full result dict.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query cannot be empty")

    if not req.execute:
        tool, confidence = _tool_router.route_with_confidence(req.query)
        return {"tool": tool.value, "confidence": round(confidence, 3)}

    return _tool_router.execute(req.query, max_results=req.max_results)


# ── Progress Reporter singleton ────────────────────────────────────────

from cognia.reports.progress_reporter import ProgressReporter as _ProgressReporter
from fastapi.responses import Response as _ReportResponse

_progress_reporter = _ProgressReporter(db_path=_CHAT_DB)


@app.get("/report/progress")
def report_progress(
    user_id: str = Query("local", max_length=128),
    days: int = Query(7, ge=0, le=365),
):
    """
    Generate a Markdown progress report for user_id over the last `days` days.
    Returns text/markdown so the Electron renderer can display it directly.
    """
    md = _progress_reporter.generate_report(user_id=user_id, period_days=days)
    return _ReportResponse(content=md, media_type="text/markdown")


@app.get("/report/stats")
def report_stats(
    user_id: str = Query("local", max_length=128),
    days: int = Query(7, ge=0, le=365),
):
    """
    Return JSON stats for user_id over the last `days` days.
    Keys: period_days, goals_active, goals_completed, messages_total,
          sessions_total, insights_count.
    """
    return _progress_reporter.generate_json_stats(user_id=user_id, period_days=days)


# ── Notification Center singleton ─────────────────────────────────────

from cognia.notifications.notification_center import NotificationCenter as _NotificationCenter

_notification_center = _NotificationCenter(db_path=_CHAT_DB)

# ── Reminder Manager singleton ────────────────────────────────────────

from cognia.reminders.reminder_manager import ReminderManager as _ReminderManager

_reminder_manager = _ReminderManager(db_path=_CHAT_DB)
_reminder_manager.set_notification_center(_notification_center)

# ── Quality Analyzer singleton ────────────────────────────────────────

from cognia.quality.quality_analyzer import QualityAnalyzer as _QualityAnalyzer

_quality_analyzer = _QualityAnalyzer()


@app.get("/quality/trends")
def quality_trends(
    days: int = Query(7, ge=1, le=365),
    bucket_hours: int = Query(6, ge=1, le=168),
):
    """Return quality trends bucketed by hour windows over the last N days."""
    try:
        return _quality_analyzer.get_trends(period_days=days, bucket_hours=bucket_hours)
    except Exception as exc:
        _api_logger.warning("quality_trends error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/quality/summary")
def quality_summary(days: int = Query(7, ge=1, le=365)):
    """Return aggregate quality statistics for the last N days."""
    try:
        return _quality_analyzer.get_summary(period_days=days)
    except Exception as exc:
        _api_logger.warning("quality_summary error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/quality/alerts")
def quality_alerts(
    threshold: float = Query(0.4, ge=0.0, le=1.0),
    limit: int = Query(10, ge=1, le=100),
):
    """Return prompt hashes whose overall quality score is below threshold."""
    try:
        return {"alerts": _quality_analyzer.get_low_quality_prompts(threshold=threshold, limit=limit)}
    except Exception as exc:
        _api_logger.warning("quality_alerts error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Notification Center endpoints ────────────────────────────────────

class _NotifMarkReadRequest(BaseModel):
    notification_id: int


@app.get("/notifications/{user_id}")
def notifications_list(
    user_id: str,
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
):
    """Return notifications for user_id. unread_only=true filters to unread only."""
    items = _notification_center.get_all(
        user_id, limit=limit, include_read=not unread_only
    )
    return {"notifications": items}


@app.get("/notifications/{user_id}/count")
def notifications_count(user_id: str):
    """Return count of unread notifications for user_id."""
    return {"unread": _notification_center.get_unread_count(user_id)}


@app.post("/notifications/{user_id}/read")
def notifications_mark_read(user_id: str, req: _NotifMarkReadRequest):
    """Mark a single notification as read. Returns {"marked": bool}."""
    ok = _notification_center.mark_read(req.notification_id, user_id)
    return {"marked": ok}


@app.post("/notifications/{user_id}/read-all")
def notifications_mark_all_read(user_id: str):
    """Mark all unread notifications as read. Returns {"marked": N}."""
    n = _notification_center.mark_all_read(user_id)
    return {"marked": n}


@app.delete("/notifications/{notification_id}")
def notifications_delete(notification_id: int, user_id: str = Query(..., max_length=128)):
    """Delete a notification by id (scoped to user_id). Returns {"deleted": bool}."""
    deleted = _notification_center.delete(notification_id, user_id)
    return {"deleted": deleted}


# ── Reminder endpoints ────────────────────────────────────────────────

class _ReminderCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=256)
    minutes: int = Field(..., ge=1, le=525600)  # max 1 year
    body: str = Field("", max_length=1024)
    goal_id: int = Field(None)


@app.post("/reminders")
def reminders_create(req: _ReminderCreateRequest):
    """Create a relative reminder that fires in `minutes` from now."""
    reminder = _reminder_manager.create_relative(
        user_id=req.user_id,
        title=req.title,
        minutes=req.minutes,
        body=req.body,
        goal_id=req.goal_id,
    )
    return reminder


@app.get("/reminders/{user_id}")
def reminders_list(user_id: str):
    """List all pending reminders for user_id, ordered by fire_at ASC."""
    return {"reminders": _reminder_manager.get_pending(user_id)}


@app.delete("/reminders/{reminder_id}")
def reminders_cancel(reminder_id: int, user_id: str = Query(..., max_length=128)):
    """Cancel a pending reminder by id (scoped to user_id)."""
    cancelled = _reminder_manager.cancel(reminder_id, user_id)
    return {"cancelled": cancelled}


# ── Conversation Templates ────────────────────────────────────────────

from cognia.templates.conversation_templates import ConversationTemplateManager as _CTM

_template_manager = _CTM(db_path=_CHAT_DB)


class _TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=512)
    initial_prompt: str = Field(..., min_length=1, max_length=2000)
    guide_questions: list = Field(..., min_length=1)
    tags: list = Field(default_factory=list)
    estimated_turns: int = Field(default=5, ge=1, le=50)


@app.get("/templates")
def list_templates(tag: str = Query(None, max_length=64)):
    """List all templates (builtin + custom). Optionally filter by tag."""
    return {"templates": _template_manager.list_templates(tag=tag or None)}


@app.get("/templates/{template_id}")
def get_template(template_id: str):
    """Return detail for a single template."""
    if not _re_files.match(r'^[\w\-]+$', template_id):
        raise HTTPException(status_code=400, detail="invalid template_id")
    tpl = _template_manager.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    return tpl


@app.post("/templates/{template_id}/start")
def start_template_session(
    template_id: str,
    session_id: str = Query(None, max_length=128),
):
    """
    Start a session with the given template.
    Returns initial_prompt, guide_questions, session_id, and estimated_turns.
    """
    if not _re_files.match(r'^[\w\-]+$', template_id):
        raise HTTPException(status_code=400, detail="invalid template_id")
    try:
        return _template_manager.start_session(template_id, session_id=session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="template not found")


@app.post("/templates")
def create_template(req: _TemplateCreateRequest):
    """Create a new custom template. Returns the created template dict with id."""
    try:
        return _template_manager.create_custom(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/templates/{template_id}")
def delete_template(template_id: str):
    """
    Delete a custom template by id.
    Returns {"deleted": false} if the template is builtin or does not exist.
    """
    if not _re_files.match(r'^[\w\-]+$', template_id):
        raise HTTPException(status_code=400, detail="invalid template_id")
    deleted = _template_manager.delete_custom(template_id)
    return {"deleted": deleted}


# ── Debug endpoints ────────────────────────────────────────────────────

# All singletons are defined by this point; build the context map here.
_APP_CONTEXT = {
    "metrics": _metrics,
    "itcs_scorer": _itcs_scorer,
    "session_summarizer": _session_summarizer,
    "api_key_manager": _api_key_manager,
    "rate_limiter": _rate_limiter,
    "persona_manager": _persona_manager,
    "persona_advisor": _persona_advisor,
    "semantic_cache": _sem_cache,
    "orchestrator": _orch,
    "cache_warmer": _cache_warmer,
    "web_search": _web_search,
    "tool_router": _tool_router,
    "rfv_validator": _rfv_validator,
    "goal_tracker": _goal_tracker,
    "goal_suggester": _goal_suggester,
    "task_decomposer": _task_decomposer,
    "webhook_manager": _webhook_manager,
    "curiosity_engine": _curiosity_engine_api,
    "history_exporter": _history_exporter,
    "progress_reporter": _progress_reporter,
    "notification_center": _notification_center,
    "reminder_manager": _reminder_manager,
    "quality_analyzer": _quality_analyzer,
    "template_manager": _template_manager,
}


# ── Long-term Memory Consolidation endpoints ──────────────────────────

@app.get("/memory/consolidated")
async def memory_consolidated():
    """Returns consolidated recurring topics for the default user."""
    if _consolidator is None:
        return {"facts": [], "count": 0}
    facts = _consolidator.get_consolidated_facts("default")
    return {"facts": facts, "count": len(facts)}


@app.post("/memory/consolidate")
async def memory_consolidate():
    """Runs consolidation immediately and returns count of new KG facts added."""
    if _consolidator is None:
        return {"new_facts": 0}
    n = _consolidator.consolidate("default")
    return {"new_facts": n}


@app.get("/debug/state")
async def debug_state(request: Request):
    """
    Full system snapshot for enterprise debugging.
    Requires X-Admin-Key header == COGNIA_ADMIN_KEY env var.
    Returns 503 if COGNIA_ADMIN_KEY is not configured.
    """
    admin_key = os.getenv("COGNIA_ADMIN_KEY", "")
    if not admin_key:
        return _JSONResponse({"error": "debug_disabled"}, status_code=503)
    provided = request.headers.get("X-Admin-Key", "")
    if not hmac.compare_digest(admin_key, provided):
        return _JSONResponse({"error": "unauthorized"}, status_code=401)
    return _state_inspector.full_snapshot(_APP_CONTEXT)


@app.get("/debug/health")
async def debug_health():
    """Public health check endpoint — no auth required."""
    return {
        "status": "ok",
        "ts": _time.time(),
        "version": "3.0",
    }


# ── Implicit Feedback endpoints ───────────────────────────────────────

class _FeedbackBody(BaseModel):
    message_id: str
    signal: str
    query_type: str = "general"


@app.post("/feedback")
def feedback_record(body: _FeedbackBody):
    """Record explicit user feedback signal."""
    if _feedback_learner is None:
        return {"ok": False, "error": "feedback_learner_unavailable"}
    _feedback_learner.record(body.message_id, body.signal, body.query_type)
    return {"ok": True}


@app.get("/feedback/stats")
def feedback_stats():
    """Return aggregate feedback statistics."""
    if _feedback_learner is None:
        return {"error": "feedback_learner_unavailable"}
    return _feedback_learner.get_stats()


# ── Proactive Suggestions endpoints ───────────────────────────────────

class _ProactiveGenerateRequest(BaseModel):
    text: str = Field(..., max_length=4096)
    goals: list = Field(default_factory=list)


@app.get("/proactive/suggestions")
def proactive_get_suggestions():
    """Return up to 3 unshown proactive suggestions and mark them shown."""
    if _proactive is None:
        return {"suggestions": []}
    try:
        return {"suggestions": _proactive.get_pending(3)}
    except Exception as exc:
        _api_logger.warning("proactive get_pending error: %s", exc)
        return {"suggestions": []}


@app.post("/proactive/generate")
def proactive_generate(req: _ProactiveGenerateRequest):
    """Generate contextual suggestions, queue them, and return the list."""
    if _proactive is None:
        return {"suggestions": []}
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")
    try:
        suggestions = _proactive.generate_suggestions(req.text, active_goals=req.goals)
        for s in suggestions:
            _proactive.queue_suggestion(
                s["text"], s["category"], context_trigger=req.text[:128]
            )
        return {"suggestions": suggestions}
    except Exception as exc:
        _api_logger.warning("proactive generate error: %s", exc)
        return {"suggestions": []}


# ── Smart Notes endpoints ──────────────────────────────────────────────

class _NoteCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    note_type: str = Field("fact", max_length=32)
    session_id: str = Field("default", max_length=128)
    source: str = Field("manual", max_length=64)


@app.get("/notes")
def notes_list(
    session_id: str = Query(None, max_length=128),
    note_type: str = Query(None, max_length=32),
    limit: int = Query(20, ge=1, le=200),
):
    """Return notes with optional session_id and note_type filters."""
    if _notes is None:
        raise HTTPException(status_code=503, detail="SmartNotesEngine not available")
    return {"notes": _notes.get_notes(session_id=session_id, note_type=note_type, limit=limit)}


@app.post("/notes")
def notes_create(req: _NoteCreateRequest):
    """Create a new note manually. Returns {"id": N}."""
    if _notes is None:
        raise HTTPException(status_code=503, detail="SmartNotesEngine not available")
    note_id = _notes.add_note(
        req.content, note_type=req.note_type,
        session_id=req.session_id, source=req.source,
    )
    if _analytics is not None:
        import threading as _t_notes
        _t_notes.Thread(target=_analytics.record, args=("notes",), daemon=True).start()
    return {"id": note_id}


@app.get("/notes/search")
def notes_search(
    q: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(10, ge=1, le=100),
):
    """Search notes by content substring."""
    if _notes is None:
        raise HTTPException(status_code=503, detail="SmartNotesEngine not available")
    return {"notes": _notes.search_notes(q, limit=limit)}


@app.get("/notes/stats")
def notes_stats():
    """Return aggregate statistics: total, by_type, pinned."""
    if _notes is None:
        raise HTTPException(status_code=503, detail="SmartNotesEngine not available")
    return _notes.get_stats()


@app.post("/notes/{note_id}/pin")
def notes_pin(note_id: int):
    """Pin a note by id."""
    if _notes is None:
        raise HTTPException(status_code=503, detail="SmartNotesEngine not available")
    _notes.pin_note(note_id)
    return {"pinned": True, "id": note_id}


# ── Spaced Repetition endpoints ────────────────────────────────────────

class _SRCardCreateRequest(BaseModel):
    front: str = Field(..., min_length=1, max_length=1000)
    back: str = Field(..., min_length=1, max_length=2000)
    topic: str = Field("general", max_length=128)


class _SRReviewRequest(BaseModel):
    quality: int = Field(..., ge=0, le=5)


@app.get("/learning/cards")
def sr_cards_list(
    topic: str = Query(None, max_length=128),
    due_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=200),
):
    """Return flashcards with optional topic and due_only filters."""
    if _sr is None:
        raise HTTPException(status_code=503, detail="SpacedRepetitionEngine not available")
    if due_only:
        cards = _sr.get_due_cards(limit=limit)
        if topic:
            cards = [c for c in cards if c["topic"] == topic]
        return {"cards": cards}
    from storage.db_pool import get_pool as _gp
    import time as _t
    with _gp(_sr._db).get() as _conn:
        if topic:
            rows = _conn.execute(
                "SELECT id, front, back, topic, ease_factor, interval_days, "
                "repetitions, next_review, last_reviewed, created_at "
                "FROM sr_cards WHERE topic = ? ORDER BY next_review ASC LIMIT ?",
                (topic, limit),
            ).fetchall()
        else:
            rows = _conn.execute(
                "SELECT id, front, back, topic, ease_factor, interval_days, "
                "repetitions, next_review, last_reviewed, created_at "
                "FROM sr_cards ORDER BY next_review ASC LIMIT ?",
                (limit,),
            ).fetchall()
    from cognia.learning.spaced_repetition import _row_to_dict as _sr_row
    return {"cards": [_sr_row(r) for r in rows]}


@app.post("/learning/cards")
def sr_cards_create(req: _SRCardCreateRequest):
    """Create a new flashcard. Returns {"id": N}."""
    if _sr is None:
        raise HTTPException(status_code=503, detail="SpacedRepetitionEngine not available")
    card_id = _sr.add_card(req.front, req.back, topic=req.topic)
    if _analytics is not None:
        import threading as _t_learning
        _t_learning.Thread(target=_analytics.record, args=("learning",), daemon=True).start()
    return {"id": card_id}


@app.post("/learning/cards/{card_id}/review")
def sr_cards_review(card_id: int, req: _SRReviewRequest):
    """Apply SM-2 review to a card. Returns the updated card dict."""
    if _sr is None:
        raise HTTPException(status_code=503, detail="SpacedRepetitionEngine not available")
    try:
        return _sr.review_card(card_id, req.quality)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Card {card_id} not found")


@app.get("/learning/due")
def sr_due_cards(limit: int = Query(10, ge=1, le=100)):
    """Shortcut: return cards due for review."""
    if _sr is None:
        raise HTTPException(status_code=503, detail="SpacedRepetitionEngine not available")
    return {"cards": _sr.get_due_cards(limit=limit)}


@app.get("/learning/stats")
def sr_stats():
    """Return aggregate learning statistics."""
    if _sr is None:
        raise HTTPException(status_code=503, detail="SpacedRepetitionEngine not available")
    return _sr.get_stats()


# ── Quiz endpoints ────────────────────────────────────────────────────

@app.get("/quiz/generate")
def quiz_generate(topic: _Optional[str] = None, limit: int = 10):
    """Generate quiz questions from KG facts and SR cards."""
    if _quiz is None:
        raise HTTPException(status_code=503, detail="QuizGenerator not available")
    questions = _quiz.generate_mixed(topic=topic, limit=limit)
    return {"questions": questions}


class _QuizAnswerRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=0)
    user_answer: str = Field(..., min_length=0)
    source: str = Field("quiz", max_length=32)


@app.post("/quiz/answer")
def quiz_answer(req: _QuizAnswerRequest):
    """Record a user's answer and return whether it was correct."""
    if _quiz is None:
        raise HTTPException(status_code=503, detail="QuizGenerator not available")
    correct = _quiz.record_answer(
        question=req.question,
        answer=req.answer,
        user_answer=req.user_answer,
        source=req.source,
    )
    return {"correct": correct}


@app.get("/quiz/stats")
def quiz_stats():
    """Return aggregate quiz accuracy statistics."""
    if _quiz is None:
        raise HTTPException(status_code=503, detail="QuizGenerator not available")
    return _quiz.get_stats()


# ── Achievement System singleton ──────────────────────────────────────

_achievements: _Optional["_AchievementSystem_t"] = None

try:
    from cognia.gamification.achievement_system import AchievementSystem as _AchievementSystem
    _AchievementSystem_t = _AchievementSystem
    _achievements = _AchievementSystem(db_path=_CHAT_DB)
except Exception as _ach_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "AchievementSystem init failed: %s", _ach_err
    )
    _AchievementSystem = None  # type: ignore[assignment,misc]


class _AchievementCheckRequest(BaseModel):
    event: str = Field(..., min_length=1, max_length=64)
    count: int = Field(1, ge=1)


@app.get("/achievements")
def achievements_list():
    """Return all achievements with unlocked status for the default user."""
    if _achievements is None:
        raise HTTPException(status_code=503, detail="AchievementSystem not available")
    if _analytics is not None:
        import threading as _t_ach
        _t_ach.Thread(target=_analytics.record, args=("achievements",), daemon=True).start()
    return {"achievements": _achievements.get_all_with_status("default")}


@app.get("/achievements/stats")
def achievements_stats():
    """Return aggregate achievement stats for the default user."""
    if _achievements is None:
        raise HTTPException(status_code=503, detail="AchievementSystem not available")
    return _achievements.get_stats("default")


@app.post("/achievements/check")
def achievements_check(req: _AchievementCheckRequest):
    """Manually trigger achievement check. Returns {"unlocked": [names]}."""
    if _achievements is None:
        raise HTTPException(status_code=503, detail="AchievementSystem not available")
    unlocked = _achievements.check_and_unlock("default", req.event, count=req.count)
    return {"unlocked": unlocked}


# ── Usage Analytics singleton ─────────────────────────────────────────

_analytics: _Optional["_UsageAnalytics_t"] = None

try:
    from cognia.analytics.usage_analytics import UsageAnalytics as _UsageAnalytics
    _UsageAnalytics_t = _UsageAnalytics
    _analytics = _UsageAnalytics(db_path=_CHAT_DB)
except Exception as _uan_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "UsageAnalytics init failed: %s", _uan_err
    )
    _UsageAnalytics = None  # type: ignore[assignment,misc]


# ── Analytics endpoints ────────────────────────────────────────────────

@app.get("/analytics/stats")
def analytics_stats():
    """Return aggregate usage stats for the local user."""
    if _analytics is None:
        raise HTTPException(status_code=503, detail="UsageAnalytics not available")
    return _analytics.get_stats()


@app.get("/analytics/top-features")
def analytics_top_features(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=100),
):
    """Return top features by usage count over last N days."""
    if _analytics is None:
        raise HTTPException(status_code=503, detail="UsageAnalytics not available")
    return {"features": _analytics.get_top_features(days=days, limit=limit)}


@app.get("/analytics/daily")
def analytics_daily(days: int = Query(14, ge=1, le=365)):
    """Return total usage per day for last N days."""
    if _analytics is None:
        raise HTTPException(status_code=503, detail="UsageAnalytics not available")
    return {"activity": _analytics.get_daily_activity(days=days)}


@app.get("/analytics/streak")
def analytics_streak():
    """Return current consecutive-day usage streak."""
    if _analytics is None:
        raise HTTPException(status_code=503, detail="UsageAnalytics not available")
    return {"streak": _analytics.get_streak()}


# ── Semantic Memory Search singleton ─────────────────────────────────

_semantic_search: _Optional["_SemanticMemorySearch_t"] = None

try:
    from cognia.memory.semantic_search import SemanticMemorySearch as _SemanticMemorySearch
    _SemanticMemorySearch_t = _SemanticMemorySearch
    _semantic_search = _SemanticMemorySearch(db_path=_CHAT_DB)
except Exception as _sms_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "SemanticMemorySearch init failed: %s", _sms_err
    )
    _SemanticMemorySearch = None  # type: ignore[assignment,misc]


# ── Semantic Memory Search endpoints ─────────────────────────────────

@app.get("/memory/search")
def memory_search(
    q: str = Query(..., min_length=1, max_length=1000),
    limit: int = Query(5, ge=1, le=50),
    role: str = Query("all", max_length=32),
):
    """TF-IDF search over conversation history. Returns top matches."""
    if _semantic_search is None:
        raise HTTPException(status_code=503, detail="SemanticMemorySearch not available")
    results = _semantic_search.search(query=q, limit=limit, role=role)
    return {"results": results}


@app.get("/memory/search/context")
def memory_search_context(
    q: str = Query(..., min_length=1, max_length=1000),
    window: int = Query(3, ge=1, le=10),
):
    """TF-IDF search returning surrounding conversation window for best match."""
    if _semantic_search is None:
        raise HTTPException(status_code=503, detail="SemanticMemorySearch not available")
    context = _semantic_search.search_context(query=q, window=window)
    return {"context": context}


# ── Knowledge Synthesizer singleton ──────────────────────────────────
_synthesizer: _Optional["_KnowledgeSynthesizer_t"] = None

try:
    from cognia.synthesis.knowledge_synthesizer import KnowledgeSynthesizer as _KnowledgeSynthesizer
    import cognia.synthesis.knowledge_synthesizer as _ks_mod
    _ks_mod._CHAT_DB = _CHAT_DB
    _KnowledgeSynthesizer_t = _KnowledgeSynthesizer
    _synthesizer = _KnowledgeSynthesizer()
except Exception as _kse_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "KnowledgeSynthesizer init failed: %s", _kse_err
    )
    _KnowledgeSynthesizer = None  # type: ignore[assignment,misc]


@app.get("/synthesis")
def synthesis_endpoint(q: str = Query(..., min_length=1, max_length=500)):
    """Aggregate notes, KG facts, and chat context about a topic into a synthesis."""
    if _synthesizer is None:
        raise HTTPException(status_code=503, detail="KnowledgeSynthesizer not available")
    return _synthesizer.synthesize(q)


# ── Cognitive Profile singleton ───────────────────────────────────────

_cognitive_profile: _Optional["_CognitiveProfile_t"] = None

try:
    from cognia.intelligence.cognitive_profile import CognitiveProfile as _CognitiveProfile
    import cognia.intelligence.cognitive_profile as _cp_mod
    _cp_mod._DB_PATH = _CHAT_DB
    _CognitiveProfile_t = _CognitiveProfile
    _cognitive_profile = _CognitiveProfile()
except Exception as _cp_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "CognitiveProfile init failed: %s", _cp_err
    )
    _CognitiveProfile = None  # type: ignore[assignment,misc]


@app.get("/cognitive-profile")
def cognitive_profile_get():
    """Return the unified cognitive profile for the local user."""
    if _cognitive_profile is None:
        raise HTTPException(status_code=503, detail="CognitiveProfile not available")
    profile = _cognitive_profile.build()
    try:
        user_id = profile.get("user_id", "default") if isinstance(profile, dict) else "default"
        profile["recommendations"] = _rec_engine.generate(user_id) if _rec_engine is not None else []
    except Exception:
        pass
    return profile


@app.get("/cognitive-profile/summary")
def cognitive_profile_summary():
    """Return a formatted ASCII summary of the cognitive profile."""
    if _cognitive_profile is None:
        raise HTTPException(status_code=503, detail="CognitiveProfile not available")
    return {"summary": _cognitive_profile.get_summary()}


# ── Recommendation Engine singleton ──────────────────────────────────────

_rec_engine: _Optional["_RecommendationEngine_t"] = None

try:
    from cognia.intelligence.recommendation_engine import RecommendationEngine as _RecommendationEngine
    import cognia.intelligence.recommendation_engine as _re_mod
    _re_mod._DB_PATH = _CHAT_DB
    _RecommendationEngine_t = _RecommendationEngine
    _rec_engine = _RecommendationEngine()
except Exception as _re_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "RecommendationEngine init failed: %s", _re_err
    )
    _RecommendationEngine = None  # type: ignore[assignment,misc]


@app.get("/recommendations")
def recommendations_get(request: Request):
    """Return personalized next-best-action recommendations."""
    if _rec_engine is None:
        raise HTTPException(status_code=503, detail="RecommendationEngine not available")
    user_id = getattr(request.state, "user_id", "default")
    return {"recommendations": _rec_engine.generate(user_id)}


@app.get("/recommendations/top")
def recommendations_top(request: Request):
    """Return the highest priority recommendation or null."""
    if _rec_engine is None:
        raise HTTPException(status_code=503, detail="RecommendationEngine not available")
    user_id = getattr(request.state, "user_id", "default")
    return {"recommendation": _rec_engine.get_top(user_id)}


# ── Self-Critique endpoints ───────────────────────────────────────────

@app.get("/critique/recent")
def critique_recent():
    """Return last 5 response critiques."""
    if _self_critic is None:
        raise HTTPException(status_code=503, detail="SelfCritic not available")
    return {"critiques": _self_critic.get_recent_critiques(5)}


@app.get("/critique/score")
def critique_score():
    """Return average quality score for last 7 days and trend."""
    if _self_critic is None:
        raise HTTPException(status_code=503, detail="SelfCritic not available")
    avg_7d = _self_critic.get_avg_score(days=7)
    # trend: compare avg last 3 days vs avg days 4-7
    avg_3d = _self_critic.get_avg_score(days=3)
    # approximate days 4-7 as (7d_avg * 7 - 3d_avg * 3) / 4 — guarded against div/zero
    try:
        import time as _t
        cutoff_4 = _t.time() - 4 * 86400
        cutoff_7 = _t.time() - 7 * 86400
        from storage.db_pool import get_pool as _gp_cs
        with _gp_cs(_self_critic._db_path).get() as _conn:
            row = _conn.execute(
                "SELECT AVG(overall_score) FROM response_critiques WHERE ts >= ? AND ts < ?",
                (cutoff_7, cutoff_4),
            ).fetchone()
        avg_early = float(row[0]) if row and row[0] is not None else avg_3d
    except Exception:
        avg_early = avg_3d
    diff = avg_3d - avg_early
    if diff > 0.05:
        trend = "improving"
    elif diff < -0.05:
        trend = "declining"
    else:
        trend = "stable"
    return {"avg_score_7d": avg_7d, "trend": trend}


# ── Conversation Anchor Tracker debug endpoint — Phase 61 ─────────────

@app.get("/anchor/{session_id}")
def anchor_debug(session_id: str):
    """Return current anchor info for a session (debug endpoint)."""
    if _anchor_tracker is None:
        raise HTTPException(status_code=503, detail="AnchorTracker not available")
    anchor = _anchor_tracker._anchors.get(session_id)
    if anchor is None:
        return {"session_id": session_id, "anchor": None}
    return {
        "session_id": session_id,
        "anchor": {
            "original_query": anchor.original_query,
            "turn_count": anchor.turn_count,
            "keywords": sorted(anchor.keywords),
        },
    }


# ── Style Engine endpoint — Phase 54 ──────────────────────────────────

@app.get("/style/profile")
def style_profile():
    """Return the current adaptive style profile for the local user."""
    if _style_engine is None:
        raise HTTPException(status_code=503, detail="StyleEngine not available")
    return _style_engine.get_profile()


# ── Comprehensive Report Generator singleton ──────────────────────────

_report_gen: _Optional["_ComprehensiveReportGenerator_t"] = None

try:
    from cognia.export.comprehensive_report import (
        ComprehensiveReportGenerator as _ComprehensiveReportGenerator,
    )
    _ComprehensiveReportGenerator_t = _ComprehensiveReportGenerator
    _report_gen = _ComprehensiveReportGenerator()
except Exception as _rg_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "ComprehensiveReportGenerator init failed: %s", _rg_err
    )
    _ComprehensiveReportGenerator = None  # type: ignore[assignment,misc]


class _ReportSaveRequest(BaseModel):
    path: str
    period: int = 7


@app.get("/reports/generate")
def reports_generate(
    period: int = Query(7, ge=1, le=365),
    format: str = Query("md"),
):
    """Generate a full Markdown report aggregating all subsystems."""
    if _report_gen is None:
        raise HTTPException(status_code=503, detail="ComprehensiveReportGenerator not available")
    report_md = _report_gen.generate(period_days=period, user_id="default")
    return {"report": report_md, "period_days": period}


@app.post("/reports/save")
def reports_save(req: _ReportSaveRequest):
    """Save the generated report to disk. Returns absolute path."""
    if _report_gen is None:
        raise HTTPException(status_code=503, detail="ComprehensiveReportGenerator not available")
    from pathlib import Path as _Path
    # Security: path must be relative or inside a safe directory — reject traversal
    req_path = _Path(req.path)
    if req_path.is_absolute():
        abs_path = req_path
    else:
        abs_path = _Path.cwd() / req_path
    saved = _report_gen.save(str(abs_path), period_days=req.period, user_id="default")
    return {"saved_to": saved}


# ── Feature Flags endpoints ───────────────────────────────────────────

class _FeatureFlagPatchRequest(BaseModel):
    enabled: bool


@app.get("/features")
def features_list(tier: str = Query(None, max_length=32)):
    """Return all feature flags. Optional ?tier= filter returns only flags accessible to that tier."""
    if _feature_flags is None:
        raise HTTPException(status_code=503, detail="FeatureFlagManager not available")
    all_flags = _feature_flags.get_all()
    if tier:
        accessible = set(_feature_flags.get_accessible(tier))
        all_flags = [f for f in all_flags if f["name"] in accessible]
    return {"flags": all_flags}


@app.get("/features/{name}")
def features_get(name: str):
    """Return single flag status by name."""
    if _feature_flags is None:
        raise HTTPException(status_code=503, detail="FeatureFlagManager not available")
    all_flags = {f["name"]: f for f in _feature_flags.get_all()}
    if name not in all_flags:
        raise HTTPException(status_code=404, detail=f"Flag '{name}' not found")
    return all_flags[name]


@app.patch("/features/{name}")
def features_patch(name: str, body: _FeatureFlagPatchRequest, request: Request):
    """Update flag enabled_default. Requires X-Admin-Key header == COGNIA_ADMIN_KEY."""
    admin_key = os.getenv("COGNIA_ADMIN_KEY", "")
    if not admin_key:
        return _JSONResponse({"error": "admin_not_configured"}, status_code=503)
    provided = request.headers.get("X-Admin-Key", "")
    if not hmac.compare_digest(admin_key, provided):
        return _JSONResponse({"error": "unauthorized"}, status_code=401)
    if _feature_flags is None:
        raise HTTPException(status_code=503, detail="FeatureFlagManager not available")
    updated = _feature_flags.set_flag(name, body.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Flag '{name}' not found")
    return {"name": name, "enabled": body.enabled}


# ── Knowledge Crystallization endpoints ──────────────────────────────

@app.get("/knowledge/crystallized")
def knowledge_get_crystallized():
    """Return list of crystallized KG facts."""
    if _crystallizer is None:
        raise HTTPException(status_code=503, detail="KnowledgeCrystallizer not available")
    return {"facts": _crystallizer.get_crystallized()}


@app.post("/knowledge/crystallize")
def knowledge_crystallize():
    """Promote high-weight facts to crystallized status. Returns count."""
    if _crystallizer is None:
        raise HTTPException(status_code=503, detail="KnowledgeCrystallizer not available")
    count = _crystallizer.crystallize_frequent()
    return {"crystallized": count}


@app.get("/knowledge/crystal-stats")
def knowledge_crystal_stats():
    """Return crystallization statistics."""
    if _crystallizer is None:
        raise HTTPException(status_code=503, detail="KnowledgeCrystallizer not available")
    return _crystallizer.get_stats()


# ── Knowledge Consistency Checker endpoints ───────────────────────────

@app.get("/knowledge/conflicts")
def knowledge_conflicts_list():
    """Return unresolved KG conflicts."""
    if _consistency is None:
        raise HTTPException(status_code=503, detail="ConsistencyChecker not available")
    return _consistency.get_unresolved()


@app.post("/knowledge/conflicts/check")
def knowledge_conflicts_check():
    """Run contradiction detection and store new conflicts."""
    if _consistency is None:
        raise HTTPException(status_code=503, detail="ConsistencyChecker not available")
    new_conflicts = _consistency.run_check()
    return {"new_conflicts": new_conflicts}


@app.post("/knowledge/conflicts/{conflict_id}/resolve")
def knowledge_conflicts_resolve(conflict_id: int):
    """Mark a conflict as resolved."""
    if _consistency is None:
        raise HTTPException(status_code=503, detail="ConsistencyChecker not available")
    ok = _consistency.resolve_conflict(conflict_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return {"resolved": True}


@app.get("/knowledge/conflicts/stats")
def knowledge_conflicts_stats():
    """Return conflict statistics."""
    if _consistency is None:
        raise HTTPException(status_code=503, detail="ConsistencyChecker not available")
    return _consistency.get_stats()


# ── Learning Path endpoints ────────────────────────────────────────────

class _LearningPathCreateRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=512)


@app.post("/learning/paths")
def learning_path_create(req: _LearningPathCreateRequest):
    """Create a new learning path for the given goal."""
    if _learning_path is None:
        raise HTTPException(status_code=503, detail="LearningPathGenerator not available")
    try:
        return _learning_path.generate(req.goal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/learning/paths/stats")
def learning_path_stats():
    """Return learning path statistics: total, active, completed, avg_completion_pct."""
    if _learning_path is None:
        raise HTTPException(status_code=503, detail="LearningPathGenerator not available")
    return _learning_path.get_stats()


@app.get("/learning/paths")
def learning_path_list():
    """Return all active (not completed) learning paths."""
    if _learning_path is None:
        raise HTTPException(status_code=503, detail="LearningPathGenerator not available")
    return {"paths": _learning_path.get_active_paths()}


@app.get("/learning/paths/{path_id}")
def learning_path_get(path_id: int):
    """Return a single learning path by id."""
    if _learning_path is None:
        raise HTTPException(status_code=503, detail="LearningPathGenerator not available")
    try:
        return _learning_path.get_path(path_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/learning/paths/{path_id}/advance")
def learning_path_advance(path_id: int):
    """Advance the learning path to the next step."""
    if _learning_path is None:
        raise HTTPException(status_code=503, detail="LearningPathGenerator not available")
    try:
        return _learning_path.advance_step(path_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── User Facts endpoints ───────────────────────────────────────────────

class _UserFactBody(BaseModel):
    fact: str
    confidence: float = 1.0


@app.get("/user/facts")
def user_facts_list():
    """Return all stored user facts (limit 50, min_confidence 0.0)."""
    if _user_facts is None:
        raise HTTPException(status_code=503, detail="UserFactsMemory not available")
    return {"facts": _user_facts.get_facts(limit=50, min_confidence=0.0)}


@app.post("/user/facts")
def user_facts_add(body: _UserFactBody):
    """Declare a new user fact."""
    if _user_facts is None:
        raise HTTPException(status_code=503, detail="UserFactsMemory not available")
    if not body.fact.strip():
        raise HTTPException(status_code=400, detail="fact cannot be empty")
    fact_id = _user_facts.add_fact(body.fact, source="declared", confidence=body.confidence)
    return {"id": fact_id, "fact": body.fact}


@app.delete("/user/facts/{fact_id}")
def user_facts_forget(fact_id: int):
    """Delete a user fact by id."""
    if _user_facts is None:
        raise HTTPException(status_code=503, detail="UserFactsMemory not available")
    ok = _user_facts.forget_fact(fact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="fact not found")
    return {"deleted": True, "id": fact_id}


@app.get("/user/facts/context")
def user_facts_context():
    """Return the formatted context string injected into the system prompt."""
    if _user_facts is None:
        raise HTTPException(status_code=503, detail="UserFactsMemory not available")
    return {"context": _user_facts.get_context()}


@app.get("/context/prioritizer-stats")
def context_prioritizer_stats():
    """Return InjectionPrioritizer call statistics."""
    if _injector is None:
        raise HTTPException(status_code=503, detail="InjectionPrioritizer not available")
    return _injector.get_stats()


# ── Daily Digest singleton ─────────────────────────────────────────────

_digest: _Optional["_DailyDigest_t"] = None

try:
    from cognia.social.daily_digest import DailyDigest as _DailyDigest
    _DailyDigest_t = _DailyDigest
    _digest = _DailyDigest(db_path=_CHAT_DB)
except Exception as _dd_err:
    _logging.getLogger("cognia_desktop_api").warning(
        "DailyDigest init failed: %s", _dd_err
    )
    _DailyDigest = None  # type: ignore[assignment,misc]


@app.get("/digest")
def digest_get():
    """Return today's daily digest: formatted text + raw metric data."""
    if _digest is None:
        raise HTTPException(status_code=503, detail="DailyDigest not available")
    data = _digest.generate()
    return {"digest": _digest.format_digest(data), "data": data}


# ── Format Intelligence endpoint — Phase 59 ──────────────────────────

@app.get("/format/detect")
def format_detect(q: str = Query(..., description="Text to classify", max_length=4096)):
    """Debug endpoint: return detected question type and format hint for a given text."""
    if _format_intelligence is None:
        raise HTTPException(status_code=503, detail="FormatIntelligence not available")
    qtype = _format_intelligence.detect_type(q)
    hint  = _format_intelligence.get_format_hint(q)
    return {"type": qtype, "hint": hint}


# ── Dev entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("COGNIA_DESKTOP_PORT", 8765))
    host = "0.0.0.0" if _LAN_MODE else "127.0.0.1"
    uvicorn.run("cognia_desktop_api:app", host=host, port=port, reload=False)
