"""
cognia/cognia.py
=================
Clase principal Cognia v3 — integración de todos los módulos.
"""

import json
import time
import random
from collections import defaultdict, Counter
from datetime import datetime
from typing import Optional

from .config import (
    DB_PATH, HAS_FATIGUE, HAS_PLANNER, HAS_CURIOSITY_ENGINE,
    HAS_LANGUAGE_ENGINE, HAS_RESEARCH_ENGINE, HAS_PROGRAM_CREATOR,
    NORMAL_CYCLE_MS_ENERGY, VECTOR_DIM,
    ReasoningPlanner, ActiveCuriosityEngine,
)
from .database import db_connect, init_db, limpiar_episodios_ruido
from .vectors import cosine_similarity

from .memory import (
    EpisodicMemory, SemanticMemory, WorkingMemory, PerceptionModule,
    ChatHistory, UserProfile, ForgettingModule, ConsolidationModule,
)
from .reasoning import (
    ContradictionDetector, WorldModelModule, HypothesisModule,
    MetacognitionModule, EvaluationModule, CuriosityModule,
)
from .knowledge import KnowledgeGraph, InferenceEngine, TemporalMemory, GoalSystem
from .attention import AttentionSystem
from .compression import ConceptCompressor, GraphEpisodicBridge

from cognia_embedding import get_embedding_queue

try:
    from cognia_deferred import DeferredMaintenance, IdleHypothesisScheduler
    HAS_DEFERRED = True
except ImportError:
    HAS_DEFERRED = False

# ── Paso 3: módulos de aprendizaje ────────────────────────────────────
try:
    from teacher_interface import get_teacher
    HAS_TEACHER = True
except ImportError:
    HAS_TEACHER = False

# ── Paso 4: SelfArchitect ─────────────────────────────────────────────
try:
    from self_architect import SelfArchitect
    HAS_SELF_ARCHITECT = True
except ImportError:
    HAS_SELF_ARCHITECT = False

try:
    from model_collapse_guard import ModelCollapseGuard
    HAS_COLLAPSE_GUARD = True
except ImportError:
    HAS_COLLAPSE_GUARD = False

try:
    from language_corrector import LanguageCorrector
    HAS_LANGUAGE_CORRECTOR = True
except ImportError:
    HAS_LANGUAGE_CORRECTOR = False


class Cognia:
    """
    Cognia v3 — Arquitectura Cognitiva Híbrida Simbólico-Neural.

    FLUJO COGNITIVO:
      INPUT → Embeddings → WorkingMemory → AttentionSystem → EpisodicRecall
           → KnowledgeGraph → SpreadingActivation → InferenceEngine
           → TemporalMemory (predicción) → RESPUESTA

    CICLO DE SUEÑO:
      ConsolidationModule + ConceptCompressor + GraphEpisodicBridge

    OBJETIVO ENERGÉTICO: 5-20W (edge AI)
    """

    def __init__(self, db_path: str = DB_PATH):
        print("\n🧠 Iniciando COGNIA v3...")
        self.db = db_path
        init_db(db_path)

        # Módulos heredados de v2
        self.perception    = PerceptionModule()
        self.working_mem   = WorkingMemory()
        self.episodic      = EpisodicMemory(db_path)
        self.semantic      = SemanticMemory(db_path)
        self.forgetting    = ForgettingModule(db_path)
        self.consolidation = ConsolidationModule(db_path, self.semantic)
        self.contradiction = ContradictionDetector(db_path)
        self.world_model   = WorldModelModule(db_path)
        self.hypothesis    = HypothesisModule(db_path, self.semantic)
        self.metacog       = MetacognitionModule(db_path)
        self.evaluation    = EvaluationModule(self.episodic, self.metacog)
        self.curiosity     = CuriosityModule(db_path)

        # Módulos nuevos v3
        self.kg            = KnowledgeGraph(db_path)
        self.inference     = InferenceEngine(db_path, self.kg)
        self.goal_system   = GoalSystem(db_path)
        self.temporal_mem  = TemporalMemory(db_path)
        self.attention     = AttentionSystem()
        self.compressor    = ConceptCompressor(db_path, self.semantic)
        self.bridge        = GraphEpisodicBridge(db_path, self.kg)

        # Módulos v3.1
        self.chat_history  = ChatHistory(db_path)
        self.user_profile  = UserProfile(db_path)

        self.interaction_count       = 0
        self.consolidation_interval  = 8
        self.forgetting_interval     = 15
        self._introspect_cache       = None
        self._introspect_ts          = 0.0

        # Monitor de fatiga
        if HAS_FATIGUE:
            from .config import get_fatigue_monitor
            self.fatigue = get_fatigue_monitor()
        else:
            self.fatigue = None

        self.planner = ReasoningPlanner(db_path) if HAS_PLANNER else None
        if self.planner:
            print("✅ ReasoningPlanner activo")

        self.curiosity_engine = ActiveCuriosityEngine(db_path) if HAS_CURIOSITY_ENGINE else None
        if self.curiosity_engine:
            print("✅ CuriosityEngine activo")

        if HAS_RESEARCH_ENGINE:
            print("✅ ResearchEngine (investigación autónoma durante sueño) activo")

        self._hobby_idle_seconds    = 0.0
        self._last_interaction_time = time.time()
        if HAS_PROGRAM_CREATOR:
            print("✅ ProgramCreator (hobby de programación) activo")

        self._lang = self.user_profile.get("lang", "es")

        self._embedding_queue = get_embedding_queue(
            throttle_controller=self.fatigue,
            vector_dim=VECTOR_DIM,
        )

        if HAS_DEFERRED:
            self._maintenance = DeferredMaintenance(self, throttle_controller=self.fatigue)
            self._hyp_scheduler = IdleHypothesisScheduler(self, min_idle_s=60.0, cpu_threshold=40.0)
        else:
            self._maintenance = None
            self._hyp_scheduler = None

        # ── Paso 3: módulos de aprendizaje ─────────────────────────────
        self.teacher = get_teacher(self, db_path) if HAS_TEACHER else None
        if self.teacher:
            print("✅ TeacherInterface activo")

        self.collapse_guard = ModelCollapseGuard(db_path) if HAS_COLLAPSE_GUARD else None
        if self.collapse_guard:
            print("✅ ModelCollapseGuard activo")

        self.language_corrector = LanguageCorrector() if HAS_LANGUAGE_CORRECTOR else None
        if self.language_corrector:
            print("✅ LanguageCorrector activo")

        # ── Paso 4: SelfArchitect ──────────────────────────────────────
        if HAS_SELF_ARCHITECT:
            try:
                self.architect = SelfArchitect(db_path=db_path, cognia_instance=self)
                print("✅ SelfArchitect v4 activo")
            except Exception:
                self.architect = None
        else:
            self.architect = None

        print("✅ COGNIA v3.2 lista. [KG + Inferencia + Objetivos + Predicción Temporal + Historial]\n")

    # ── API pública ────────────────────────────────────────────────────

    def process(self, observation: str) -> str:
        result = self.observe(observation)
        return self._format_result(result)

    def learn(self, observation: str, label: str) -> str:
        result = self.observe(observation, provided_label=label)
        return self._format_result(result)

    # ── Método core ────────────────────────────────────────────────────

    def observe(self, observation: str, provided_label: str = None) -> dict:
        self.interaction_count += 1

        _observe_start = time.perf_counter()

        reasoning_plan = None
        plan_depth = 3
        if self.planner:
            reasoning_plan = self.planner.plan_reasoning_depth(observation)
            plan_depth = reasoning_plan["recommended_depth"]

        if self.fatigue:
            self.fatigue.start_cycle()
        adaptations = self.fatigue.get_adaptations() if self.fatigue else {
            "top_k_retrieval": 10, "attention_threshold": 0.25,
            "inference_max_steps": 3, "enable_temporal": True,
            "enable_bridge": True, "embedding_cache_only": False,
            "consolidation_defer": False, "mode": "normal",
        }

        effective_max_steps = min(plan_depth, adaptations["inference_max_steps"])

        features = self.perception.extract_features(observation)
        vec = features["vector"]
        emotion = features["emotion"]

        working_hits = self.working_mem.find_similar_in_buffer(vec, threshold=0.7)

        top_k = adaptations["top_k_retrieval"]
        similar_raw = self.episodic.retrieve_similar(vec, top_k=top_k + 5)

        curiosity_score = 0.0
        if self.curiosity_engine:
            _prov_label = None
            if similar_raw:
                _lbs = [s.get("label") for s in similar_raw if s.get("label")]
                if _lbs:
                    _prov_label = Counter(_lbs).most_common(1)[0][0]
            curiosity_score = self.curiosity_engine.get_curiosity_score(
                observation, similar_count=len(similar_raw), top_label=_prov_label)
            _ok = (not self.fatigue) or self.fatigue._fatigue_score < 60
            if curiosity_score > 0.6 and _ok:
                similar_raw = self.episodic.retrieve_similar(vec, top_k=top_k + 8)
            if curiosity_score > 0.7 and effective_max_steps == 1 and _ok:
                effective_max_steps = 2

        original_threshold = self.attention.threshold
        if self.fatigue and adaptations["attention_threshold"] != original_threshold:
            self.attention.threshold = adaptations["attention_threshold"]
        similar = self.attention.filter_memories(similar_raw, vec)
        if self.fatigue and adaptations["attention_threshold"] != original_threshold:
            self.attention.threshold = original_threshold
        if not similar:
            similar = similar_raw[:min(5, top_k)]

        reactivated = self.forgetting.reactivate(vec)
        if reactivated:
            similar = reactivated[:2] + similar[:top_k - 2]

        assessment = self.metacog.assess_confidence(similar)

        activated_concepts = []
        top_label = assessment.get("top_label")
        if top_label:
            activated_concepts = self.semantic.spreading_activation(top_label, depth=2)

        kg_facts = []
        if top_label:
            kg_facts = self.kg.get_facts(top_label)[:5]

        inferences = []
        max_inf_steps = effective_max_steps
        if top_label and max_inf_steps > 0:
            inferences = self.inference.infer(top_label, max_steps=max_inf_steps)[:3]
            inherited = self.inference.infer_properties(top_label)[:2]
            inferences.extend(inherited)

        temporal_predictions = []
        if adaptations["enable_temporal"]:
            temporal_predictions = self.temporal_mem.predict_from_context()

        surprise = 0.0
        if similar:
            top_sim = similar[0]["similarity"]
            surprise = max(0.0, 1.0 - top_sim)

        if provided_label:
            # ── MODO APRENDIZAJE ───────────────────────────────────────
            contradiction = self.contradiction.check(observation, provided_label, vec, self.semantic)
            if contradiction:
                self.contradiction.log_contradiction(
                    provided_label,
                    f"Antes: {assessment.get('top_label', '?')}",
                    f"Nuevo: {provided_label}"
                )

            old_prediction = assessment.get("top_label")

            ep_id = self.episodic.store(
                observation=observation, label=provided_label, vector=vec,
                confidence=0.6, importance=1.0, emotion=emotion, surprise=surprise,
                context_tags=self.working_mem.get_context_labels()[-3:]
            )

            self.working_mem.add(observation, provided_label, vec, emotion, 0.6)

            words = features["words"][:3]
            for w in words:
                if len(w) > 3:
                    self.world_model.add_relation(w, "es_tipo", provided_label, 0.6)

            self.semantic.update_concept(provided_label, vec,
                                          confidence_delta=0.05, emotion_score=emotion["score"])

            if HAS_LANGUAGE_ENGINE:
                try:
                    from language_engine import get_language_engine
                    get_language_engine(self).invalidate_concept(provided_label)
                except Exception:
                    pass

            kg_triples = self.bridge.process_episode(observation, provided_label)
            self.temporal_mem.observe_concept(provided_label)

            eval_result = None
            if old_prediction:
                eval_result = self.evaluation.evaluate_prediction(old_prediction, provided_label, similar)

            metacog_state = self.metacog.introspect()
            self.goal_system.auto_generate_goals(metacog_state)

            result = {
                "action": "learned",
                "label": provided_label,
                "observation": observation,
                "previous_prediction": old_prediction,
                "was_error": (eval_result["correct"] == False) if eval_result else False,
                "assessment": assessment,
                "emotion": emotion,
                "surprise": surprise,
                "contradiction": contradiction,
                "reactivated": [r["observation"][:30] for r in reactivated],
                "working_hits": len(working_hits),
                "kg_triples_added": len(kg_triples),
                "kg_triples": [(s, p, o) for s, p, o in kg_triples[:3]],
                "curiosity_score": round(curiosity_score, 3),
            }

            # ── Paso 3: reportar al collapse_guard ────────────────────
            if self.collapse_guard and result.get("was_error"):
                _cg_report = self.collapse_guard.get_collapse_report()
                if _cg_report["risk_level"] in ("medium", "high"):
                    result["_collapse_risk"] = _cg_report["risk_level"]

        else:
            # ── MODO INFERENCIA ────────────────────────────────────────
            self.episodic.store(
                observation=observation, label=None, vector=vec,
                confidence=0.3, importance=0.5, emotion=emotion, surprise=surprise,
                context_tags=[]
            )
            self.working_mem.add(observation, None, vec, emotion, 0.3)

            inference_answer = None
            if "?" in observation:
                inference_answer = self.inference.can_answer(observation)

            question = None
            if self.curiosity.should_explore(assessment):
                question = self.curiosity.generate_question(observation, assessment, similar)

            pattern_hypothesis = None
            if self._hyp_scheduler:
                pattern_hypothesis = self._hyp_scheduler.maybe_run(similar)

            if top_label:
                self.temporal_mem.observe_concept(top_label)

            result = {
                "action": "infer",
                "observation": observation,
                "prediction": assessment.get("top_label"),
                "confidence": assessment["confidence"],
                "state": assessment["state"],
                "similar": [{"obs": s["observation"][:40], "label": s["label"],
                              "sim": round(s["similarity"], 3),
                              "attention": s.get("attention_score", 0),
                              "emotion": s.get("emotion", {})}
                             for s in similar[:3]],
                "should_ask": assessment["should_ask"],
                "question": question,
                "pattern_hypothesis": pattern_hypothesis,
                "assessment": assessment,
                "activated_concepts": activated_concepts[:4],
                "reactivated": [r["observation"][:30] for r in reactivated],
                "emotion_detected": emotion,
                "kg_facts": kg_facts[:3],
                "inferences": inferences[:3],
                "temporal_predictions": temporal_predictions[:2],
                "inference_answer": inference_answer,
                "curiosity_score": round(curiosity_score, 3),
            }

        # ── Fatiga cognitiva ───────────────────────────────────────────
        _cycle_ms = 0.0
        if self.fatigue:
            fatigue_score = self.fatigue.end_cycle(
                ops_count=len(inferences) + len(kg_facts) + len(activated_concepts),
                cache_hits=0, cache_misses=0,
                expensive=1 if not __import__("importlib").util.find_spec("sentence_transformers") else 0,
            )
            result["fatigue"] = {
                "score": round(fatigue_score, 1),
                "level": self.fatigue.level,
                "mode": adaptations["mode"],
            }
            if self.fatigue.should_propose_optimization():
                result["_needs_arch_optimization"] = True
            if self.fatigue._score_history:
                _cycle_ms = self.fatigue._score_history[-1].get("cycle_ms", 0.0)

        # ── energy_log ────────────────────────────────────────────────
        try:
            from .config import _embedding_cache
            _e_est = round(_cycle_ms / max(1.0, NORMAL_CYCLE_MS_ENERGY), 3)
            _ec = db_connect(self.db)
            _ec.execute(
                "INSERT INTO energy_log (timestamp, interaction_id, embedding_calls,"
                " retrieval_ops, inference_steps, cache_hits, cache_misses,"
                " latency_ms, energy_estimate) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(), self.interaction_count,
                 len(_embedding_cache), len(similar) if similar else 0,
                 len(inferences),
                 int(sum(self.fatigue._cache_hits))   if self.fatigue else 0,
                 int(sum(self.fatigue._cache_misses)) if self.fatigue else 0,
                 round(_cycle_ms, 1), _e_est))
            _ec.commit(); _ec.close()
        except Exception:
            pass

        # ── Planner ───────────────────────────────────────────────────
        if self.planner and reasoning_plan:
            _lat = (time.perf_counter() - _observe_start) * 1000.0
            _q = float(result.get("confidence", result.get("assessment", {}).get("confidence", 0.5)))
            self.planner.save_plan(observation, reasoning_plan, latency_ms=_lat, quality_score=_q)
            result["_plan"] = {
                "complexity": reasoning_plan["complexity"],
                "depth_used": max_inf_steps,
                "cache_hit": reasoning_plan["cache_hit"],
                "sub_tasks": reasoning_plan.get("sub_tasks", []),
            }

        if self._maintenance:
            self._maintenance.tick(self.interaction_count)
        return result

    # ── Formateo de respuestas ─────────────────────────────────────────

    def _format_result(self, result: dict) -> str:
        lines = []
        action = result.get("action", "")

        if action == "learned":
            _obs_display = result.get("observation", "")
            if self.language_corrector:
                _obs_display = self.language_corrector.clean(_obs_display)
            lines.append(f"✅ Aprendido: '{result['label']}'")
            if result.get("was_error"):
                lines.append(f"   ↳ Corrección: antes creía '{result['previous_prediction']}'")
            emotion = result.get("emotion", {})
            if emotion.get("label") != "neutral":
                lines.append(f"   💭 Emoción: {emotion['label']} (intensidad: {emotion.get('intensity',0):.0%})")
            if result.get("contradiction"):
                c = result["contradiction"]
                lines.append(f"   ⚠️  Contradicción: {c['message']}")
            kg_n = result.get("kg_triples_added", 0)
            if kg_n > 0:
                triples_str = "; ".join(f"{s}→{p}→{o}" for s, p, o in result.get("kg_triples", []))
                lines.append(f"   🕸️  Grafo: +{kg_n} relaciones [{triples_str}]")
            if result.get("reactivated"):
                lines.append(f"   🔄 Reactivado: {result['reactivated'][0][:40]}")

        elif action == "infer":
            pred = result.get("prediction")
            conf = result.get("confidence", 0)
            state = result.get("state", "ignorant")
            icons = {"confident": "🟢", "uncertain": "🟡", "confused": "🟠", "ignorant": "🔴"}
            icon = icons.get(state, "❓")

            if pred:
                lines.append(f"{icon} Creo que es: '{pred}' (confianza: {conf:.0%})")
            else:
                lines.append(f"{icon} No sé qué es esto todavía")

            if result.get("inference_answer"):
                ia = result["inference_answer"]
                lines.append(f"   🔗 Inferencia: {ia['justification']} (conf: {ia['confidence']:.0%})")

            if result.get("activated_concepts"):
                acts = [a["concept"] for a in result["activated_concepts"][:3]]
                lines.append(f"   🌐 Activados: {', '.join(acts)}")

            if result.get("kg_facts"):
                kf = result["kg_facts"][0]
                lines.append(f"   📚 Grafo: {kf['subject']} --{kf['predicate']}--> {kf['object']}")

            if result.get("temporal_predictions"):
                tp = result["temporal_predictions"]
                preds_str = ", ".join(f"{p['concept']}({p['score']:.2f})" for p in tp[:2])
                lines.append(f"   ⏭️  Predicción siguiente: {preds_str}")

            if result.get("inferences"):
                inf = result["inferences"][0]
                just = inf.get("justification", inf.get("property", ""))
                lines.append(f"   💡 Inferido: {just[:80]}")

            if result.get("question"):
                lines.append(f"   ❓ {result['question']}")
            if result.get("pattern_hypothesis"):
                lines.append(f"   💭 {result['pattern_hypothesis']}")

        return "\n".join(lines)

    # ── Comandos de gestión ────────────────────────────────────────────

    def correct(self, observation: str, wrong_label: str, correct_label: str) -> str:
        vec = self.perception.encode(observation)
        self.episodic.store(
            observation, correct_label, vec,
            confidence=0.85, importance=1.8,
            emotion={"score": -0.3, "label": "negativo", "intensity": 0.5},
            surprise=0.7
        )
        self.semantic.update_concept(correct_label, vec, f"Corregido desde '{wrong_label}'", 0.15)
        self.metacog.log_decision("correct", wrong_label, correct_label, was_error=True)
        self.kg.add_triple(observation.split()[0] if observation else "?",
                           "is_a", correct_label, weight=1.2, source="correction")
        return f"✏️ Corregido: '{wrong_label}' → '{correct_label}'. Lo recordaré mejor ahora."

    def generate_hypothesis(self, a: str, b: str) -> str:
        result = self.hypothesis.generate(a, b, kg=self.kg)
        if not result or "error" in result:
            return result.get("error", "No pude generar hipótesis") if result else "No pude generar hipótesis"
        return (f"💡 Hipótesis (confianza: {result['confidence']:.0%}):\n"
                f"{result['hypothesis']}\n"
                f"Similitud entre conceptos: {result['similarity']:.2f}")

    def introspect(self) -> dict:
        now = time.time()
        if self._introspect_cache and (now - self._introspect_ts) < 2.0:
            return self._introspect_cache

        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0")
            active = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=1")
            forgotten = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM semantic_memory")
            concepts = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM hypotheses")
            hyps = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM decision_log")
            total_dec = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM decision_log WHERE was_error=1")
            errors = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM contradictions WHERE resolved=0")
            contradictions = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE next_review <= ? AND forgotten=0",
                      (datetime.now().isoformat(),))
            due_review = c.fetchone()[0]
            c.execute("SELECT emotion_label, COUNT(*) FROM episodic_memory WHERE forgotten=0 GROUP BY emotion_label")
            emotion_dist = dict(c.fetchall())
            c.execute("SELECT COUNT(*) FROM knowledge_graph")
            kg_edges = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM temporal_sequences")
            seq_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM goal_system WHERE status='pending'")
            pending_goals = c.fetchone()[0]
        finally:
            conn.close()

        error_rate = errors / max(1, total_dec)
        result = {
            "active_memories": active, "forgotten_memories": forgotten,
            "concepts": concepts, "hypotheses": hyps,
            "error_rate": round(error_rate, 3),
            "contradictions_pending": contradictions,
            "due_for_review": due_review, "emotion_distribution": emotion_dist,
            "total_decisions": total_dec, "kg_edges": kg_edges,
            "temporal_sequences": seq_count, "pending_goals": pending_goals,
        }
        self._introspect_cache = result
        self._introspect_ts = now
        return result

    def list_concepts(self) -> str:
        concepts = self.semantic.list_all()
        if not concepts:
            return "Sin conceptos semánticos todavía."
        lines = ["📚 Conceptos semánticos:\n"]
        for c in concepts:
            emo_icon = "😊" if c["emotion_avg"] > 0.2 else ("😔" if c["emotion_avg"] < -0.2 else "😐")
            lines.append(f"  • {c['concept']} (conf: {c['confidence']:.0%}, soporte: {c['support']}) {emo_icon}")
        return "\n".join(lines)

    def forget_cycle(self) -> str:
        stats = self.forgetting.decay_cycle()
        return (f"🌊 Ciclo de olvido:\n"
                f"   Revisados:   {stats['total_checked']}\n"
                f"   Olvidados:   {stats['forgotten']}\n"
                f"   Comprimidos: {stats['compressed']}")

    def sleep(self) -> str:
        """Ciclo de sueño v3: consolidación + compresión + actualización del grafo."""
        start = time.time()

        consolidation = self.consolidation.sleep_consolidation()
        compression   = self.compressor.compress_all()
        bridge_result = self.bridge.process_recent_episodes()
        forgetting    = self.forgetting.decay_cycle()

        resolved_contradictions = self.contradiction.auto_resolve_old(max_age_days=30)

        meta_state = self.metacog.introspect()
        new_goals = self.goal_system.auto_generate_goals(meta_state)

        duration_ms = int((time.time() - start) * 1000)

        # Hipótesis espontánea
        hipotesis_n = 0
        try:
            buenos = [c for c in self.semantic.list_all()
                      if c["confidence"] >= 0.55 and c["support"] >= 2]
            if len(buenos) >= 4:
                for _ in range(6):
                    par = random.sample(buenos, 2)
                    ca_obj = self.semantic.get_concept(par[0]["concept"])
                    cb_obj = self.semantic.get_concept(par[1]["concept"])
                    if ca_obj and cb_obj:
                        sim_par = cosine_similarity(ca_obj["vector"], cb_obj["vector"])
                        if sim_par < 0.65:
                            self.hypothesis.generate(par[0]["concept"], par[1]["concept"],
                                                     kg=self.kg, usar_ollama=True)
                            hipotesis_n += 1
                            break
        except Exception:
            pass

        # Limpieza de ruido
        try:
            limpieza = limpiar_episodios_ruido(self.db)
        except Exception:
            limpieza = {"episodios_limpiados": 0, "kg_triples_eliminados": 0}

        extras = ""
        if limpieza["episodios_limpiados"] > 0 or limpieza["kg_triples_eliminados"] > 0:
            extras = (f"\n   Limpieza:       {limpieza['episodios_limpiados']} "
                      f"preguntas archivadas, {limpieza['kg_triples_eliminados']} triples KG")

        # Investigación autónoma
        research_info = ""
        if HAS_RESEARCH_ENGINE:
            try:
                from cognia.research_engine import run_research_session, format_sleep_summary
                research_session = run_research_session(cognia_instance=self, db_path=self.db,
                                                         max_questions=3, verbose=False)
                research_info = format_sleep_summary(research_session)
            except Exception:
                pass

        # Hobby de programación
        hobby_info = ""
        if HAS_PROGRAM_CREATOR:
            try:
                from cognia.program_creator import maybe_run_hobby
                if random.random() < 0.4:
                    hobby_result = maybe_run_hobby(cognia_instance=self, idle_seconds=60.0,
                                                   min_idle=60.0, probability=1.0, storage_dir=None)
                    if hobby_result and hobby_result.stored > 0:
                        hobby_info = f"\n   Programas hobby:  +{hobby_result.stored} guardados"
                    elif hobby_result:
                        hobby_info = f"\n   Programas hobby:  {hobby_result.attempted} intentos, ninguno guardado"
            except Exception:
                pass

        # Language Engine — evolución de prompts + reporte al architect
        engine_info = ""
        if HAS_LANGUAGE_ENGINE:
            try:
                from language_engine import get_language_engine
                engine = get_language_engine(self)
                evolved = engine.run_prompt_evolution()
                if evolved:
                    engine_info = f"\n   Prompts evolucionados: {len(evolved)}"
                engine.cache.clear_expired()

                # Paso 4: reportar zonas débiles al architect
                if self.architect:
                    try:
                        zones = engine.report_weak_zones()
                        if zones.get("engine_fallback_rate", 0) > 0.20:
                            engine_info += (
                                f"\n   ⚠️  Engine fallback rate: "
                                f"{zones['engine_fallback_rate']:.0%} — "
                                f"evaluación arquitectural programada"
                            )
                    except Exception:
                        pass
            except Exception:
                pass

        # Paso 4: SelfArchitect — evaluación + energy loop durante el sueño
        architect_info = ""
        if self.architect:
            try:
                # Energy optimization loop (micro-ajustes automáticos)
                energy_result = self.architect.energy_loop.run_loop()
                if energy_result.get("adjusted"):
                    architect_info += (
                        f"\n   ⚡ Auto-ajuste energético: "
                        f"{energy_result['actions'][-1].get('message','')}"
                    )

                # Evaluación arquitectural completa (si no hay fatiga crítica)
                fatigue_ok = (
                    not self.fatigue or
                    self.fatigue._fatigue_score < 75
                )
                if fatigue_ok:
                    eval_result = self.architect.run_evaluation(triggered_by="sleep")
                    if eval_result and not eval_result.get("skipped"):
                        score = eval_result.get("score", 0)
                        n_props = eval_result.get("proposals_generated", 0)
                        has_crit = eval_result.get("has_critical", False)
                        crit_tag = " 🔴 CRÍTICO" if has_crit else ""
                        architect_info += (
                            f"\n   🏗️  Architect score: {score:.1f}/100"
                            f"{crit_tag}"
                            + (f", {n_props} propuesta(s)" if n_props else "")
                        )
            except Exception:
                pass

        return (f"😴 CICLO DE SUEÑO v3 completado ({duration_ms}ms):\n"
                f"   Consolidación:  {consolidation['concepts_consolidated']} conceptos, "
                f"{consolidation['associations_created']} asociaciones\n"
                f"   Compresión:     {compression['labels_processed']} labels, "
                f"{compression['total_compressed']} episodios comprimidos\n"
                f"   Grafo:          +{bridge_result['triples_added']} relaciones\n"
                f"   Olvido:         {forgetting['forgotten']} episodios\n"
                f"   Contradicciones resueltas: {resolved_contradictions}\n"
                f"   Nuevos objetivos: {len(new_goals)}\n"
                f"   Hipótesis generadas: {hipotesis_n}"
                + extras + research_info + hobby_info + engine_info + architect_info)

    def fatigue_status(self) -> str:
        if not self.fatigue:
            return "⚠️  Monitor de fatiga cognitiva no disponible."
        return self.fatigue.format_status()

    def review_due(self) -> str:
        due = self.episodic.get_due_for_review()
        if not due:
            return "✅ No hay episodios pendientes de repaso."
        lines = [f"📅 {len(due)} episodios para repasar:\n"]
        for ep in due[:5]:
            lines.append(f"  [{ep['id']}] '{ep['observation'][:50]}' → {ep['label']} "
                         f"(revisado {ep['review_count']}x)")
        lines.append("\nUsa 'repasar <id> correcto' o 'repasar <id> incorrecto'")
        return "\n".join(lines)

    def mark_review(self, ep_id: int, correct: bool) -> str:
        self.episodic.mark_reviewed(ep_id, correct)
        return f"✅ Episodio {ep_id} marcado como {'correcto' if correct else 'incorrecto'}."

    def show_contradictions(self) -> str:
        items = self.contradiction.list_unresolved()
        if not items:
            return "✅ Sin contradicciones detectadas."
        lines = [f"⚠️ {len(items)} contradicciones sin resolver:\n"]
        for item in items:
            lines.append(f"  • [{item['concept']}] {item['claim_a']} vs {item['claim_b']}")
        return "\n".join(lines)

    def explain(self, observation: str) -> str:
        vec = self.perception.encode(observation)
        similar = self.episodic.retrieve_similar(vec, top_k=3)
        assessment = self.metacog.assess_confidence(similar)
        activated = []
        if assessment.get("top_label"):
            activated = self.semantic.spreading_activation(assessment["top_label"])

        lines = [f"🔍 Explicación para: '{observation}'",
                 f"Estado: {assessment['state']} (confianza: {assessment['confidence']:.0%})",
                 f"Razón: {assessment['reason']}"]

        if similar:
            lines.append("\nRecuerdos más relevantes:")
            for s in similar[:3]:
                emo = s.get("emotion", {}).get("label", "neutral")
                lines.append(f"  • '{s['observation'][:40]}' → {s['label']} "
                              f"(sim={s['similarity']:.2f}, {emo})")

        if activated:
            lines.append("\nConceptos activados:")
            for a in activated[:4]:
                lines.append(f"  → {a['concept']} (activación: {a['activation']:.2f})")

        top_label = assessment.get("top_label", "")
        if top_label:
            kg_facts = self.kg.get_facts(top_label)
            if kg_facts:
                lines.append("\nHechos en el grafo de conocimiento:")
                for f in kg_facts[:4]:
                    lines.append(f"  🕸️  {f['subject']} --{f['predicate']}--> {f['object']} (peso: {f['weight']:.1f})")
            ancestors = self.kg.get_ancestors(top_label)
            if ancestors:
                lines.append(f"  Jerarquía: {top_label} → {'→'.join(ancestors)}")
            inferences = self.inference.infer(top_label)
            if inferences:
                lines.append("\nInferencias derivadas:")
                for inf in inferences[:3]:
                    just = inf.get("justification", inf.get("property", ""))
                    lines.append(f"  💡 {just[:80]}")

        return "\n".join(lines)

    # ── Comandos nuevos v3 ─────────────────────────────────────────────

    def show_graph(self, concept: str) -> str:
        facts = self.kg.get_facts(concept)
        if not facts:
            return f"❌ No hay hechos sobre '{concept}' en el grafo de conocimiento."
        lines = [f"🕸️  Knowledge Graph: '{concept}'\n"]
        by_pred = defaultdict(list)
        for f in facts:
            if f["subject"] == concept:
                by_pred[f["predicate"]].append(f"→ {f['object']} (peso: {f['weight']:.1f})")
            else:
                by_pred[f"← {f['predicate']}"].append(f"← {f['subject']} (peso: {f['weight']:.1f})")
        for pred, items in sorted(by_pred.items()):
            lines.append(f"  [{pred}]")
            for item in items[:5]:
                lines.append(f"    {item}")
        ancestors = self.kg.get_ancestors(concept)
        if ancestors:
            lines.append(f"\n  Jerarquía: {concept} → {'→'.join(ancestors)}")
        return "\n".join(lines)

    def add_fact(self, subject: str, predicate: str, obj: str) -> str:
        is_new = self.kg.add_triple(subject.lower(), predicate.lower(), obj.lower(),
                                     weight=1.0, source="manual")
        action = "agregada" if is_new else "reforzada"
        return f"✅ Relación {action}: {subject} --{predicate}--> {obj}"

    def apply_feedback(self, response_id: str, correct: bool,
                       correction_text: str = None) -> str:
        self.chat_history.add_feedback(response_id, 1 if correct else -1)
        self.metacog.log_decision(action="feedback", prediction="response",
                                  outcome="correct" if correct else "incorrect",
                                  was_error=not correct, learned=correction_text or "")
        if correction_text:
            vec = self.perception.encode(correction_text)
            emotion = {"score": 0.3 if correct else -0.3,
                       "label": "positivo" if correct else "negativo", "intensity": 0.5}
            self.episodic.store(
                observation=correction_text, label=None, vector=vec,
                confidence=0.8, importance=2.0, emotion=emotion, surprise=0.5,
                context_tags=["feedback", "correction" if not correct else "confirmation"]
            )
            self.working_mem.add(correction_text, None, vec, emotion, 0.8)
            return "✅ Feedback registrado. Corrección guardada con alta prioridad."
        return f"✅ Feedback {'positivo' if correct else 'negativo'} registrado."

    def get_memory_health(self) -> dict:
        d = self.metacog.introspect()
        total = d.get("active_memories", 0)
        contradicciones = d.get("contradictions_pending", 0)
        error_rate = d.get("error_rate", 1.0)
        kg_edges = d.get("kg_edges", 0)
        concepts = d.get("concepts", 0)
        chat_count = self.chat_history.count()

        mem_score   = min(100, total * 2)
        kg_score    = min(100, kg_edges / 20)
        conc_score  = min(100, concepts * 4)
        error_score = max(0, 100 - error_rate * 100)
        contra_score = max(0, 100 - contradicciones * 2)

        health = (mem_score * 0.20 + kg_score * 0.30 +
                  conc_score * 0.20 + error_score * 0.15 + contra_score * 0.15)

        return {
            "score": round(health, 1),
            "label": ("Excelente" if health >= 80 else "Buena" if health >= 60
                      else "Regular" if health >= 40 else "Necesita atención"),
            "components": {
                "memorias": round(mem_score, 1), "knowledge_graph": round(kg_score, 1),
                "conceptos": round(conc_score, 1), "precision": round(error_score, 1),
                "coherencia": round(contra_score, 1),
            },
            "stats": {
                "episodios": total, "kg_edges": kg_edges, "conceptos": concepts,
                "error_rate": round(error_rate, 3), "contradicciones": contradicciones,
                "chats_totales": chat_count,
            }
        }

    def show_goals(self) -> str:
        return self.goal_system.format_goals()

    def predict_next(self, concept: str) -> str:
        preds = self.temporal_mem.predict_next(concept)
        if not preds:
            return f"❌ Sin datos de secuencias para '{concept}' todavía."
        lines = [f"⏭️  Predicciones temporales para '{concept}':\n"]
        for p in preds:
            bar = "█" * int(p["probability"] * 20)
            lines.append(f"  {bar} {p['concept']} ({p['probability']:.0%}, {p['count']}x visto)")
        return "\n".join(lines)

    def infer_about(self, concept: str) -> str:
        inferences = self.inference.infer(concept, max_steps=3)
        inherited  = self.inference.infer_properties(concept)
        if not inferences and not inherited:
            return f"❌ No se pudieron derivar inferencias sobre '{concept}'."
        lines = [f"💡 Inferencias sobre '{concept}':\n"]
        for inf in inferences[:5]:
            conf = inf.get("confidence", 0)
            just = inf.get("justification", "")
            lines.append(f"  [{inf.get('type', 'rule')}] {just[:80]} (conf: {conf:.0%})")
        if inherited:
            lines.append("\n  Propiedades heredadas:")
            for prop in inherited[:3]:
                lines.append(f"  ↳ {concept} {prop['property']} {prop['value']} "
                              f"(de {prop['inherited_from']}, conf: {prop['confidence']:.0%})")
        return "\n".join(lines)
