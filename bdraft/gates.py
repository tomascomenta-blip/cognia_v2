"""
bdraft/gates.py
===============
Pre-registered kill/pass gates for the BDraft track, per
planes/DSPARK_GEMMA_DRAFT_MODEL.md section 3. The thresholds live here as
named constants so every measurement script checks against the SAME numbers
that were registered before any code/training existed. Measurement protocol
(median of >=3 runs, fixed suites/seeds) is in the doc; these functions only
apply the thresholds.
"""

G2_TECHO_MIN = 1.5    # G2: theoretical ceiling with an UNTRAINED draft
G3_TOP1_MIN = 0.30    # G3: top-1 acc of the block's 1st token on val
G3_TAU_MIN = 1.5      # G3: greedy accepted length at 10% of the budget
G4A_TAU_CODE = 2.5    # G4a: tau (greedy) on code/math suites
G4A_TAU_CHAT = 1.8    # G4a: tau (greedy) on chat es/en suite
G4B_REL_MIN = 1.8     # G4b(i): speedup vs AR of the SAME Python pipeline
G4B_ABS_MIN = 1.2     # G4b(ii): absolute tok/s vs llama.cpp base B0
G5_REL_MIN = 0.05     # G5: confidence head must add >=5% relative speedup


def g2_techo(t_ciclo_s: float, t_tok_base_s: float,
             block_size: int = 8) -> tuple[float, bool]:
    """G2 theoretical ceiling, measured BEFORE training anything:
    techo = block_size * T_tok_base / T_ciclo, where T_ciclo is one full
    draft(block)+verify cycle with an untrained draft. Below G2_TECHO_MIN
    the track is killed (same math that buried speculative on CPU: 0.464x)."""
    techo = block_size * t_tok_base_s / t_ciclo_s
    return techo, techo >= G2_TECHO_MIN


def g3_early_signal(top1_acc: float, tau_greedy: float) -> bool:
    """G3 at ~10% of the training budget: BOTH first-token top-1 accuracy
    and greedy accepted length must clear their floors, else kill (or one
    single retry with adjusted lr/data, max +5h)."""
    return top1_acc >= G3_TOP1_MIN and tau_greedy >= G3_TAU_MIN


def g4_final(tau_code: float, tau_chat: float, speedup_rel: float,
             speedup_abs: float) -> dict:
    """G4 at the end of v0. Returns the verdict per sub-gate:
    g4a needs tau >= 2.5 on code/math AND >= 1.8 on chat; g4b needs
    >= 1.8x vs the same-pipeline AR baseline AND >= 1.2x absolute vs
    llama.cpp base B0. 'pasa' is the full G4 (both)."""
    g4a_code = tau_code >= G4A_TAU_CODE
    g4a_chat = tau_chat >= G4A_TAU_CHAT
    g4b_rel = speedup_rel >= G4B_REL_MIN
    g4b_abs = speedup_abs >= G4B_ABS_MIN
    return {
        "g4a_tau_code": g4a_code,
        "g4a_tau_chat": g4a_chat,
        "g4a": g4a_code and g4a_chat,
        "g4b_rel": g4b_rel,
        "g4b_abs": g4b_abs,
        "g4b": g4b_rel and g4b_abs,
        "pasa": g4a_code and g4a_chat and g4b_rel and g4b_abs,
    }
