"""
El arbitro VISUAL: el que MIRA la pagina en vez de leerla.

A diferencia de critico.py (juzga sobre hechos medidos por la sonda, es texto),
arbitro_visual compara el SCREENSHOT real contra el MOCKUP objetivo con un VLM y
emite defectos en el MISMO formato que reparar_web ya consume. Estos tests cubren
todo menos la llamada real al VLM (parcheada): corren en CPU, sin GPU ni modelo.
"""

import base64
import struct
import zlib
from unittest.mock import patch

from cognia.program_creator import arbitro_visual as av

# Un PNG 1x1 valido (rojo). Se conserva para probar el RECHAZO de screenshots
# minusculos (_screenshot_juzgable): el VLM le dio 9.5 a un 1x1 real.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _png_bytes(ancho=120, alto=120) -> bytes:
    """PNG RGB valido, >=100px de lado y CON varianza, en puro stdlib. Los
    fixtures de screenshot deben pasar _screenshot_juzgable (un 1x1 ya no
    entra al arbitro), y no queremos depender de PIL para generarlos."""
    def chunk(tipo, datos):
        c = tipo + datos
        return struct.pack(">I", len(datos)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    filas = b"".join(
        b"\x00" + bytes(v for x in range(ancho)
                        for v in ((x * 7 + y * 13) % 256, (x * 3) % 256,
                                  (y * 5) % 256))
        for y in range(alto))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(filas)) + chunk(b"IEND", b""))


_PNG_GRANDE = _png_bytes()

_RESP_OK = "NOTA: 7.5\nVEREDICTO: fiel al mockup\nDEFECTOS:\n- ninguno"
_RESP_DEFECTOS = ("NOTA: 4.0\nVEREDICTO: estructura distinta\nDEFECTOS:\n"
                  "- el header deberia ser una barra ancha arriba, no una caja "
                  "centrada\n- faltan las tres tarjetas de KPI")


def _png(tmp_path, nombre="shot.png"):
    p = tmp_path / nombre
    p.write_bytes(_PNG_GRANDE)
    return p


# ── parser tolerante ─────────────────────────────────────────────────────────

def test_parser_formato_estricto_delega_al_critico():
    r = av._parsear_visual("NOTA: 6.0\nVEREDICTO: ok\nDEFECTOS:\n- x")
    assert r["nota"] == 6.0 and r["defectos"] == ["x"]


def test_parser_rescata_cuando_falta_nota_y_va_en_veredicto():
    """El 3B a veces omite NOTA y pone el numero en VEREDICTO (medido)."""
    r = av._parsear_visual(
        'VEREDICTO: 3.0\nDEFECTOS:\n- el titulo no esta en su lugar\n'
        '- el menu no se ve')
    assert r["nota"] == 3.0
    assert len(r["defectos"]) == 2


def test_parser_rescata_formato_n_sobre_10():
    r = av._parsear_visual("The page scores 8.5/10 overall.\nDEFECTOS:\n- ninguno")
    assert r["nota"] == 8.5
    assert r["defectos"] == []


def test_parser_devuelve_defectos_aunque_no_haya_nota():
    """Clave: sin nota pero con defectos, el lazo aun puede reparar."""
    r = av._parsear_visual("DEFECTOS:\n- falta el header\n- sin sidebar")
    assert r["nota"] is None
    assert len(r["defectos"]) == 2


def test_parser_basura_es_none():
    assert av._parsear_visual("no pienso responder nada de esto") is None


# ── data URI ────────────────────────────────────────────────────────────────

def test_datauri_de_un_png(tmp_path):
    uri = av._datauri_png(_png(tmp_path))
    assert uri.startswith("data:image/png;base64,")
    # el base64 decodifica al PNG original
    assert base64.b64decode(uri.split(",", 1)[1]) == _PNG_GRANDE


def test_datauri_de_ruta_inexistente_es_none(tmp_path):
    assert av._datauri_png(tmp_path / "no_existe.png") is None


# ── arbitrar_visual: caminos ──────────────────────────────────────────────────

def test_sin_vlm_devuelve_none(tmp_path):
    with patch.object(av, "vlm_disponible", return_value=(False, "sin VLM")):
        assert av.arbitrar_visual("idea", _png(tmp_path)) is None


def test_marca_el_critico_como_vlm(tmp_path):
    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_preguntar_vlm", return_value=_RESP_OK):
        r = av.arbitrar_visual("idea", _png(tmp_path, "shot.png"),
                               _png(tmp_path, "mock.png"))
    assert r["critico"] == "vlm"
    assert r["nota"] == 7.5
    assert r["defectos"] == []


def test_defectos_llegan_en_el_formato_de_reparar_web(tmp_path):
    """El contrato con generator.reparar_web: defectos es una lista de strings
    accionables. Si esto cambia, el lazo de reparacion se queda mudo."""
    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_preguntar_vlm", return_value=_RESP_DEFECTOS):
        r = av.arbitrar_visual("dashboard", _png(tmp_path, "s.png"),
                               _png(tmp_path, "m.png"))
    assert r["nota"] == 4.0
    assert isinstance(r["defectos"], list) and len(r["defectos"]) == 2
    assert all(isinstance(d, str) and d for d in r["defectos"])


def test_con_mockup_compone_una_sola_imagen(tmp_path):
    """Modo por defecto (con PIL): mockup+screenshot se componen LADO A LADO en
    UNA imagen — el VLM chico discrimina mucho mejor asi (medido 2026-07-24)."""
    capturado = {}

    def _fake(url, prompt, imagenes):
        capturado["imagenes"] = imagenes
        capturado["prompt"] = prompt
        return _RESP_OK

    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_preguntar_vlm", side_effect=_fake):
        av.arbitrar_visual("idea", _png(tmp_path, "real.png"),
                           _png(tmp_path, "target.png"))

    assert len(capturado["imagenes"]) == 1        # una imagen compuesta
    assert "LEFT half = TARGET" in capturado["prompt"]
    assert "RIGHT half = REAL" in capturado["prompt"]


def test_fallback_a_dos_imagenes_si_no_hay_pil(tmp_path):
    """Sin PIL para componer (_lado_a_lado -> None), cae a dos imagenes
    separadas, objetivo primero, y el prompt las nombra."""
    capturado = {}

    def _fake(url, prompt, imagenes):
        capturado["imagenes"] = imagenes
        capturado["prompt"] = prompt
        return _RESP_OK

    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_lado_a_lado", return_value=None), \
         patch.object(av, "_preguntar_vlm", side_effect=_fake):
        av.arbitrar_visual("idea", _png(tmp_path, "real.png"),
                           _png(tmp_path, "target.png"))

    assert len(capturado["imagenes"]) == 2
    assert "IMAGE 1 = TARGET" in capturado["prompt"]


def test_sin_mockup_manda_una_imagen(tmp_path):
    capturado = {}

    def _fake(url, prompt, imagenes):
        capturado["imagenes"] = imagenes
        return _RESP_OK

    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_preguntar_vlm", side_effect=_fake):
        r = av.arbitrar_visual("idea", _png(tmp_path),
                               vision_texto="un dashboard oscuro y denso")
    assert len(capturado["imagenes"]) == 1
    assert r["critico"] == "vlm"


def test_screenshot_ilegible_devuelve_none(tmp_path):
    with patch.object(av, "vlm_disponible", return_value=(True, "ok")):
        assert av.arbitrar_visual("idea", tmp_path / "no.png") is None


# ── regresion 2026-08-01: un 1x1px saco 9.5 "Excelente" del VLM ──────────────

def test_screenshot_1x1_se_rechaza_sin_preguntar_al_vlm(tmp_path):
    """Un PNG de 1x1 no es una pagina: el arbitro debe cortar ANTES del VLM
    (que, medido, alucino un 9.5). El None queda marcado como NO-veredicto."""
    p = tmp_path / "s.png"
    p.write_bytes(_PNG_1x1)
    llamadas = []

    def _fake(url, prompt, imagenes):
        llamadas.append(url)
        return _RESP_OK

    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_preguntar_vlm", side_effect=_fake):
        assert av.arbitrar_visual("idea", p) is None
    assert llamadas == []                      # el VLM ni se entero
    assert av.ultimo_estado()["sin_vlm"] is True


def test_screenshot_grande_pasa_el_filtro(tmp_path):
    ok, motivo = av._screenshot_juzgable(_png(tmp_path))
    assert ok, motivo


# ── la URL se lee al llamar, no al importar ──────────────────────────────────

def test_url_vlm_se_lee_en_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_VLM_URL", "http://127.0.0.1:9911")
    urls = []

    def _fake(url, prompt, imagenes):
        urls.append(url)
        return _RESP_OK

    # vlm_disponible real leeria la env tambien; la parcheamos para no tocar red.
    with patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
         patch.object(av, "_preguntar_vlm", side_effect=_fake):
        av.arbitrar_visual("idea", _png(tmp_path, "s.png"), _png(tmp_path, "m.png"))
    assert urls == ["http://127.0.0.1:9911"]


# ── arbitrar_desde_informe: elige el screenshot correcto ─────────────────────

class _InformeFalso:
    def __init__(self, entrada=None, salida=None):
        self.input_images = entrada or []
        self.output_images = salida or []


def test_informe_prefiere_output_images(tmp_path):
    s_in = str(_png(tmp_path, "in.png"))
    s_out = str(_png(tmp_path, "out.png"))
    informe = _InformeFalso(entrada=[s_in], salida=[s_out])
    capturado = {}

    def _fake(idea, screenshot, mockup, **kw):
        capturado["screenshot"] = screenshot
        return {"nota": 8.0, "veredicto": "ok", "defectos": [], "critico": "vlm"}

    with patch.object(av, "arbitrar_visual", side_effect=_fake):
        av.arbitrar_desde_informe("idea", informe)
    assert capturado["screenshot"] == s_out


def test_informe_cae_a_input_images_si_no_hay_output(tmp_path):
    s_in = str(_png(tmp_path, "in.png"))
    informe = _InformeFalso(entrada=[s_in], salida=[])
    capturado = {}

    def _fake(idea, screenshot, mockup, **kw):
        capturado["screenshot"] = screenshot
        return {"nota": 5.0, "veredicto": "", "defectos": [], "critico": "vlm"}

    with patch.object(av, "arbitrar_visual", side_effect=_fake):
        av.arbitrar_desde_informe("idea", informe)
    assert capturado["screenshot"] == s_in


def test_informe_sin_screenshots_devuelve_none():
    assert av.arbitrar_desde_informe("idea", _InformeFalso()) is None
