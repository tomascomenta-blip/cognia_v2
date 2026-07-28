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

import json
import logging
import os
import re
import tempfile
import time
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

# Tope de rondas de reparacion guiadas por el arbitro; el disyuntor puede
# cortar antes. HISTORIA COMPLETA (no repetirla): el 2026-07-26 un n=3
# enganoso lo bajo a 1 y el n=6 lo revirtio a 3 (aquellas series eran
# BLOQUES SECUENCIALES entre noches, con deriva del tamano del efecto). El
# 2026-07-27/28 los A/B INTERCALADOS con control concurrente (la unica
# lectura valida — [[gate-e2e-flaky]]) dieron lo contrario y consistente:
# el lazo RESTA frente a entregar la primera generacion juzgada, en el
# banco brutal (neto -3, 24 pares) y en el facil (neto -7, 36 pares;
# semaforo pierde 6/6 con reparacion). Mecanismo: el sello interno esta
# al nivel del azar en composicionales y las rondas degradan paginas que
# nacieron mejor. Adopcion pre-registrada (QUINTA enmienda de
# PREREG_SENAL_CONTRATO_20260727.md, "evidencia doble"): el default pasa
# a 1 hasta que el contrato interno demuestre senal; override por
# COGNIA_MAX_RONDAS para experimentos y para revertir sin release.
MAX_RONDAS_DEFECTO = 1


def _max_rondas_defecto() -> int:
    try:
        return int(os.environ.get("COGNIA_MAX_RONDAS", MAX_RONDAS_DEFECTO))
    except ValueError:
        return MAX_RONDAS_DEFECTO


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
    assets:      dict = field(default_factory=dict)  # sprites {name: data URI}
    # ── juez ejecutable (2026-07-25) ─────────────────────────────────────────
    # El sello es lo UNICO que habla de calidad funcional. "APROBADO"/"FALLIDO"
    # los pone el juez ejecutable con un contrato; sin contrato queda
    # "sin verificar" y NUNCA se convierte en numero: un 7.5 del arbitro visual
    # a un juego de memoria con las cartas destapadas es como se llego aqui.
    contrato:    Optional[dict] = None          # contrato ejecutable de la idea
    contrato_fallido: bool = False              # sin backend, o 2 intentos fallidos
    contrato_intentos: int = 0                  # intentos de generarlo (tope 2)
    veredicto:   Optional[dict] = None          # ultimo veredicto del juez (dict)
    sello:       str = "sin verificar"          # APROBADO | FALLIDO | sin verificar
    bon:         Optional[dict] = None          # best-of-N inicial {k, elegido, candidatos}

    @property
    def html(self) -> Optional[str]:
        """El FUENTE limpio (con data-asset, sin base64). Para entregar al
        usuario usar html_entregable(), que embebe los sprites."""
        return self.program.code if self.program else None

    def html_entregable(self) -> Optional[str]:
        """El HTML final con los sprites embebidos (si los hay). Es lo que se
        guarda/abre; el fuente limpio es lo que ve el LLM al reparar."""
        if not self.program:
            return None
        if self.assets:
            from .asset_bridge import inyectar_assets
            return inyectar_assets(self.program.code, self.assets)
        return self.program.code

    def resumen(self) -> str:
        n = f"{self.nota_visual:.1f}/10" if self.nota_visual is not None else "s/nota"
        return (f"'{self.idea[:50]}' -> {self.rondas} ronda(s), "
                f"sello: {self.sello}, fidelidad {n}, "
                f"{len(self.defectos)} defecto(s), corte: {self.motivo_corte}")


def _defectos_de(informe: InformeVisual, arb: Optional[dict]) -> List[str]:
    """Une los defectos de la sonda estructural con los del arbitro visual.
    reparar_web no distingue el origen: los trata todos como observaciones."""
    defectos = list(informe.defectos or [])
    if arb and arb.get("defectos"):
        defectos += [f"(visual) {d}" for d in arb["defectos"]]
    return defectos


def _ids_desaparecidos(html_fuente: str, dom_renderizado: str) -> List[str]:
    """Elementos con id que existen en el FUENTE pero ya no estan en el DOM tras
    correr el JS. Es el bug del juego arcade (2026-07-24): draw() hacia
    game.innerHTML='' cada frame y BORRABA la nave y el HUD — la pagina quedaba
    en puntitos moviles sobre negro. HTML valido, sonda contenta (algo se movia),
    y el elemento central del juego no existia en pantalla. Solo comparar fuente
    vs renderizado lo detecta. Logica pura -> testeable sin navegador."""
    if not html_fuente or not dom_renderizado:
        return []
    ids = re.findall(r'\bid\s*=\s*["\']([\w-]+)["\']', html_fuente)
    return [i for i in dict.fromkeys(ids)          # unicos, en orden
            if f'id="{i}"' not in dom_renderizado
            and f"id='{i}'" not in dom_renderizado]


def _defectos_estaticos(codigo: str, informe: InformeVisual) -> List[str]:
    """Defectos detectables SIN VLM que el arbitro y la sonda no ven."""
    defectos = []
    perdidos = _ids_desaparecidos(codigo, informe.dom_renderizado or "")
    if perdidos:
        defectos.append(
            "estos elementos existen en el fuente pero DESAPARECEN del DOM al "
            f"correr el JS: #{', #'.join(perdidos[:5])}. Causa tipica: un "
            "contenedor se vacia con innerHTML='' en cada frame y borra a sus "
            "hijos estaticos. ARREGLO: crea un contenedor SEPARADO solo para los "
            "elementos dinamicos y nunca vacies el que contiene los estaticos")
    if re.search(r"\balert\s*\(", codigo or ""):
        defectos.append(
            "usa alert() — bloquea la pagina (y el modo headless). Muestra el "
            "game over / los mensajes en un overlay <div> dentro de la pagina")
    return defectos


def _proponer_sprites(idea: str, brief: str,
                      llm: Optional[LlmFn] = None) -> List[dict]:
    """El CEREBRO le pide elementos al modelo de imagenes: propone que sprites
    necesita la escena (pedido del dueno). Devuelve specs [{name, prompt}] para
    asset_bridge.preparar_assets, o [] si no hay LLM o nada parsea. El formato
    pedido es una linea por sprite ('SPRITE nombre: prompt'), no JSON: el 14B lo
    respeta mucho mas."""
    from ..llm_local import generar
    pedido = (
        f'Product: "{(idea or "")[:300]}"\n'
        f'Look: "{(brief or "")[:300]}"\n\n'
        "List the 2-4 image sprites this scene needs (main characters/objects "
        "only, not backgrounds or text). One line each, EXACTLY:\n"
        "SPRITE <short_snake_case_name>: <image generation prompt in English, "
        "concrete and visual>\n")
    try:
        raw = None
        if llm is not None:
            try:
                raw = llm(pedido, "", 300, 0.4)
            except Exception:
                raw = None
        if not raw:
            raw = generar(pedido, temperature=0.4, max_tokens=300)
        if not raw:
            return []
        specs = []
        for linea in raw.splitlines():
            m = re.match(r"\s*SPRITE\s+([\w-]+)\s*:\s*(.+)", linea, re.I)
            if m and len(m.group(2).strip()) > 10:
                specs.append({"name": m.group(1).strip().lower(),
                              "prompt": m.group(2).strip()})
        return specs[:4]
    except Exception as e:
        logger.warning("diseno_a_codigo: _proponer_sprites fallo (%s)", e)
        return []


def _juez_del_lazo(idea: str, codigo_render: str, tmp_dir: Path,
                   ronda: "int | str",
                   res: "ResultadoDiseno", verbose: bool = False):
    """
    El juez EJECUTABLE dentro del lazo: genera el contrato de la idea (una sola
    vez, con el pensador + inventario del DOM) y juzga el producto de esta ronda
    en Chromium real. Devuelve el Veredicto, o None si no hay juez posible (sin
    backend LLM para el contrato, o sin Playwright) — en ese caso el lazo sigue
    con los cortes visuales y el sello queda "sin verificar".

    POR QUE (2026-07-25): el lazo entregaba por nota_visual de un VLM de 3B, y
    ese juez firmo 7.5/10 a un juego de memoria con las 16 cartas destapadas.
    Medido en b2_sistema_real: 2/6 tareas con el VLM decidiendo, con 4 tareas
    que ALGUN modelo del pool ya resolvia y el lazo perdia igual.
    """
    from . import juez_ejecutable

    html = tmp_dir / f"juez_r{ronda}.html"
    html.write_text(codigo_render, encoding="utf-8")

    if res.contrato is None:
        if res.contrato_fallido:
            return None
        try:
            from ..llm_local import disponible
            if not disponible():
                # Sin backend no hay a quien pedirle el contrato: no insistir.
                res.contrato_fallido = True
                if verbose:
                    print("   ⚖️  Sin backend para el contrato: el producto "
                          "saldra SIN VERIFICAR.")
                return None
            res.contrato_intentos += 1
            res.contrato = juez_ejecutable.generar_contrato(idea, html)
        except Exception as e:
            logger.warning("diseno_a_codigo: generar_contrato fallo (%s)", e)
        if res.contrato is None:
            # El pensador puede fallar por la cola de su distribucion de
            # razonamiento (medido 2026-07-26: ~1 de 2 a max_tokens justos).
            # Se paga UN reintento en la ronda siguiente; al segundo fallo se
            # deja de insistir.
            if res.contrato_intentos >= 2:
                res.contrato_fallido = True
            if verbose:
                print("   ⚖️  Sin contrato ejecutable"
                      + (" (reintento en la proxima ronda)"
                         if not res.contrato_fallido else "")
                      + ": el producto saldra SIN VERIFICAR "
                        "(el arbitro visual solo opina).")
            return None

    try:
        v = juez_ejecutable.juzgar_web(html, res.contrato)
    except Exception as e:
        logger.warning("diseno_a_codigo: juez_ejecutable fallo (%s)", e)
        return None
    if v.error:                     # p.ej. Playwright no instalado
        logger.warning("diseno_a_codigo: juez sin veredicto (%s)", v.error)
        return None
    return v


def _mejor_de_n(idea: str, primero, generar, k: int, tmp_dir: Path,
                res: "ResultadoDiseno", verbose: bool = False):
    """
    Best-of-N VERIFICADO sobre la generacion inicial (2026-07-26).

    La serie b2 de la config final (3,4,5,5,4 sobre 6) mostro que el cuello es
    la VARIANZA de la generacion inicial: las tareas que fallan ROTAN entre
    corridas. Antes de gastar rondas de reparacion, el juez ve hasta k
    candidatos SECUENCIALES: se queda con el PRIMERO que aprueba (el caso bueno
    no paga ningun candidato extra) o, si ninguno aprueba, con el de mas
    checks_ok. Sin contrato posible no hay seleccion y se devuelve el primero:
    elegir sin juez seria elegir por opinion (la leccion del VLM que firmo 7.5
    a un juego de memoria con las cartas destapadas).
    """
    candidatos: List[dict] = []
    mejor, mejor_ok, mejor_idx = primero, -1, 1
    p = primero
    for i in range(1, k + 1):
        if i > 1:
            try:
                p = generar()
            except Exception as e:
                logger.warning("diseno_a_codigo: candidato %d fallo (%s)", i, e)
                p = None
            if p is None or getattr(p, "lenguaje", "html") != "html":
                candidatos.append({"candidato": i, "sello": "sin HTML"})
                continue
        codigo = p.code
        if res.assets:
            from .asset_bridge import inyectar_assets
            codigo = inyectar_assets(p.code, res.assets)
        v = _juez_del_lazo(idea, codigo, tmp_dir, f"0c{i}", res, verbose=verbose)
        if v is None and i == 1 and res.contrato is None \
                and not res.contrato_fallido:
            # El intento 1 de contrato fallo por la cola del razonamiento del
            # pensador (~1 de 2, medido). El reintento se paga AQUI, sobre el
            # MISMO candidato: reintentarlo generando el candidato 2 gastaria
            # 60-90s de GPU solo para volver a pedir el contrato, y dejaria
            # al candidato 1 fuera de la seleccion sin haberlo juzgado
            # (hallazgo del revisor 2026-07-26).
            v = _juez_del_lazo(idea, codigo, tmp_dir, f"0c{i}b", res,
                               verbose=verbose)
        if v is None:
            candidatos.append({"candidato": i, "sello": "sin juez"})
            if res.contrato is None:
                # Sin contrato tras los reintentos (o backend caido): no va a
                # haber juez y elegir es imposible — generar mas candidatos
                # seria gastar GPU a ciegas. Se sigue con el primero.
                break
            continue
        ok = sum(1 for c in v.checks if c.ok)
        candidatos.append({"candidato": i,
                           "sello": "APROBADO" if v.aprobado else "FALLIDO",
                           "checks_ok": ok, "checks": len(v.checks)})
        if verbose:
            print(f"🏅 BoN candidato {i}/{k}: "
                  f"{'APROBADO' if v.aprobado else 'FALLIDO'} ({ok} checks OK)")
        if v.aprobado:
            # El APROBADO del BoN ES el veredicto de la entrega: el llamador
            # corta sin re-juzgar (re-juzgar el mismo HTML con un juez con
            # flakiness conocida seria doble jeopardy contra el candidato
            # bueno, y contradice el coste-0 del caso bueno del prereg).
            res.veredicto = v.a_dict()
            res.sello = "APROBADO"
            res.bon = {"k": k, "elegido": i, "candidatos": candidatos}
            return p
        if ok > mejor_ok:
            mejor, mejor_ok, mejor_idx = p, ok, i
    res.bon = {"k": k, "elegido": mejor_idx, "candidatos": candidatos}
    return mejor


# Telemetria de sellos en produccion (2026-07-26). Los tests la redirigen a
# tmp_path desde conftest, igual que el rastro de feromona.
RUTA_TELEMETRIA = (Path(__file__).resolve().parent / "generated_programs"
                   / "telemetria_sellos.jsonl")


def _registrar_sello(res: "ResultadoDiseno") -> None:
    """Contador de salud del juez en produccion: cada construccion deja una
    linea append-only con su sello. La metrica que importa es la fraccion que
    sale SIN VERIFICAR — el pensador falla la generacion de contrato ~1 de 2
    veces por la cola de su razonamiento, hay un reintento, y hasta hoy nadie
    media cuantos productos quedaban sin sello. Best-effort: nunca rompe el
    lazo."""
    try:
        RUTA_TELEMETRIA.parent.mkdir(parents=True, exist_ok=True)
        linea = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "idea": (res.idea or "")[:80],
                 "sello": res.sello,
                 # con_contrato separa el fallo del PENSADOR (no hubo
                 # contrato) del fallo de harness (contrato si, pero
                 # juzgar_web sin veredicto): sin esto la "salud del
                 # pensador" absorberia fallos de Playwright.
                 "con_contrato": res.contrato is not None,
                 "contrato_intentos": res.contrato_intentos,
                 "contrato_fallido": res.contrato_fallido,
                 "rondas": res.rondas,
                 "motivo_corte": res.motivo_corte,
                 "bon": res.bon}
        with open(RUTA_TELEMETRIA, "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("diseno_a_codigo: telemetria de sello no escrita (%s)", e)


def construir_para_mockup(idea: str, *, llm: Optional[LlmFn] = None,
                          max_rondas: Optional[int] = None,
                          gate_nota: Optional[float] = None,
                          usar_mockup_imagen: bool = True,
                          mockup_path: Optional[str] = None,
                          sprites=None,
                          assets: Optional[dict] = None,
                          requiere_grafico: bool = False,
                          candidatos_iniciales: int = 1,
                          max_rondas_progreso: Optional[int] = None,
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
        sprites:            elementos que el modelo de imagenes debe generar para
                            la escena. "auto" = el CEREBRO los propone desde la
                            vision (pedido del dueno); o una lista de specs
                            [{name, prompt}] (asset_bridge). None = sin sprites.
        assets:             sprites YA generados {name: data URI} (para cuando
                            SDXL no coexiste con cerebro+VLM en la GPU: se
                            generan aparte y se pasan aqui). Requiere `sprites`
                            con las specs para describirselos al modelo.
        requiere_grafico:   se pasa a la sonda (si la idea pide un grafico).
        candidatos_iniciales: best-of-N VERIFICADO sobre la generacion inicial
                            (PREREG_BON_RONDAS_20260726.md). >1 = el juez ve
                            hasta N candidatos secuenciales y se queda con el
                            primero que aprueba, ANTES de gastar rondas de
                            reparacion. 1 = comportamiento de siempre.
        max_rondas_progreso: si esta puesto (p.ej. 5), el tope de rondas se
                            extiende hasta ahi MIENTRAS checks_ok del juez
                            crezca entre rondas (progreso real, no espiral;
                            el disyuntor sigue rigiendo). None = tope fijo.

    Returns:
        ResultadoDiseno. NUNCA lanza hacia el llamador (best-effort como el resto
        del pipeline); ante fallo temprano devuelve el resultado con lo que haya.
    """
    gate = _gate() if gate_nota is None else gate_nota
    if max_rondas is None:
        max_rondas = _max_rondas_defecto()
    res = ResultadoDiseno(idea=idea)

    try:
        # ── 1. El cerebro IMAGINA el producto ──────────────────────────────
        vision = _mockup.imaginar_vision(idea, llm=llm)
        res.brief = vision.get("brief", "")
        res.prompt_imagen = vision.get("prompt_imagen", "")
        if verbose:
            print(f"🧠 Vision: {res.brief[:120]}")

        # ── 2. El modelo de imagenes DIBUJA el objetivo (opcional/GPU) ──────
        # mockup_path: usar un mockup YA hecho (util cuando SDXL no puede coexistir
        # con cerebro+VLM en la GPU: se genera aparte y se pasa aqui).
        if mockup_path:
            res.mockup = mockup_path
            if verbose:
                print(f"🎨 Mockup (provisto): {res.mockup}")
        elif usar_mockup_imagen:
            res.mockup = _mockup.generar_mockup(res.prompt_imagen or idea)
            if verbose:
                print(f"🎨 Mockup: {res.mockup or 'no disponible (uso brief de texto)'}")

        # ── 3. Construir la pagina inicial ─────────────────────────────────
        # El lazo diseno-a-codigo SIEMPRE construye un producto visual web. La
        # heuristica de generator (_es_idea_web) no basta: "dashboard de cripto"
        # sin la palabra "web" caia a un script Python de terminal (medido). Se
        # fuerza web prefijando una pista fuerte cuando la idea no la trae; el
        # enumerador de componentes ya sabe quitar ese prefijo.
        #
        # El BRIEF va EN la idea, a proposito: hasta el 2026-07-24 la vision solo
        # la veia el arbitro — el constructor generaba a ciegas y la fidelidad
        # arrancaba en 3-5. Ademas _componentes_de_idea trocea el brief en
        # REQUIRED components, o sea que el aspecto pedido se vuelve checklist.
        idea_build = idea if _es_idea_web(idea) else f"pagina web: {idea}"
        # COGNIA_IDEA_PELADA: construir con la idea TAL CUAL, sin pegarle el
        # brief estetico. Medido 2026-07-27 (b2_confound_envoltorio.py): el
        # mismo modelo, mismo server y mismo juez dan 75% con la idea directa
        # y 17% por el camino del sistema en el banco brutal — el envoltorio
        # destruye capacidad ya pagada en tareas composicionales, y el adorno
        # de la idea es el sospechoso principal (el brief compite con los
        # selectores OBLIGATORIOS del enunciado). El brief sigue existiendo
        # para el arbitro y los sprites.
        if res.brief and res.brief != idea.strip() \
                and not os.environ.get("COGNIA_IDEA_PELADA"):
            idea_build += f". TARGET LOOK, match it: {res.brief}"

        # ── 2b. El cerebro le PIDE elementos al modelo de imagenes ─────────
        # (pedido del dueno). Los sprites van como <img data-asset> en el
        # fuente; el base64 se inyecta SOLO al renderizar/entregar — nunca al
        # LLM (1.2MB de data URIs revientan el contexto de reparacion).
        specs = []
        if sprites == "auto":
            specs = _proponer_sprites(idea, res.brief, llm=llm)
            if verbose and specs:
                print("🖼️  Sprites pedidos por el cerebro: "
                      + ", ".join(s["name"] for s in specs))
        elif sprites:
            specs = list(sprites)

        if specs and assets is not None:
            res.assets = dict(assets)
        elif specs:
            try:
                from .asset_bridge import preparar_assets
                res.assets = preparar_assets(specs, recortar=True)
            except Exception as e:
                # Tipico: la GPU esta ocupada por cerebro+VLM. El lazo sigue
                # sin sprites en vez de morir (se puede regenerar despues).
                logger.warning("diseno_a_codigo: sin sprites (%s)", e)
                if verbose:
                    print(f"🖼️  Sprites no disponibles ({e}); sigo sin ellos.")
                specs = []

        # temperature 0.2 y no la 0.9 creativa: aqui hay una VISION que
        # cumplir (y a menudo selectores OBLIGATORIOS). Medido en b2
        # (2026-07-26, mismo modelo/server): 0.2 aprueba el contrato 6/7;
        # 0.9 aprueba 1/5 — a 0.9 el modelo "interpreta" la idea y pierde
        # los selectores que el enunciado exige.
        # La generacion inicial queda en un closure porque best-of-N la
        # vuelve a pedir tal cual para los candidatos 2..k.
        if specs and res.assets:
            from .asset_bridge import build_prompt_web_con_assets
            from .generator import _SISTEMA_WEB, _call_llm, _parse_response
            prompt_a = build_prompt_web_con_assets(
                idea_build, specs,
                extra_hint="Render a complete first frame immediately on load.")

            def _generar_inicial():
                raw = _call_llm(prompt_a, "html", temperature=0.2, llm=llm)
                return _parse_response(raw, idea, "html") if raw else None
        else:
            def _generar_inicial():
                return generate_program(forced_idea=idea_build, llm=llm,
                                        temperature=0.2)

        program = _generar_inicial()
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

            # ── 3b. Best-of-N verificado ANTES de gastar reparacion ────────
            if candidatos_iniciales > 1:
                program = _mejor_de_n(idea, program, _generar_inicial,
                                      candidatos_iniciales, tmp_dir, res,
                                      verbose=verbose)
                res.program = program
                if res.sello == "APROBADO":
                    # El juez ya aprobo un candidato: entrar al lazo seria
                    # re-juzgar el mismo HTML (doble jeopardy con un juez con
                    # flakiness conocida) y gastar sonda+arbitro para nada.
                    res.motivo_corte = ("aprobado por juez ejecutable "
                                        "(best-of-N)")
                    return res

            # max_rondas_progreso <= max_rondas no puede extender nada, pero
            # SI registraria verdes en el disyuntor (debilitando D1/D2/D6b a
            # cambio de nada): se normaliza a None.
            if max_rondas_progreso and max_rondas_progreso <= max_rondas:
                max_rondas_progreso = None

            tope_duro = max(max_rondas, max_rondas_progreso or 0)
            checks_ok_prev: Optional[int] = None
            for ronda in range(1, tope_duro + 1):
                res.rondas = ronda
                # Lo que se renderiza lleva los sprites embebidos; lo que ve el
                # LLM al reparar es el fuente limpio (program.code).
                codigo_render = program.code
                if res.assets:
                    from .asset_bridge import inyectar_assets
                    codigo_render = inyectar_assets(program.code, res.assets)
                # La sonda estructural (con screenshot: hay que pasar dir_programa)
                informe = revisar_en_navegador(
                    codigo_render, dir_programa=tmp_dir / f"r{ronda}",
                    requiere_grafico=requiere_grafico)
                # El OJO: compara el screenshot contra el mockup (o el brief).
                arb = arbitrar_desde_informe(
                    idea, informe, mockup=res.mockup, vision_texto=res.brief)
                if arb is not None:
                    res.nota_visual = arb.get("nota")

                defectos = _defectos_de(informe, arb) \
                    + _defectos_estaticos(program.code, informe)

                # ── El JUEZ EJECUTABLE decide la entrega (2026-07-25) ──────
                # Con contrato, el veredicto por ejecucion manda: aprueba el
                # juez o no se entrega como bueno. La nota del VLM queda como
                # telemetria. Sus contraejemplos (`visibles('.tile')=16,
                # esperaba 0`) van al canal de reparacion: es la unica senal
                # con efecto medido sobre modelos chicos congelados
                # (arXiv:2606.31511 — traza y auto-critica empatan con placebo).
                veredicto = _juez_del_lazo(idea, codigo_render, tmp_dir,
                                           ronda, res, verbose=verbose)
                hay_progreso = False
                checks_ok_ronda: Optional[int] = None
                if veredicto is not None:
                    res.veredicto = veredicto.a_dict()
                    res.sello = "APROBADO" if veredicto.aprobado else "FALLIDO"
                    # Progreso real = checks_ok CRECIO respecto a la ronda
                    # anterior. Es la senal que autoriza extender el tope
                    # (max_rondas_progreso); una espiral no la produce.
                    checks_ok_ronda = sum(1 for c in veredicto.checks if c.ok)
                    hay_progreso = (checks_ok_prev is not None
                                    and checks_ok_ronda > checks_ok_prev)
                    checks_ok_prev = checks_ok_ronda
                    if not veredicto.aprobado:
                        contraejemplos = [
                            f"(juez) {c.nombre}: {c.detalle}"
                            for c in veredicto.checks if not c.ok]
                        defectos = contraejemplos + defectos

                res.defectos = defectos
                nota = res.nota_visual
                res.historia.append({
                    "ronda": ronda, "nota": nota,
                    "n_defectos": len(defectos),
                    "arbitro": bool(arb),
                    "sello": res.sello,
                    "checks_ok": checks_ok_ronda,
                })
                if verbose:
                    n_txt = f"{nota:.1f}" if nota is not None else "s/nota"
                    print(f"── Ronda {ronda}: sello {res.sello}, "
                          f"fidelidad {n_txt}, {len(defectos)} defecto(s)")

                if veredicto is not None and veredicto.aprobado:
                    res.motivo_corte = "aprobado por juez ejecutable"
                    break

                # Cortes de OPINION (sonda/VLM): solo mandan cuando no hubo
                # juez. Con un FALLIDO del juez en la mano, una nota bonita no
                # entrega — seria devolverle la decision al VLM.
                if veredicto is None:
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
                # Con max_rondas_progreso activo, una ronda cuyo checks_ok
                # CRECIO se registra como verde: progreso corta la racha
                # esteril (la regla del propio disyuntor) — si no, su D1
                # (3 intentos) cortaria en la ronda 4 justo a la reparacion
                # que esta rematando. Sin el flag, comportamiento identico
                # al de siempre.
                disyuntor.registrar(
                    huella_de_texto("|".join(sorted(defectos))),
                    ok=bool(max_rondas_progreso) and hay_progreso,
                    hubo_cambio=(ronda > 1))
                motivo = disyuntor.motivo_corte()
                if motivo:
                    res.motivo_corte = f"disyuntor {motivo}"
                    if verbose:
                        print(f"   ⛔ Disyuntor ({motivo}): dejo de parchear a ciegas.")
                    break

                if ronda >= max_rondas:
                    # Con checks_ok creciendo la reparacion esta rematando, no
                    # espiralando: se le deja seguir hasta max_rondas_progreso.
                    # Sin progreso (o sin la opcion), el tope fijo manda.
                    if not (max_rondas_progreso and hay_progreso
                            and ronda < tope_duro):
                        res.motivo_corte = "tope de rondas"
                        break
                    if verbose:
                        print(f"   ▶ checks_ok creciendo "
                              f"({checks_ok_ronda} OK): extiendo a ronda "
                              f"{ronda + 1} (tope {tope_duro})")

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
    finally:
        # El contador de salud corre en TODAS las salidas: la tasa de
        # "sin verificar" solo es real si tambien cuenta los fallos tempranos.
        _registrar_sello(res)
