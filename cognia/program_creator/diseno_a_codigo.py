# -*- coding: utf-8 -*-
"""
diseno_a_codigo.py — el lazo DISENO-A-CODIGO con arbitro visual.

POR QUE EXISTE (pedido del dueno): el cerebro se imagina el producto final como
una IMAGEN, el modelo de imagenes la dibuja (mockup), y luego el cerebro construye
la pagina TRABAJANDO PARA QUE SE PAREZCA a esa imagen. Un arbitro (arbitro_visual)
mira el resultado renderizado y dice si de verdad quedo como la vision; sus
observaciones vuelven al modelo como defectos a corregir, ronda tras ronda.

Reusa TODO lo que ya existe y funciona, sin tocar el lazo hobby (run_program_hobby):
  - mockup.imaginar_vision   — el cerebro imagina (brief + prompt de imagen)
  - mockup.generar_mockup    — el modelo de imagenes dibuja el objetivo (GPU, opcional)
  - generator.generate_program / reparar_web — construye y repara la pagina
  - vista_navegador.revisar_en_navegador     — renderiza y saca el screenshot
  - arbitro_visual.arbitrar_visual           — MIRA screenshot vs mockup -> defectos
  - disciplina.Disyuntor                     — corta el bucle de parches esteriles

El arbitro visual se SUMA al canal de reparacion que ya consume defectos de la
sonda estructural: reparar_web no distingue de donde viene cada defecto. Si no hay
VLM vivo, el lazo degrada con gracia y sigue solo con la sonda estructural + el
brief de texto (nunca se rompe por falta del arbitro).

Condiciones de corte (cualquiera): sin defectos, nota del arbitro >= gate, tope de
rondas, o el disyuntor detecta que insistir no avanza (regla 11 del repo).
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from ..disciplina import Disyuntor, huella_de_texto
from . import mockup as _mockup
from .arbitro_visual import arbitrar_desde_informe
from .generator import (GeneratedProgram, _es_idea_web, generate_program,
                        reparar_web)
from .vista_navegador import InformeVisual, revisar_en_navegador

logger = logging.getLogger(__name__)

LlmFn = Callable[[str, str, int, float], Optional[str]]

# Nota de fidelidad a partir de la cual se acepta la pagina sin mas rondas. El
# arbitro puntua 0-10 el parecido al mockup; 7.0 es "fiel en lo estructural, con
# desviaciones menores toleradas" (el mockup es intencion, no plano). Override por
# COGNIA_GATE_VISUAL.
GATE_VISUAL_DEFECTO = 7.0

# Tope de rondas de reparacion guiadas por el arbitro. Mismo espiritu que el lazo
# web hobby (3, umbral de Aider); el disyuntor puede cortar antes.
MAX_RONDAS_DEFECTO = 3


def _gate() -> float:
    try:
        return float(os.environ.get("COGNIA_GATE_VISUAL", GATE_VISUAL_DEFECTO))
    except (TypeError, ValueError):
        return GATE_VISUAL_DEFECTO


@dataclass
class ResultadoDiseno:
    """Lo que devuelve el lazo diseno-a-codigo."""
    idea:        str
    program:     Optional[GeneratedProgram] = None
    brief:       str = ""
    prompt_imagen: str = ""
    mockup:      Optional[str] = None          # ruta al PNG objetivo (o None)
    nota_visual: Optional[float] = None         # ultima nota del arbitro (o None)
    rondas:      int = 0
    defectos:    List[str] = field(default_factory=list)  # los que quedaron
    motivo_corte: str = ""                       # por que paro el lazo
    historia:    List[dict] = field(default_factory=list)  # por ronda

    @property
    def html(self) -> Optional[str]:
        return self.program.code if self.program else None

    def resumen(self) -> str:
        n = f"{self.nota_visual:.1f}/10" if self.nota_visual is not None else "s/nota"
        return (f"'{self.idea[:50]}' -> {self.rondas} ronda(s), fidelidad {n}, "
                f"{len(self.defectos)} defecto(s), corte: {self.motivo_corte}")


def _defectos_de(informe: InformeVisual, arb: Optional[dict]) -> List[str]:
    """Une los defectos de la sonda estructural con los del arbitro visual.
    reparar_web no distingue el origen: los trata todos como observaciones."""
    defectos = list(informe.defectos or [])
    if arb and arb.get("defectos"):
        defectos += [f"(visual) {d}" for d in arb["defectos"]]
    return defectos


def construir_para_mockup(idea: str, *, llm: Optional[LlmFn] = None,
                          max_rondas: int = MAX_RONDAS_DEFECTO,
                          gate_nota: Optional[float] = None,
                          usar_mockup_imagen: bool = True,
                          requiere_grafico: bool = False,
                          verbose: bool = True) -> ResultadoDiseno:
    """
    Construye una pagina para una idea y la itera hasta que se PAREZCA a la
    vision que el cerebro imagino.

    Args:
        idea:               que producto construir ("dashboard de inversiones", ...).
        llm:                backend real inyectado (LlmFn). Sin el se usa el
                            residente (llm_local) donde cada pieza lo resuelve.
        max_rondas:         tope de rondas de reparacion guiadas por el arbitro.
        gate_nota:          nota de fidelidad para aceptar sin mas rondas
                            (default COGNIA_GATE_VISUAL o 7.0).
        usar_mockup_imagen: si True, el modelo de imagenes dibuja el mockup (GPU).
                            Si no hay backend, cae a comparar contra el brief de texto.
        requiere_grafico:   se pasa a la sonda (si la idea pide un grafico).

    Returns:
        ResultadoDiseno. NUNCA lanza hacia el llamador (best-effort como el resto
        del pipeline); ante fallo temprano devuelve el resultado con lo que haya.
    """
    gate = _gate() if gate_nota is None else gate_nota
    res = ResultadoDiseno(idea=idea)

    try:
        # ── 1. El cerebro IMAGINA el producto ──────────────────────────────
        vision = _mockup.imaginar_vision(idea, llm=llm)
        res.brief = vision.get("brief", "")
        res.prompt_imagen = vision.get("prompt_imagen", "")
        if verbose:
            print(f"🧠 Vision: {res.brief[:120]}")

        # ── 2. El modelo de imagenes DIBUJA el objetivo (opcional/GPU) ──────
        if usar_mockup_imagen:
            res.mockup = _mockup.generar_mockup(res.prompt_imagen or idea)
            if verbose:
                print(f"🎨 Mockup: {res.mockup or 'no disponible (uso brief de texto)'}")

        # ── 3. Construir la pagina inicial ─────────────────────────────────
        # El lazo diseno-a-codigo SIEMPRE construye un producto visual web. La
        # heuristica de generator (_es_idea_web) no basta: "dashboard de cripto"
        # sin la palabra "web" caia a un script Python de terminal (medido). Se
        # fuerza web prefijando una pista fuerte cuando la idea no la trae; el
        # enumerador de componentes ya sabe quitar ese prefijo.
        idea_build = idea if _es_idea_web(idea) else f"pagina web: {idea}"
        program = generate_program(forced_idea=idea_build, llm=llm)
        if program is None:
            res.motivo_corte = "no se pudo generar la pagina inicial"
            return res
        if getattr(program, "lenguaje", "python") != "html":
            res.motivo_corte = ("la idea no se resolvio como web "
                                f"(lenguaje={getattr(program, 'lenguaje', '?')})")
            res.program = program
            return res
        res.program = program

        # ── 4. Lazo: render -> arbitro -> reparar -> repetir ───────────────
        disyuntor = Disyuntor(f"mockup: {idea[:40]}")
        with tempfile.TemporaryDirectory(prefix="cognia_d2c_") as tmp:
            tmp_dir = Path(tmp)
            for ronda in range(1, max_rondas + 1):
                res.rondas = ronda
                # La sonda estructural (con screenshot: hay que pasar dir_programa)
                informe = revisar_en_navegador(
                    program.code, dir_programa=tmp_dir / f"r{ronda}",
                    requiere_grafico=requiere_grafico)
                # El OJO: compara el screenshot contra el mockup (o el brief).
                arb = arbitrar_desde_informe(
                    idea, informe, mockup=res.mockup, vision_texto=res.brief)
                if arb is not None:
                    res.nota_visual = arb.get("nota")

                defectos = _defectos_de(informe, arb)
                res.defectos = defectos
                nota = res.nota_visual
                res.historia.append({
                    "ronda": ronda, "nota": nota,
                    "n_defectos": len(defectos),
                    "arbitro": bool(arb),
                })
                if verbose:
                    n_txt = f"{nota:.1f}" if nota is not None else "s/nota"
                    print(f"── Ronda {ronda}: fidelidad {n_txt}, "
                          f"{len(defectos)} defecto(s)")

                # Corte por calidad: sin defectos, o el arbitro ya la aprueba.
                if not defectos:
                    res.motivo_corte = "sin defectos"
                    break
                if nota is not None and nota >= gate:
                    res.motivo_corte = f"fidelidad {nota:.1f} >= gate {gate:.1f}"
                    break

                # Disyuntor: el sintoma es el conjunto de defectos. La primera
                # ronda es el punto de partida (el modelo aun no reparo nada):
                # hubo_cambio=False para no gastar una huella de D6 antes de tiempo
                # (mismo criterio que el lazo hobby, program_creator.py:323).
                disyuntor.registrar(
                    huella_de_texto("|".join(sorted(defectos))),
                    ok=False, hubo_cambio=(ronda > 1))
                motivo = disyuntor.motivo_corte()
                if motivo:
                    res.motivo_corte = f"disyuntor {motivo}"
                    if verbose:
                        print(f"   ⛔ Disyuntor ({motivo}): dejo de parchear a ciegas.")
                    break

                if ronda == max_rondas:
                    res.motivo_corte = "tope de rondas"
                    break

                # Reparar con TODOS los defectos (estructurales + visuales).
                arreglado = reparar_web(program, defectos, llm=llm)
                if arreglado is None:
                    res.motivo_corte = "el modelo no devolvio una correccion valida"
                    if verbose:
                        print("   ↩️  Correccion no valida; paro.")
                    break
                program = arreglado
                res.program = program

        return res
    except Exception as e:
        logger.warning("diseno_a_codigo: fallo inesperado (%s)", e)
        res.motivo_corte = f"error: {e}"
        return res
