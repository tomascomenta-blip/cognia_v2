# -*- coding: utf-8 -*-
"""
arbitro_visual.py — el arbitro que MIRA la pagina, no la lee.

POR QUE EXISTE (pedido del dueno): critico.py juzga sobre HECHOS medidos por la
sonda (colores computados, ejes de un svg, animacion) — es texto, no pixeles.
Nunca compara lo que se ve contra lo que se QUERIA que se viera. El dueno quiere
que el cerebro imagine el producto final como una IMAGEN y que un arbitro evalue
si la pagina construida se PARECE a esa imagen. Eso exige un ojo de verdad.

COMO FUNCIONA: se le dan al VLM dos imagenes — la VISION (mockup objetivo) y el
SCREENSHOT real de la pagina renderizada por vista_navegador — y se le pide un
veredicto de FIDELIDAD. El formato de salida es identico al de critico.criticar_web
({"nota","veredicto","defectos"}) para que enchufe SIN cambios en el lazo de
reparacion: generator.reparar_web ya sabe consumir esa lista de defectos.

QUE SE JUZGA (y que NO): jerarquia visual, estructura/layout, paleta, tipografia,
y que los ELEMENTOS clave del mockup esten presentes. NO se exige igualdad pixel a
pixel: el mockup es una INTENCION, no un plano. Exigir pixel-perfect no converge
nunca (el modelo de imagenes alucina layouts que a veces ni son construibles); el
arbitro puntua el ESPIRITU y deja que el cerebro se desvie por viabilidad.

BACKEND INTERCAMBIABLE: por defecto habla al VLM servido en COGNIA_VLM_URL
(llama-server con --mmproj, API multimodal compatible con OpenAI). La variable se
lee en CADA llamada, no al importar: exportarla a mitad de sesion funciona. Sin
backend vivo devuelve None y el llamador decide (no rompe el lazo).

NUNCA LANZA: como critico.py, todo va envuelto; ante cualquier fallo devuelve None.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

# Reusar el parser del critico: NOTA/VEREDICTO/DEFECTOS, tolerante a caja, coma
# decimal, idioma y bloques <think> de los modelos con razonamiento.
from .critico import _parsear

logger = logging.getLogger(__name__)

VLM_URL_DEFECTO = "http://127.0.0.1:8081"
TIMEOUT_SONDEO = 2
TIMEOUT_VLM = 180

# Estado del ULTIMO arbitraje de este proceso. Existe porque el degradado del
# arbitro es un None: no se le puede colgar un campo. Con esto el llamador puede
# preguntar "esto lo miro alguien?" DESPUES, sin cambiar el contrato (None).
_ULTIMO: dict = {"sin_vlm": None, "motivo": "todavia no se arbitro nada"}


def _marcar(sin_vlm: bool, motivo: str) -> None:
    """Registra como termino el arbitraje. Si degrado, ademas GRITA: un lazo
    que sigue sin que nadie mire el pixel tiene que verse en la corrida."""
    global _ULTIMO
    _ULTIMO = {"sin_vlm": sin_vlm, "motivo": motivo}
    if not sin_vlm:
        return
    try:
        from .. import backend_activo
        backend_activo.sin_backend("arbitro_visual", motivo)
    except Exception:
        pass


def ultimo_estado() -> dict:
    """{'sin_vlm': bool|None, 'motivo': str} del ultimo arbitrar_visual().

    sin_vlm=True significa NADIE MIRO LA PAGINA: el None que devolvio el arbitro
    NO es un veredicto, y el resultado del lazo no se puede llamar 'juzgado'."""
    return dict(_ULTIMO)

# Un solo sistema, dos modos de imagen. LADO A LADO es el modo por defecto: el
# VLM chico (Qwen2.5-VL-3B) razona MUCHO mejor con UNA imagen partida en dos
# mitades que con dos imagenes separadas. Medido el 2026-07-24 en esta maquina
# con las mismas imagenes: idos imagenes daba 6.5 a un par IDENTICO (y alucinaba
# defectos) y 7.0 a un par TOTALMENTE distinto (dashboard vs juego) — no
# discriminaba. Lado a lado dio 8.5 a las identicas y 0.0 a las distintas, con
# defectos correctos. La causa es conocida: los VLM pequenos atienden mal a
# varias imagenes a la vez. El fallback de dos imagenes queda solo por si no hay
# PIL para componer.
_SYSTEM = (
    "You are a senior product designer doing brutally honest visual QA. You are "
    "shown ONE image split into two halves: the LEFT half is the TARGET mockup "
    "(how the product was imagined) and the RIGHT half is a screenshot of the "
    "REAL built web page. You report how faithfully the RIGHT realizes the LEFT. "
    "You judge visual hierarchy, layout/structure, color palette, typography and "
    "whether the key elements of the mockup are present. You do NOT demand "
    "pixel-perfect equality — the mockup is an intent, not a blueprint; small "
    "position/size differences and different sample text are fine. You never "
    "inflate grades: a page that misses the mockup's structure or main elements "
    "is a 5, not an 8."
)

# La rubrica va en el prompt de usuario junto a la imagen. Cada defecto debe ser
# ACCIONABLE por un desarrollador front (es lo que leera reparar_web), no un
# reproche vago: "el header deberia ser una barra ancha arriba, no una caja
# centrada", no "se ve distinto".
_RUBRICA = """This single image has two halves:
- LEFT half = TARGET (the mockup the brain imagined for this product).
- RIGHT half = REAL (a screenshot of the actual built web page).

The product idea was: "{idea}"
{vision}
Compare the RIGHT half (real) against the LEFT half (target) on this checklist:
1. Overall layout & structure (same regions in the same places: header, main area, sidebar, footer...).
2. Visual hierarchy (does the same thing dominate the view?).
3. Color palette & mood (do the main colors and contrast match the intent?).
4. Key elements present (every prominent element of the mockup exists in the page).
5. Typography feel (headings vs body, weight, scale).
6. Polish (spacing, alignment, nothing looks broken or empty).

Do NOT penalize small pixel differences, different sample data/text, or minor
position/size shifts. Penalize STRUCTURAL and INTENT mismatches.

Each defect MUST be a concrete instruction a front-end developer can act on
(what is wrong AND the direction to fix it), e.g. "the KPI row should be three
cards across the top, not a single centered box".

Answer EXACTLY in this format, nothing else:
NOTA: <number 0-10, one decimal — how faithfully the RIGHT realizes the LEFT>
VEREDICTO: <one line>
DEFECTOS:
- <actionable defect>
- <actionable defect>
If the page faithfully realizes the mockup, DEFECTOS is exactly "- ninguno".
"""


def _parsear_visual(texto: str) -> Optional[Dict]:
    """Parser TOLERANTE del veredicto del VLM. Primero intenta el parser estricto
    del critico (NOTA/VEREDICTO/DEFECTOS); si el VLM se desvia del formato (el 3B
    a veces OMITE la linea NOTA y pone el numero en VEREDICTO — medido 2026-07-24),
    rescata la nota (de 'N/10', de la linea nota/veredicto/score, o un numero
    suelto) y los defectos. Clave: devuelve los DEFECTOS aunque falte la nota — el
    lazo puede reparar con ellos. None solo si no hay ni nota ni defectos."""
    if not texto:
        return None
    base = _parsear(texto)
    if base is not None:
        return base

    t = texto.split("</think>", 1)[1] if "</think>" in texto else texto
    lineas = t.strip().splitlines()

    defectos = [l.strip().lstrip("-*").strip() for l in lineas
                if l.strip().startswith(("- ", "* "))]
    defectos = [d for d in defectos if d]
    if [d.lower() for d in defectos] in (["ninguno"], ["none"]):
        defectos = []

    nota = None
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*/\s*10', t)
    if not m:
        for l in lineas:
            low = l.lower().lstrip()
            if low.startswith(("nota", "note", "veredicto", "verdict", "score")):
                m = re.search(r'(\d+(?:[.,]\d+)?)', l)
                if m:
                    break
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
            if 0.0 <= val <= 10.0:
                nota = val
        except ValueError:
            pass

    veredicto = ""
    for l in lineas:
        if l.lower().lstrip().startswith(("veredicto", "verdict")) and ":" in l:
            veredicto = l.split(":", 1)[1].strip()
            break

    if nota is None and not defectos:
        return None
    return {"nota": nota, "veredicto": veredicto, "defectos": defectos}


def url_vlm() -> str:
    """URL del backend VLM. Se lee en call-time (env override en caliente)."""
    return (os.environ.get("COGNIA_VLM_URL") or VLM_URL_DEFECTO).strip().rstrip("/")


def vlm_disponible(url: str = None) -> tuple:
    """(ok, motivo). Sondea /health del llama-server multimodal. Barato."""
    u = (url or url_vlm())
    try:
        req = urllib.request.Request(u + "/health")
        with urllib.request.urlopen(req, timeout=TIMEOUT_SONDEO) as r:
            if r.status == 200:
                return True, "ok"
            return False, f"health devolvio {r.status}"
    except Exception as e:
        return False, f"sin VLM en {u} ({e})"


def _datauri_png(ruta) -> Optional[str]:
    """PNG en disco -> data URI base64. None si no se puede leer."""
    try:
        datos = Path(ruta).read_bytes()
        b64 = base64.b64encode(datos).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        logger.warning("arbitro_visual: no pude leer la imagen %s (%s)", ruta, e)
        return None


def _lado_a_lado(mockup, screenshot, salida, *, alto: int = 700) -> Optional[str]:
    """Compone el mockup (IZQUIERDA=objetivo) y el screenshot (DERECHA=real) en
    UNA sola imagen con una banda de etiquetas arriba. Devuelve la ruta, o None si
    no hay PIL o algo falla (el llamador cae al modo de dos imagenes).

    POR QUE: el VLM chico discrimina mucho mejor con una imagen partida que con
    dos imagenes separadas (medido 2026-07-24, ver cabecera del modulo).

    alto=700 y no 512, tambien medido: con dos escenas oscuras y densas (juego
    arcade vs su mockup) a 512 el 3B ALUCINABA la mitad derecha vacia y daba 0.0;
    a 700 la lee bien y da notas coherentes (7.5). La resolucion de la compuesta
    es parte del contrato de calidad del arbitro."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    try:
        def _cargar(x):
            im = Image.open(x).convert("RGB")
            w = max(1, int(im.width * alto / max(1, im.height)))
            return im.resize((w, alto))

        izq, der = _cargar(mockup), _cargar(screenshot)
        sep, banda = 10, 30
        ancho = izq.width + der.width + sep
        lienzo = Image.new("RGB", (ancho, alto + banda), (18, 18, 18))
        lienzo.paste(izq, (0, banda))
        lienzo.paste(der, (izq.width + sep, banda))
        d = ImageDraw.Draw(lienzo)
        d.text((6, 8), "LEFT = TARGET (mockup)", fill=(255, 255, 255))
        d.text((izq.width + sep + 6, 8), "RIGHT = REAL (page)", fill=(255, 255, 255))
        lienzo.save(salida)
        return str(salida)
    except Exception as e:
        logger.warning("arbitro_visual: no pude componer lado a lado (%s)", e)
        return None


def _preguntar_vlm(url: str, prompt: str, imagenes: List[str]) -> Optional[str]:
    """POST multimodal al VLM (formato OpenAI). imagenes = lista de data URIs.
    Devuelve el texto de la respuesta o None."""
    try:
        contenido = [{"type": "text", "text": prompt}]
        for datauri in imagenes:
            contenido.append({"type": "image_url",
                              "image_url": {"url": datauri}})
        cuerpo = json.dumps({
            "model": "local",
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": contenido}],
            "temperature": 0.2,
            # El VLM describe y razona antes de dar la nota; 400 se quedaba corto
            # con dos imagenes (medido en el patron del critico con UIGEN).
            "max_tokens": 900,
        }).encode("utf-8")
        peticion = urllib.request.Request(
            url + "/v1/chat/completions", data=cuerpo,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_VLM) as r:
            datos = json.loads(r.read().decode("utf-8"))
        return datos["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("arbitro_visual: el VLM de %s no respondio (%s)", url, e)
        return None


def arbitrar_visual(idea: str, screenshot, mockup=None, *,
                    vision_texto: str = "", url: str = None) -> Optional[Dict]:
    """
    El ojo del arbitro: compara el screenshot real contra el mockup objetivo.

    Args:
        idea:         la idea del producto (para dar contexto al VLM).
        screenshot:   ruta al PNG de la pagina renderizada (input/output_images
                      de vista_navegador.InformeVisual).
        mockup:       ruta al PNG de la vision/mockup objetivo. Si es None, se
                      juzga el screenshot contra la descripcion de texto
                      (vision_texto) en vez de contra una imagen.
        vision_texto: descripcion en palabras de como deberia verse (opcional;
                      complementa al mockup o lo sustituye si no hay imagen).
        url:          override del backend VLM.

    Returns:
        {"nota": float, "veredicto": str, "defectos": [str], "critico": "vlm",
         "sin_vlm": False} — el sin_vlm=False dice explicitamente QUE SE MIRO.
        o None si no hay VLM vivo, no se pudieron leer las imagenes o nada
        parseo. Ese None NO es un veredicto: ultimo_estado()['sin_vlm'] queda en
        True y el degradado se grita por stderr. NUNCA lanza.
    """
    tmp_compuesta = None
    try:
        u = (url or url_vlm())
        vision_linea = ""
        if vision_texto:
            vision_linea = f'The intended look, in words: "{vision_texto.strip()}"\n'

        imagenes: List[str] = []
        if mockup is not None:
            # Modo por defecto: componer mockup+screenshot lado a lado en UNA
            # imagen (el VLM chico discrimina mucho mejor asi). Fallback a dos
            # imagenes solo si no hay PIL para componer.
            fd, tmp_compuesta = tempfile.mkstemp(prefix="arb_sbs_", suffix=".png")
            os.close(fd)
            compuesta = _lado_a_lado(mockup, screenshot, tmp_compuesta)
            if compuesta is not None:
                datauri = _datauri_png(compuesta)
                if datauri is None:
                    _marcar(True, "no se pudo leer la imagen compuesta "
                                  "mockup+screenshot: NADIE juzgo el pixel")
                    return None
                imagenes = [datauri]
                prompt = _RUBRICA.format(idea=(idea or "")[:400],
                                         vision=vision_linea)
            else:
                # Fallback (sin PIL): dos imagenes separadas, objetivo primero.
                img_mockup = _datauri_png(mockup)
                img_screenshot = _datauri_png(screenshot)
                if img_mockup is None or img_screenshot is None:
                    _marcar(True, "mockup o screenshot ilegibles: NADIE juzgo "
                                  "el pixel")
                    return None
                imagenes = [img_mockup, img_screenshot]
                prompt = (
                    f'IMAGE 1 = TARGET mockup. IMAGE 2 = REAL built page.\n'
                    f'The product idea was: "{(idea or "")[:400]}"\n{vision_linea}\n'
                    f"How faithfully does IMAGE 2 realize IMAGE 1? Judge layout, "
                    f"hierarchy, palette, key elements. Penalize structural "
                    f"mismatches, not pixels.\n\nAnswer EXACTLY:\nNOTA: <0-10, one "
                    f"decimal>\nVEREDICTO: <one line>\nDEFECTOS:\n- <actionable "
                    f'defect>\nIf faithful, DEFECTOS is exactly "- ninguno".')
        else:
            # Sin mockup: solo el screenshot; la vision va como texto.
            img_screenshot = _datauri_png(screenshot)
            if img_screenshot is None:
                _marcar(True, "screenshot ilegible: NADIE juzgo el pixel")
                return None
            imagenes = [img_screenshot]
            prompt = (
                f'IMAGE 1 = a screenshot of the actual built web page.\n'
                f'The product idea was: "{(idea or "")[:400]}"\n{vision_linea}\n'
                f"Judge how well the page realizes that intent on layout, visual "
                f"hierarchy, palette, key elements, typography and polish. Do not "
                f"penalize sample data or tiny pixel differences.\n\n"
                f"Answer EXACTLY:\nNOTA: <0-10, one decimal>\nVEREDICTO: <one line>\n"
                f"DEFECTOS:\n- <actionable defect>\nIf excellent, DEFECTOS is "
                f'exactly "- ninguno".')

        ok, motivo = vlm_disponible(u)
        if not ok:
            logger.warning("arbitro_visual: %s", motivo)
            _marcar(True, f"{motivo}: la pagina NO fue mirada por nadie, el "
                          f"lazo sigue solo con la sonda estructural")
            return None

        texto = _preguntar_vlm(u, prompt, imagenes)
        if not texto:
            _marcar(True, f"el VLM de {u} no devolvio texto: NADIE juzgo el pixel")
            return None
        resultado = _parsear_visual(texto)
        if resultado is None:
            _marcar(True, "veredicto del VLM imparseable: NADIE juzgo el pixel")
            return None
        resultado["critico"] = "vlm"
        # Marca POSITIVA en la salida: este dict SI lo miro un VLM. Su ausencia
        # (o sin_vlm=True) nunca puede confundirse con "juzgado".
        resultado["sin_vlm"] = False
        _marcar(False, f"juzgado por el VLM de {u}")
        return resultado
    except Exception as e:
        # Un arbitro roto no tumba la generacion (misma politica que critico.py).
        logger.warning("arbitro_visual: fallo inesperado (%s)", e)
        _marcar(True, f"el arbitro fallo ({e}): NADIE juzgo el pixel")
        return None
    finally:
        if tmp_compuesta:
            try:
                os.remove(tmp_compuesta)
            except OSError:
                pass


def arbitrar_desde_informe(idea: str, informe, mockup=None, *,
                           vision_texto: str = "", url: str = None) -> Optional[Dict]:
    """Conveniencia: toma el screenshot directamente de un InformeVisual de
    vista_navegador (output_images si la pagina se acepto, si no la ultima
    input_images). Devuelve lo mismo que arbitrar_visual, o None."""
    try:
        shots = list(getattr(informe, "output_images", []) or []) \
            or list(getattr(informe, "input_images", []) or [])
        if not shots:
            _marcar(True, "el informe visual no trajo ningun screenshot: no "
                          "hubo nada que mirar")
            return None
        return arbitrar_visual(idea, shots[-1], mockup,
                               vision_texto=vision_texto, url=url)
    except Exception as e:
        logger.warning("arbitro_visual: informe sin screenshot usable (%s)", e)
        _marcar(True, f"informe sin screenshot usable ({e}): NADIE juzgo el pixel")
        return None
