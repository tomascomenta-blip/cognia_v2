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


def _grito(via: str, detalle: str) -> None:
    """Deja constancia RUIDOSA de un degradado (stderr + backend_audit.jsonl).

    POR QUE: hasta el 2026-07-25 el lazo se cortaba solo cuando el pensador no
    respondia y el reporte decia "el pensador decidio ENTREGAR" — una decision
    que nadie tomo. Un degradado que no se ve se repite para siempre. El import
    va DENTRO: la instrumentacion nunca puede tumbar el lazo."""
    try:
        from .. import backend_activo
        backend_activo.sin_backend(via, detalle)
    except Exception:
        pass


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
        _grito("pulidor.pensador",
               f"el cerebro de :8080 no respondio ({e}); el ciclo sigue SIN pensador")
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
        # Sin pensador se entrega lo que hay, PERO eso no es una decision de
        # calidad: es un backend caido. La marca viaja en el dict para que el
        # motivo del corte no mienta ("el pensador decidio ENTREGAR").
        decision["sin_pensador"] = True
        _grito("pulidor.decidir",
               f"el pensador no respondio en el ciclo {ciclo}: se entrega lo "
               f"que hay SIN que nadie lo haya decidido")
        return decision
    seguir = bool(re.search(r"DECISION\s*:\s*SEGUIR", raw, re.I))
    cambios = [l.strip().lstrip("-*").strip() for l in raw.splitlines()
               if l.strip().startswith(("- ", "* "))]
    cambios = [c for c in cambios if c and c.lower() not in ("ninguno", "none")]
    decision["seguir"] = seguir and bool(cambios)
    decision["cambios"] = cambios[:6]
    return decision


def _juzgar(goal: str, html: str, dir_trabajo: Path,
            mockup: Optional[str] = None) -> tuple:
    """Renderiza y pide veredicto al juez fino (VL-7B servido). Devuelve
    (nota|None, defectos, ruta_screenshot|None).

    requiere_grafico viene del GOAL (la sonda no lo conoce): sin esto, una
    pagina con los paneles de grafico VACIOS pasaba sin defecto estructural y
    el juez de texto le daba 8.5 (medido en el sueno del 2026-07-25).
    mockup: si hay imagen objetivo, el arbitro compara CONTRA ELLA (mucho mas
    exigente que juzgar contra la intencion en texto — medido en el juego)."""
    from .arbitro_visual import arbitrar_desde_informe
    from .program_creator import _idea_pide_grafico
    from .vista_navegador import revisar_en_navegador
    informe = revisar_en_navegador(html, dir_programa=dir_trabajo,
                                   requiere_grafico=_idea_pide_grafico(goal))
    arb = arbitrar_desde_informe(goal, informe, mockup=mockup,
                                 vision_texto=goal)
    defectos = list(informe.defectos or [])
    nota = None
    if arb and not arb.get("sin_vlm"):
        nota = arb.get("nota")
        defectos += [f"(visual) {d}" for d in arb.get("defectos", [])]
    else:
        # NADIE MIRO EL PIXEL. Sin esto, el ciclo seguia con solo la sonda
        # estructural y el reporte no distinguia "juzgado 6.0" de "no juzgado".
        _grito("pulidor.arbitro_visual",
               "el arbitro visual no emitio veredicto (VLM caido o ilegible): "
               "el ciclo sigue SOLO con la sonda estructural")
    shots = (informe.output_images or []) + (informe.input_images or [])
    return nota, defectos, (shots[-1] if shots else None)


def _gpu_python() -> Optional[str]:
    """El python CON torch/CUDA (venv312gpu) para generar el mockup en
    subproceso: el pulidor corre en venv312 (sin torch) y SDXL necesita la GPU
    libre — la flota se apaga antes. Override: COGNIA_GPU_PYTHON."""
    env = os.environ.get("COGNIA_GPU_PYTHON", "").strip()
    if env and Path(env).is_file():
        return env
    cand = _RAIZ / "venv312gpu" / "Scripts" / "python.exe"
    return str(cand) if cand.is_file() else None


def _generar_mockup_subproceso(prompt: str, salida: Path,
                               verbose: bool = True) -> Optional[str]:
    """Mockup con SDXL en el python GPU. None si no hay GPU-python o falla
    (el pulidor sigue en modo texto — nunca se rompe por esto)."""
    py = _gpu_python()
    if py is None:
        return None
    codigo = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "from cognia.program_creator.mockup import generar_mockup\n"
        "r = generar_mockup(%r, salida=r'%s', ancho=1024, alto=768, pasos=24)\n"
        "print('MOCKUP_OK' if r else 'MOCKUP_FAIL')\n"
    ) % (str(_RAIZ), prompt, str(salida))
    try:
        r = subprocess.run([py, "-c", codigo], capture_output=True, text=True,
                           timeout=600)
        if "MOCKUP_OK" in (r.stdout or "") and salida.exists():
            return str(salida)
        if verbose:
            print(f"   mockup no disponible ({(r.stdout or r.stderr)[-120:]})")
        return None
    except Exception as e:
        logger.warning("pulidor: mockup en subproceso fallo (%s)", e)
        return None


@dataclass
class ResultadoPulido:
    goal: str
    html: Optional[str] = None
    nota_final: Optional[float] = None
    ciclos: int = 0
    motivo: str = ""
    historia: List[dict] = field(default_factory=list)
    directorio: Optional[str] = None
    # Todo lo que el lazo hizo A CIEGAS (goal canned, sin pensador, sin arbitro,
    # sin mockup). Va al resumen y al reporte.md: una corrida degradada tiene que
    # poder distinguirse de una sana DESPUES, no solo en el stderr del momento.
    degradaciones: List[str] = field(default_factory=list)
    # El veredicto MEDIDO de la autoprueba sobre el index.html entregado. Va en
    # su propio campo y NO en degradaciones: un veredicto no es "algo hecho a
    # ciegas", y meterlo ahi hacia que toda corrida sana pareciera degradada.
    autoprueba: str = ""

    def resumen(self) -> str:
        n = f"{self.nota_final:.1f}/10" if self.nota_final is not None else "s/nota"
        aviso = (f" | DEGRADADO ({len(self.degradaciones)}): "
                 f"{self.degradaciones[0]}") if self.degradaciones else ""
        prueba = f" | autoprueba: {self.autoprueba}" if self.autoprueba else ""
        return (f"'{self.goal[:60]}' -> {self.ciclos} ciclo(s), nota {n}, "
                f"corte: {self.motivo}{aviso}{prueba}")


def pulir(goal: str = None, *, ciclos_max: int = CICLOS_MAX_DEFECTO,
          gate_final: float = None, tiempo_max_s: int = TIEMPO_MAX_DEFECTO,
          gestionar_flota: bool = True, usar_mockup: bool = True,
          verbose: bool = True) -> ResultadoPulido:
    """El loop thinking completo. NUNCA lanza: devuelve lo mejor que haya.

    goal: que construir y pulir. None -> el modelo SUENA uno.
    gestionar_flota: True (default) = el pulidor cambia los combos el solo.
                     False = asume cerebro:8080 + VLM:8081 ya servidos (mas
                     rapido para pruebas; juez = el VLM que este).
    usar_mockup: True (default) = fase de IMAGINACION: la flota se apaga, SDXL
                 (python GPU, subproceso) dibuja el mockup objetivo, y el juez
                 compara CONTRA LA IMAGEN — mucho mas exigente que el goal en
                 texto (medido: 8.5 a paneles vacios en modo texto). Sin GPU
                 python o si falla, degrada al modo texto sin romper.
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
            sonado = sonar_goal()
            goal = sonado or "una pagina web visual e interactiva"
            res.goal = goal
            if not sonado:
                # El goal CANNED se veia igual que un sueno de verdad en la
                # salida y en el reporte: parecia que el modelo habia elegido
                # construir "una pagina web visual e interactiva".
                res.degradaciones.append(
                    "GOAL CANNED: el pensador no propuso ningun sueno; se uso "
                    "el goal de relleno 'una pagina web visual e interactiva'")
                _grito("pulidor.sonar_goal",
                       "sin sueno del pensador: goal CANNED de relleno")
                if verbose:
                    print("⚠️  Sin sueno del pensador: goal CANNED de relleno")
            elif verbose:
                print(f"💭 Sueno del modelo: {goal}")

        from .diseno_a_codigo import construir_para_mockup
        from .generator import GeneratedProgram, reparar_web

        slug = re.sub(r"[^a-z0-9]+", "_", goal.lower())[:40].strip("_") or "pulido"
        from .storage import DEFAULT_STORAGE_DIR
        dir_final = Path(DEFAULT_STORAGE_DIR) / "pulidos" / slug
        dir_final.mkdir(parents=True, exist_ok=True)
        res.directorio = str(dir_final)

        # ── fase de IMAGINACION (opcional): el mockup objetivo ────────────
        # SDXL necesita la GPU sola: la flota se apaga, se dibuja, y el combo
        # siguiente la vuelve a levantar. El precio (~1 min) compra un juez
        # con dientes durante TODOS los ciclos.
        mockup_ruta = None
        if usar_mockup and gestionar_flota:
            _combo("parar", verbose)
            if verbose:
                print("🎨 Imaginando el mockup objetivo (SDXL, GPU sola)...")
            mockup_ruta = _generar_mockup_subproceso(
                goal, dir_final / "mockup.png", verbose)
            if not mockup_ruta:
                # Sin imagen objetivo el juez es MUCHO mas laxo (medido: 8.5 a
                # paneles vacios juzgando contra el goal en texto).
                res.degradaciones.append(
                    "SIN MOCKUP objetivo: el arbitro juzga contra el goal en "
                    "texto (mas laxo que contra la imagen)")
                if verbose:
                    print("   sin mockup: el juez usara el goal en texto")

        html, program = None, None
        mejor_nota = None
        mejor_html = None            # checkpoint: SIEMPRE se entrega el mejor
        mejor_ciclo = None           # ciclo del checkpoint (para el reporte)

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
                # Hasta 2 intentos: UIGEN a veces trunca su primer intento
                # (piensa largo); un reintento con otra semilla suele salir.
                r1 = None
                for _intento in range(2):
                    r1 = construir_para_mockup(goal, usar_mockup_imagen=False,
                                               mockup_path=mockup_ruta,
                                               max_rondas=2, verbose=verbose)
                    if r1.html_entregable():
                        break
                    if verbose:
                        print("   ↩️  construccion fallida; reintento")
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
                if arreglado is not None and arreglado.code != program.code:
                    program = arreglado
                    html = program.code
                else:
                    # Nada cambio: re-juzgar solo muestrearia el RUIDO del juez
                    # (medido 2026-07-25: una reparacion truncada dejo el html
                    # identico y la nota "subio" 7.5->8.5 cruzando el gate sin
                    # mejora real). Sin cambio no hay veredicto nuevo: se corta.
                    if verbose:
                        print("   ↩️  la reparacion no cambio el html; "
                              "insistir seria juzgar el ruido. Corto aqui.")
                    res.motivo = "la reparacion no avanzo (se entrega lo juzgado)"
                    break

            (dir_final / f"ciclo_{ciclo}.html").write_text(html, encoding="utf-8")

            # ── 2. JUZGAR fino ─────────────────────────────────────────────
            if gestionar_flota:
                _combo("juzgar", verbose)
            nota, defectos, shot = _juzgar(goal, html, dir_final / f"c{ciclo}",
                                           mockup=mockup_ruta)
            res.historia.append({"ciclo": ciclo, "nota": nota,
                                 "n_defectos": len(defectos)})
            res.nota_final = nota if nota is not None else res.nota_final
            if nota is None:
                # Ciclo SIN VEREDICTO: no es un 0 ni un aprobado, es que nadie
                # miro. El disyuntor y el gate lo saltan; el reporte lo dice.
                res.degradaciones.append(
                    f"ciclo {ciclo}: SIN NOTA, el arbitro visual no juzgo "
                    f"(el gate y el disyuntor no pudieron aplicarse)")
            # Checkpoint del MEJOR ciclo: un ciclo puede EMPEORAR (medido
            # 2026-07-25: 7.0 -> 7.5 -> 6.0) y sin esto se entregaba el ultimo.
            if nota is not None and (mejor_nota is None or nota > mejor_nota):
                mejor_html, mejor_ciclo = html, ciclo
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
                if decision.get("sin_pensador"):
                    # El corte es identico, el motivo NO: sin esto el reporte
                    # atribuia al pensador una decision que nunca tomo.
                    res.motivo = ("SIN PENSADOR: se entrega lo que hay (el "
                                  "cerebro no respondio; nadie lo decidio)")
                    res.degradaciones.append(
                        f"ciclo {ciclo}: el pensador no respondio; el lazo se "
                        f"corto sin decision de calidad")
                    if verbose:
                        print("⚠️  El pensador NO respondio: se corta el lazo "
                              "sin decision (no es un ENTREGAR)")
                else:
                    res.motivo = "el pensador decidio ENTREGAR"
                break
            cambios = decision["cambios"] + defectos[:3]
            if verbose:
                print("🧠 El pensador pide otro ciclo:")
                for c in decision["cambios"]:
                    print(f"   - {c}")

        # Se entrega el MEJOR ciclo, no el ultimo (un ciclo puede empeorar).
        if mejor_html is not None:
            res.html = mejor_html
            res.nota_final = mejor_nota if mejor_nota is not None else res.nota_final
            # mejor_nota se actualiza tras el disyuntor; el checkpoint manda:
            notas_hist = [h["nota"] for h in res.historia
                          if h.get("nota") is not None]
            if notas_hist:
                res.nota_final = max(notas_hist)
            if mejor_ciclo is not None and mejor_ciclo != res.ciclos:
                res.motivo += f" (entregado el ciclo {mejor_ciclo}, el mejor)"
            html = mejor_html
        else:
            res.html = html
        if html:
            (dir_final / "index.html").write_text(html, encoding="utf-8")
            reporte = [f"# Pulido: {goal}", "",
                       f"- ciclos: {res.ciclos}",
                       f"- nota final: {res.nota_final}",
                       f"- corte: {res.motivo}", "", "## Historia"]
            reporte += [f"- ciclo {h['ciclo']}: nota={h['nota']} "
                        f"defectos={h['n_defectos']}" for h in res.historia]
            # Lo que se hizo A CIEGAS. Va SIEMPRE, tambien cuando no hubo nada:
            # "sin degradaciones" es informacion, la ausencia de seccion no.
            reporte += ["", "## Degradaciones (lo que se hizo a ciegas)"]
            reporte += ([f"- {d}" for d in res.degradaciones]
                        or ["- ninguna: goal real, pensador, arbitro y mockup "
                            "respondieron"])
            (dir_final / "reporte.md").write_text("\n".join(reporte),
                                                  encoding="utf-8")
            # SELLO IGUAL QUE /crear (2026-08-29): hasta hoy /pulir no llamaba a
            # la verificacion nunca y sus 6 productos ademas eran INVISIBLES para
            # /autoprueba (viven anidados en pulidos/<slug>/). Se sella aqui, con
            # el mismo criterio medido, y el motivo del veredicto entra en el
            # reporte.md para que quede junto a la historia del pulido.
            try:
                from .program_creator import _verificar_y_reparar, texto_veredicto
                _ver = _verificar_y_reparar(dir_final, None, verbose=False, reparar=False)
                res.autoprueba = texto_veredicto(_ver)
                with open(dir_final / "reporte.md", "a", encoding="utf-8") as fh:
                    fh.write(f"\n\n## Autoprueba (medida, no opinada)\n"
                             f"- {texto_veredicto(_ver)}\n")
                if verbose:
                    print(f"🔬 Autoprueba: {texto_veredicto(_ver)}")
            except Exception as exc:
                # Que la autoprueba NO se pueda correr si es una degradacion:
                # se entrega una pagina sin haberla medido.
                res.autoprueba = f"NO se pudo medir ({type(exc).__name__})"
                res.degradaciones.append(
                    f"SIN AUTOPRUEBA: no se pudo sellar el pulido "
                    f"({type(exc).__name__}: {exc})")
                _grito("pulidor.autoprueba",
                       f"no se pudo sellar el pulido: {type(exc).__name__}: {exc}")
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
