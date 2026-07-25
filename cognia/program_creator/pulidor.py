# -*- coding: utf-8 -*-
"""
pulidor.py — LOOP THINKING: el producto se evalua y se decide si entra en OTRO
ciclo de pensamiento, priorizando el pulido sobre la rapidez.

PEDIDO DEL DUENO (2026-07-24): "un loop thinking donde el producto 'final' se
evalua y se decide si se entra en otro ciclo... el modelo va repitiendo sobre un
goal (especificado por el usuario o la idea/sueno propuesta por el modelo)...
casi todo autonomo y facil de usar".

EL CICLO (cada vuelta):
  1. CONSTRUIR — ciclo 1: el lazo diseno-a-codigo completo (construir_para_mockup,
     con arbitro en-lazo). Ciclos 2+: REPARAR el html existente con los cambios
     que pidio el pensador (reparar_web) — mas barato y convergente que regenerar.
  2. JUZGAR    — el juez FINO (VL-7B, solo en GPU) puntua el producto contra el
     goal y lista defectos accionables.
  3. PENSAR    — el PENSADOR (gpt-oss-20b, solo en GPU) recibe goal + nota +
     defectos + historia y DECIDE: ENTREGAR o SEGUIR con una lista concreta de
     cambios. Prioriza pulido: solo entrega si esta a la altura o si insistir ya
     no aporta.

AUTONOMIA DE FLOTA: entre fases el pulidor cambia el combo servido EL SOLO
(scripts/servir_flota.py, subprocess): pensar -> construir-ui -> juzgar ->
pensar... En 16GB no caben todos a la vez; la secuencia es el precio del pulido
y esta bien pagarlo (rapidez NO es el objetivo de este modo).

CORTES (el que llegue primero): decision ENTREGAR del pensador; nota >= gate;
ciclos_max; presupuesto de tiempo; o disyuntor (dos ciclos sin mejorar la nota
= insistir no aporta, regla 11 del repo).

SUENO: sin goal, el pensador PROPONE uno (pequeno, visual, construible).
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_RAIZ = Path(__file__).resolve().parent.parent.parent
_SERVIR_FLOTA = _RAIZ / "scripts" / "servir_flota.py"

GATE_FINAL_DEFECTO = 8.5     # el listSon de "pulido": exigente a proposito
CICLOS_MAX_DEFECTO = 4
TIEMPO_MAX_DEFECTO = 2400    # 40 min: pulir > rapidez, pero con techo


# ── flota: cambiar de combo (autonomo) ──────────────────────────────────────

def _combo(modo: str, verbose: bool = True) -> bool:
    """Cambia el combo servido. True si el combo quedo arriba."""
    if verbose:
        print(f"⚙️  flota -> {modo}")
    try:
        r = subprocess.run([sys.executable, str(_SERVIR_FLOTA), modo],
                           capture_output=True, text=True, timeout=360)
        ok = r.returncode == 0
        if not ok and verbose:
            print(f"   flota fallo: {(r.stdout or r.stderr)[-200:]}")
        return ok
    except Exception as e:
        logger.warning("pulidor: no pude cambiar la flota a %s (%s)", modo, e)
        return False


def _pensador(prompt: str, system: str = "", max_tokens: int = 900,
              temperature: float = 0.3) -> Optional[str]:
    """Habla con el cerebro servido en :8080 (en fase pensar: gpt-oss).

    PISO de tokens a 1024: gpt-oss razona en reasoning_content ANTES de emitir
    content; con presupuestos chicos el razonamiento se come todo y content
    llega VACIO con finish=length (medido 2026-07-25: sonar_goal con 100 tokens
    devolvia None y el sueno caia al fallback generico)."""
    try:
        cuerpo = json.dumps({
            "model": "local",
            "messages": ([{"role": "system", "content": system}] if system else [])
                        + [{"role": "user", "content": prompt}],
            "temperature": temperature, "max_tokens": max(1024, max_tokens),
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8080/v1/chat/completions", data=cuerpo,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            texto = json.loads(r.read())["choices"][0]["message"]["content"]
        if texto and "</think>" in texto:
            texto = texto.split("</think>", 1)[1]
        return (texto or "").strip() or None
    except Exception as e:
        logger.warning("pulidor: el pensador no respondio (%s)", e)
        return None


# ── piezas del ciclo ────────────────────────────────────────────────────────

def sonar_goal() -> Optional[str]:
    """El modelo PROPONE su sueno: un producto web pequeno, visual, construible."""
    raw = _pensador(
        "Propose ONE small, visual, self-contained web product you would love "
        "to build and polish (a game, a dashboard, an interactive page...). "
        "Answer with ONLY the product description in Spanish, 10-30 words.",
        temperature=0.9, max_tokens=100)
    if not raw:
        return None
    linea = raw.strip().strip('"').splitlines()[0].strip()
    return linea if 10 < len(linea) < 250 else None


def _decidir(goal: str, nota, defectos: List[str], ciclo: int,
             ciclos_max: int, historia: List[dict]) -> dict:
    """El pensador decide ENTREGAR o SEGUIR (+cambios). Formato tolerante."""
    notas_previas = [h.get("nota") for h in historia]
    prompt = (
        f'GOAL: "{goal}"\n'
        f"Ciclo {ciclo}/{ciclos_max}. Nota actual del juez visual: {nota}/10.\n"
        f"Notas de ciclos previos: {notas_previas}\n"
        f"Defectos observados por el juez:\n"
        + "\n".join(f"- {d}" for d in defectos[:8])
        + "\n\nEres el director de calidad. El objetivo es entregar el trabajo "
          "MAS PULIDO posible (la rapidez no importa). Decide:\n"
          "- SEGUIR si hay mejoras concretas y realistas que un desarrollador "
          "front puede aplicar al HTML.\n"
          "- ENTREGAR si el producto ya honra el goal o si las notas muestran "
          "que insistir no aporta.\n\n"
          "Responde EXACTAMENTE en este formato:\n"
          "DECISION: SEGUIR|ENTREGAR\n"
          "CAMBIOS:\n- <cambio concreto y accionable>\n- <otro>\n"
          "(si ENTREGAR, CAMBIOS es exactamente '- ninguno')")
    raw = _pensador(prompt, system="You are a meticulous quality director.",
                    temperature=0.2)
    decision = {"seguir": False, "cambios": []}
    if not raw:
        return decision          # sin pensador: entregar lo que hay
    seguir = bool(re.search(r"DECISION\s*:\s*SEGUIR", raw, re.I))
    cambios = [l.strip().lstrip("-*").strip() for l in raw.splitlines()
               if l.strip().startswith(("- ", "* "))]
    cambios = [c for c in cambios if c and c.lower() not in ("ninguno", "none")]
    decision["seguir"] = seguir and bool(cambios)
    decision["cambios"] = cambios[:6]
    return decision


def _juzgar(goal: str, html: str, dir_trabajo: Path) -> tuple:
    """Renderiza y pide veredicto al juez fino (VL-7B servido). Devuelve
    (nota|None, defectos, ruta_screenshot|None)."""
    from .arbitro_visual import arbitrar_desde_informe
    from .vista_navegador import revisar_en_navegador
    informe = revisar_en_navegador(html, dir_programa=dir_trabajo)
    arb = arbitrar_desde_informe(goal, informe, mockup=None, vision_texto=goal)
    defectos = list(informe.defectos or [])
    nota = None
    if arb:
        nota = arb.get("nota")
        defectos += [f"(visual) {d}" for d in arb.get("defectos", [])]
    shots = (informe.output_images or []) + (informe.input_images or [])
    return nota, defectos, (shots[-1] if shots else None)


@dataclass
class ResultadoPulido:
    goal: str
    html: Optional[str] = None
    nota_final: Optional[float] = None
    ciclos: int = 0
    motivo: str = ""
    historia: List[dict] = field(default_factory=list)
    directorio: Optional[str] = None

    def resumen(self) -> str:
        n = f"{self.nota_final:.1f}/10" if self.nota_final is not None else "s/nota"
        return (f"'{self.goal[:60]}' -> {self.ciclos} ciclo(s), nota {n}, "
                f"corte: {self.motivo}")


def pulir(goal: str = None, *, ciclos_max: int = CICLOS_MAX_DEFECTO,
          gate_final: float = None, tiempo_max_s: int = TIEMPO_MAX_DEFECTO,
          gestionar_flota: bool = True, verbose: bool = True) -> ResultadoPulido:
    """El loop thinking completo. NUNCA lanza: devuelve lo mejor que haya.

    goal: que construir y pulir. None -> el modelo SUENA uno.
    gestionar_flota: True (default) = el pulidor cambia los combos el solo.
                     False = asume cerebro:8080 + VLM:8081 ya servidos (mas
                     rapido para pruebas; juez = el VLM que este).
    """
    if gate_final is None:
        try:
            gate_final = float(os.environ.get("COGNIA_GATE_PULIDO",
                                              GATE_FINAL_DEFECTO))
        except (TypeError, ValueError):
            gate_final = GATE_FINAL_DEFECTO

    t0 = time.time()
    res = ResultadoPulido(goal=goal or "")

    try:
        # ── goal: del usuario o sonado ─────────────────────────────────────
        if not goal:
            if gestionar_flota:
                _combo("pensar", verbose)
            goal = sonar_goal() or "una pagina web visual e interactiva"
            res.goal = goal
            if verbose:
                print(f"💭 Sueno del modelo: {goal}")

        from .diseno_a_codigo import construir_para_mockup
        from .generator import GeneratedProgram, reparar_web

        slug = re.sub(r"[^a-z0-9]+", "_", goal.lower())[:40].strip("_") or "pulido"
        from .storage import DEFAULT_STORAGE_DIR
        dir_final = Path(DEFAULT_STORAGE_DIR) / "pulidos" / slug
        dir_final.mkdir(parents=True, exist_ok=True)
        res.directorio = str(dir_final)

        html, program = None, None
        mejor_nota = None

        for ciclo in range(1, ciclos_max + 1):
            res.ciclos = ciclo
            if time.time() - t0 > tiempo_max_s:
                res.motivo = "presupuesto de tiempo"
                break

            # ── 1. CONSTRUIR / REPARAR ─────────────────────────────────────
            if ciclo == 1:
                if gestionar_flota:
                    _combo("construir-ui", verbose)
                    os.environ["COGNIA_CONSTRUCTOR_URL"] = "http://127.0.0.1:8080"
                r1 = construir_para_mockup(goal, usar_mockup_imagen=False,
                                           max_rondas=2, verbose=verbose)
                program = r1.program
                html = r1.html_entregable()
                if not html:
                    res.motivo = f"no se pudo construir ({r1.motivo_corte})"
                    break
            else:
                if gestionar_flota:
                    _combo("construir-ui", verbose)
                    os.environ["COGNIA_CONSTRUCTOR_URL"] = "http://127.0.0.1:8080"
                arreglado = reparar_web(program, cambios)
                if arreglado is not None:
                    program = arreglado
                    html = program.code
                elif verbose:
                    print("   ↩️  la reparacion no devolvio algo valido; juzgo lo actual")

            (dir_final / f"ciclo_{ciclo}.html").write_text(html, encoding="utf-8")

            # ── 2. JUZGAR fino ─────────────────────────────────────────────
            if gestionar_flota:
                _combo("juzgar", verbose)
            nota, defectos, shot = _juzgar(goal, html, dir_final / f"c{ciclo}")
            res.historia.append({"ciclo": ciclo, "nota": nota,
                                 "n_defectos": len(defectos)})
            res.nota_final = nota if nota is not None else res.nota_final
            if verbose:
                n_txt = f"{nota:.1f}" if nota is not None else "s/nota"
                print(f"🏁 Ciclo {ciclo}: nota {n_txt}, {len(defectos)} defectos")

            if nota is not None and nota >= gate_final:
                res.motivo = f"gate de pulido alcanzado ({nota:.1f} >= {gate_final})"
                break

            # Disyuntor de pulido: dos ciclos seguidos sin mejorar = insistir
            # no aporta (regla 11). Se corta ANTES de gastar otro ciclo.
            if (mejor_nota is not None and nota is not None
                    and ciclo >= 2 and nota <= mejor_nota):
                res.motivo = "sin mejora entre ciclos (disyuntor de pulido)"
                break
            mejor_nota = nota if nota is not None else mejor_nota

            if ciclo == ciclos_max:
                res.motivo = "tope de ciclos"
                break

            # ── 3. PENSAR: ¿otro ciclo? ────────────────────────────────────
            if gestionar_flota:
                _combo("pensar", verbose)
            decision = _decidir(goal, nota, defectos, ciclo, ciclos_max,
                                res.historia)
            if not decision["seguir"]:
                res.motivo = "el pensador decidio ENTREGAR"
                break
            cambios = decision["cambios"] + defectos[:3]
            if verbose:
                print("🧠 El pensador pide otro ciclo:")
                for c in decision["cambios"]:
                    print(f"   - {c}")

        res.html = html
        if html:
            (dir_final / "index.html").write_text(html, encoding="utf-8")
            reporte = [f"# Pulido: {goal}", "",
                       f"- ciclos: {res.ciclos}",
                       f"- nota final: {res.nota_final}",
                       f"- corte: {res.motivo}", "", "## Historia"]
            reporte += [f"- ciclo {h['ciclo']}: nota={h['nota']} "
                        f"defectos={h['n_defectos']}" for h in res.historia]
            (dir_final / "reporte.md").write_text("\n".join(reporte),
                                                  encoding="utf-8")
        if not res.motivo:
            res.motivo = "fin"
        return res
    except Exception as e:
        logger.warning("pulidor: fallo inesperado (%s)", e)
        res.motivo = res.motivo or f"error: {e}"
        return res
    finally:
        if gestionar_flota:
            os.environ.pop("COGNIA_CONSTRUCTOR_URL", None)
