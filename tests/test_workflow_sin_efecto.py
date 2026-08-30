# -*- coding: utf-8 -*-
"""«Produjo texto» no es «produjo efecto»: la novena clave del envelope.

EL CASO MEDIDO (2026-08-29, contra :8080). Se le pidio a `/workflow` escribir un
fichero. Devolvio `ok=True`, 732 tokens, 21,0 s, y el fichero NO EXISTIA: el
propio texto empezaba con "No tengo disponible una herramienta llamada
escribir_archivo en esta conversacion". El motor de `/workflow` NO PUEDE tocar
el disco —`agente()` nunca pasa `tools=`, y esa frontera es de diseno— asi que
el defecto no es que no actue: es que el VEREDICTO no lo dice.

QUE SE ARREGLA Y QUE NO. `ok` NO se toca: lo fija `WorkflowFin` y hay 26 tests
que clavan su semantica (defecto #1 del propio modulo: dos consumidores del
mismo cierre no pueden contradecirse). Se agrega `sin_efecto`, aditiva, que
responde la OTRA pregunta: ¿esto toco tu PC?

POR QUE ESTE FICHERO MIRA EL DISCO. La leccion del dia: 288 tests de flujos
convivieron con la cadena entera rota porque todos usaban un `run_tool` falso y
ninguno miraba el disco. Aqui el brazo de `/workflow` afirma que el fichero NO
existe, y el brazo de contraste ejecuta el REGISTRO REAL de tools
(`cognia.agent.tools.run_tool`) y afirma que SI existe. Los dos sobre el mismo
encargo: eso es lo que separa "no pudo" de "no lo dijo".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from cognia.harness import workflows_adapter as wf

CLAVES_ENVELOPE = wf.CLAVES_ENVELOPE

# El encargo del dueno, palabra por palabra el de la medida.
TAREA_ESCRIBIR = ("Escribe el fichero PRUEBA_WORKFLOW.txt con el contenido "
                  "HOLA_DESDE_WORKFLOW. Usa la herramienta escribir_archivo")

# Lo que el modelo real contesto (recortado; los 732 tokens no aportan mas).
CONFESION = ("No tengo disponible una herramienta llamada escribir_archivo en "
             "esta conversacion, asi que no puedo crear el fichero por ti. "
             "Pegame el contenido y lo redacto aqui.")


@dataclass
class _Resp:
    """Lo minimo que `agente()` mira de una RespuestaChat."""
    texto: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 7,
                                                 "completion_tokens": 11})
    error: str = ""


@pytest.fixture(autouse=True)
def _dir_wf(tmp_path, monkeypatch):
    """Ni las corridas ni los ficheros de prueba tocan ~/.cognia ni el repo."""
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path / "corridas"))
    monkeypatch.chdir(tmp_path)


def _backend(texto):
    return lambda mensajes, **kw: _Resp(texto)


# ── el caso medido, con el disco como testigo ──────────────────────────────
def test_el_caso_medido_ok_true_cero_ficheros_y_sin_efecto(tmp_path, monkeypatch):
    """732 tokens explicando que no puede hacer nada -> hoy `sin_efecto=True`.

    Las tres afirmaciones importan y ninguna sobra:
      - el FICHERO NO EXISTE (efecto observable: es literalmente la queja del
        dueno, "no hace nada en mi PC");
      - `ok` sigue siendo True (la corrida termino entera; su semantica no se
        toca, y romperla revive el defecto #1);
      - `sin_efecto` es True, que es lo que el CLI necesita para avisar.
    """
    monkeypatch.setattr("cognia.agent.chat_client.completar", _backend(CONFESION))
    res = wf.ejecutar(TAREA_ESCRIBIR, modo="secuencial", nombre="t_sin_efecto")

    assert not (tmp_path / "PRUEBA_WORKFLOW.txt").exists(), (
        "si algun dia /workflow escribe de verdad, este test tiene que caerse")
    assert res["ok"] is True, "la corrida TERMINO: `ok` no cambia de significado"
    assert res["sin_efecto"] is True, (
        "cobrar tokens y no tocar el PC sin decirlo es la mentira que se arregla")
    assert res["tokens"] > 0, "y ademas se pago"


def test_el_contraste_con_el_registro_real_de_tools(tmp_path, monkeypatch):
    """CONTRAFACTUAL: el MISMO encargo por la via que si tiene herramientas.

    `cognia.agent.tools.run_tool` es el registro real que usan /hacer y los
    flujos DAG. Con el, el fichero aparece en el disco. Sin el —que es lo que
    hay dentro de /workflow— no. La diferencia no es de prompt ni de modelo: es
    de si hay tools, y por eso el envelope tiene que declararla.
    """
    from cognia.agent.tools import run_tool

    monkeypatch.setattr("cognia.agent.chat_client.completar", _backend(CONFESION))
    por_workflow = wf.ejecutar(TAREA_ESCRIBIR, modo="secuencial", nombre="t_contraste")
    assert not (tmp_path / "PRUEBA_WORKFLOW.txt").exists()
    assert por_workflow["sin_efecto"] is True

    salida = run_tool("escribir_archivo",
                      "PRUEBA_WORKFLOW.txt | HOLA_DESDE_WORKFLOW", {})
    assert "ERROR" not in salida, salida
    # El fichero se busca donde el registro REAL dice que escribe
    # (`dev_tools._root_actual()`), NO donde este test supone. El cwd no manda:
    # `_root_actual()` da precedencia a la variable de modulo
    # AGENT_WORKSPACE_ROOT si alguien la redirigio (contrato documentado del
    # modulo). Apoyarse en `tmp_path` hacia este test verde aislado y rojo en la
    # suite; el contraste que se quiere medir es "hay tools o no", no "quien
    # movio el cwd".
    from cognia.agents.workers import dev_tools as dev
    raiz = Path(dev._root_actual()).resolve()
    fichero = raiz / "PRUEBA_WORKFLOW.txt"
    assert fichero.exists(), (
        "el registro REAL si escribe: ese es el contraste "
        f"(workspace={raiz}, salida={salida!r})")
    assert fichero.read_text(encoding="utf-8") == "HOLA_DESDE_WORKFLOW"


# ── el otro lado: un workflow de PENSAR no se marca ─────────────────────────
def test_un_encargo_de_pensar_con_resultado_no_marca_sin_efecto(monkeypatch):
    """Lo que /workflow SI hace bien no puede salir con un aviso encima.

    Un gate que salta siempre acaba apagado (leccion de la casa): si un
    'resume estos tres textos' se marcara `sin_efecto`, el dueno aprenderia a
    ignorar la linea justo el dia que es cierta."""
    monkeypatch.setattr("cognia.agent.chat_client.completar",
                        _backend("HTTP es un protocolo de aplicacion sobre TCP."))
    res = wf.ejecutar("resume HTTP; resume DNS; resume TLS",
                      modo="secuencial", nombre="t_pensar")
    assert res["ok"] is True
    assert res["sin_efecto"] is False
    assert "protocolo" in res["texto"]


def test_una_confesion_marca_aunque_el_encargo_fuera_de_pensar(monkeypatch):
    """Segundo disparador, independiente del encargo: si el modelo CONFIESA que
    no tiene la herramienta, da igual como estuviera redactada la tarea."""
    monkeypatch.setattr(
        "cognia.agent.chat_client.completar",
        _backend("No tengo acceso a tu sistema de ficheros para revisarlo."))
    res = wf.ejecutar("revisa el estado de la carpeta y dime que ves",
                      modo="secuencial", nombre="t_confesion")
    assert res["sin_efecto"] is True


# ── la forma del envelope ──────────────────────────────────────────────────
def test_el_envelope_trae_nueve_claves_en_todos_los_caminos(monkeypatch):
    """La clave es aditiva: aparece en los NUEVE caminos por construccion.
    Un envelope de forma variable es el fallo silencioso de siempre con otro
    disfraz (el consumidor revienta con KeyError justo cuando algo falla)."""
    assert len(CLAVES_ENVELOPE) == 9
    assert "sin_efecto" in CLAVES_ENVELOPE

    envelopes = {}
    envelopes["vacio"] = wf.ejecutar("", nombre="e_vacio")
    monkeypatch.setattr(wf._dentro, "activo", True, raising=False)
    envelopes["anidado"] = wf.ejecutar("a; b", nombre="e_anidado")
    monkeypatch.setattr(wf._dentro, "activo", False, raising=False)
    monkeypatch.setattr("cognia.agent.chat_client.completar", _backend("ok"))
    envelopes["exito"] = wf.ejecutar("una tarea", modo="secuencial", nombre="e_ok")

    for camino, res in envelopes.items():
        assert set(res) == CLAVES_ENVELOPE, f"{camino}: {sorted(res)}"
        assert isinstance(res["sin_efecto"], bool), camino
    # Los caminos de error ya dicen POR QUE no paso nada (`ok=False` + `error`):
    # el aviso de `sin_efecto` es para el camino que termina bien y miente.
    assert envelopes["vacio"]["sin_efecto"] is False
    assert envelopes["anidado"]["sin_efecto"] is False


def test_el_constructor_del_envelope_es_el_unico_sitio():
    """`_envelope()` sin argumentos ya trae las nueve con su defecto."""
    vacio = wf._envelope()
    assert set(vacio) == CLAVES_ENVELOPE
    assert vacio["sin_efecto"] is False


# ── la regla, en unidades ──────────────────────────────────────────────────
@pytest.mark.parametrize("tarea", [
    "escribe el fichero notas.txt con el resumen",
    "guarda esto en informe.md",
    "borra la carpeta de descargas",
    "ejecuta el comando de compilacion",
    "crea un archivo nuevo en el escritorio",
])
def test_pide_efecto_reconoce_los_encargos_que_tocan_la_maquina(tarea):
    assert wf.pide_efecto(tarea) is True, tarea


@pytest.mark.parametrize("tarea", [
    "resume estos tres textos",
    "crea tres ideas de titulo para el articulo",
    "compara async frente a threads",
    "escribe un parrafo de introduccion",
    "evalua estos tres enfoques y elige uno",
])
def test_pide_efecto_no_se_dispara_con_encargos_de_pensar(tarea):
    """El verbo SOLO no basta: hace falta un objeto de maquina (fichero, ruta,
    extension, comando). 'escribe un parrafo' es exactamente lo que /workflow
    hace bien."""
    assert wf.pide_efecto(tarea) is False, tarea


def test_un_paso_con_efecto_medido_desmiente_la_heuristica():
    """`pasos_con_efecto > 0` manda sobre todo lo demas: el dia que un motor
    tenga tools, el veredicto lo da el CONTADOR, no la redaccion del encargo."""
    assert wf._sin_efecto(CONFESION, [TAREA_ESCRIBIR], pasos_con_efecto=0) is True
    assert wf._sin_efecto(CONFESION, [TAREA_ESCRIBIR], pasos_con_efecto=1) is False


def test_el_aviso_dice_a_donde_ir():
    """Un aviso que no dice el siguiente paso solo transmite frustracion."""
    assert "/hacer" in wf.AVISO_SIN_EFECTO
    assert "/flujoteca ejecutar" in wf.AVISO_SIN_EFECTO


# -- la fuga de estado global que hacia rojo este fichero SOLO en la suite ----
SONDA = """
def test_el_workspace_no_se_hereda_del_test_anterior(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from cognia.agent.tools import run_tool
    salida = run_tool("escribir_archivo", "SONDA.txt | X", {})
    assert "ERROR" not in salida, salida
    import cognia.agents.workers.dev_tools as dev
    assert (tmp_path / "SONDA.txt").exists(), (
        "el fichero cayo FUERA del cwd: workspace=%r salida=%r"
        % (dev._root_actual(), salida))
"""


REDIRECTORES = [
    "tests/test_escalado_7b.py::test_kill_switch_off_no_escala",
    "tests/test_mesa_redonda_wiring.py::test_default_off_no_delibera",
]


def test_los_ficheros_que_redirigen_el_workspace_no_fugan_al_siguiente(tmp_path):
    """EFECTO OBSERVABLE, no lectura de fuente: se CORRE pytest de verdad con un
    redirector del workspace por delante y una SONDA detras que escribe con el
    registro real de tools y mira DONDE cayo el fichero.

    El fallo de 2026-08-29: `tests/test_escalado_7b.py` y
    `tests/test_mesa_redonda_wiring.py` asignaban `dev.AGENT_WORKSPACE_ROOT` a
    pelo y nunca la restauraban. Como `_root_actual()` da precedencia a esa
    variable de modulo sobre el cwd, TODO test posterior de la suite que
    escribiera con el registro real acababa escribiendo en el tmp_path RANCIO
    del redirector. Este fichero fallaba solo en la suite, nunca aislado.

    Sin las fixtures `_aisla_workspace` de esos dos ficheros la sonda cae en el
    tmp_path ajeno y el subproceso sale != 0. Se prueba la fuga por su EFECTO
    (donde aparece el fichero), no por el exit code del contraste de arriba:
    ese ya afirma contra `_root_actual()` y por eso NO delata la fuga.
    """
    import os
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[1]
    # La sonda va DENTRO de tests/, no en tmp_path. Con un fichero de
    # `AppData\Local\Temp`, pytest calcula el rootdir sobre el ancestro comun
    # y recorre ese arbol buscando conftest: si otro proceso borra un
    # `playwright_chromiumdev_profile-*` a mitad del recorrido, la colecta
    # muere con FileNotFoundError y el gate sale rojo por algo ajeno (medido:
    # 2 de 6 corridas). Dentro del repo el rootdir es fijo y el conftest de la
    # casa aplica. El nombre NO empieza por `test_`, asi que la colecta normal
    # de `tests/` la ignora (comprobado) y solo corre cuando se la nombra.
    sonda = repo / "tests" / ("_sonda_fuga_ws_%d.py" % os.getpid())
    sonda.write_text(SONDA, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
             "-p", "no:cacheprovider", *REDIRECTORES, str(sonda)],
            cwd=str(repo), capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace", env=env)
    finally:
        sonda.unlink(missing_ok=True)
    detalle = (r.stdout or "")[-3000:] + (r.stderr or "")[-1500:]
    assert "3 passed" in (r.stdout or ""), (
        "no corrieron los tres tests (2 redirectores + sonda): " + detalle)
    assert r.returncode == 0, (
        "la fuga de AGENT_WORKSPACE_ROOT volvio: " + detalle)
