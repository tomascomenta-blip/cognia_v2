"""Regresion de cognia/harness/modo_plan.py — el MODO plan bloquea de verdad.

Antes de este modulo el /plan de Cognia era solo un ARTEFACTO: describia lo que
se iba a hacer y nada impedia que el agente lo hiciera igual. Estos tests fijan
el freno: en modo plan las tools de escritura devuelven (False, motivo), las de
lectura pasan, y aprobar el plan devuelve el objetivo Y saca del modo.
"""
import pytest

from cognia.harness import modo_plan


@pytest.fixture(autouse=True)
def _sesion_limpia():
    # el estado es global por proceso: cada test arranca y termina en limpio
    modo_plan.reiniciar()
    yield
    modo_plan.reiniciar()


# ── modo ──────────────────────────────────────────────────────────────────────

def test_default_es_ejecutar_y_alternar_conmuta():
    assert modo_plan.modo_actual() == "ejecutar"
    assert not modo_plan.en_modo_plan()
    assert modo_plan.alternar() == "plan"          # shift+tab
    assert modo_plan.en_modo_plan()
    assert modo_plan.alternar() == "ejecutar"
    assert not modo_plan.en_modo_plan()


def test_activar_modo_invalido_levanta():
    with pytest.raises(ValueError):
        modo_plan.activar("act")
    assert modo_plan.modo_actual() == "ejecutar"   # no quedo a medias


def test_activar_normaliza_mayusculas_y_espacios():
    assert modo_plan.activar("  PLAN ") == "plan"
    assert modo_plan.en_modo_plan()


# ── politica de tools ─────────────────────────────────────────────────────────

def test_en_modo_ejecutar_no_bloquea_nada():
    permitido, motivo = modo_plan.puede_usar("escribir_archivo")
    assert permitido and motivo == ""
    permitido, motivo = modo_plan.puede_usar("borrar_archivo", danger=True)
    assert permitido and motivo == ""


@pytest.mark.parametrize("tool", [
    "escribir_archivo", "editar_archivo", "apendar_archivo", "borrar_archivo",
    "copiar_archivo", "ejecutar", "powershell", "tests", "generar_codigo",
    "crear_herramienta", "memorizar",
])
def test_modo_plan_bloquea_las_de_escritura(tool):
    modo_plan.activar("plan")
    permitido, motivo = modo_plan.puede_usar(tool)
    assert not permitido
    assert tool in motivo                          # el motivo nombra la tool
    assert "MODO PLAN" in motivo
    assert "hasta que el usuario apruebe" in motivo


@pytest.mark.parametrize("tool", [
    "leer_archivo", "listar", "buscar", "repo_map", "code_grafo",
    "git_estado", "git_diff", "git_log", "notas", "recordar", "responder",
])
def test_modo_plan_deja_pasar_las_de_lectura(tool):
    modo_plan.activar("plan")
    permitido, motivo = modo_plan.puede_usar(tool)
    assert permitido and motivo == ""


def test_danger_del_registry_bloquea_aunque_no_este_en_la_lista():
    # la fuente de verdad es el registry: una tool desconocida marcada
    # danger=True se bloquea igual
    modo_plan.activar("plan")
    permitido, _ = modo_plan.puede_usar("tool_rarisima_nueva", danger=True)
    assert not permitido
    assert modo_plan.es_de_escritura("tool_rarisima_nueva", danger=True)


def test_heuristico_por_verbo_para_tools_no_declaradas():
    assert modo_plan.es_de_escritura("subir_release")
    assert modo_plan.es_de_escritura("kg_agregar")
    assert not modo_plan.es_de_escritura("consultar_indice")


def test_git_de_lectura_permitido_y_git_desconocido_bloqueado():
    # git_estado/git_diff/git_log son las unicas git del registry y son de
    # lectura: bloquear 'git_*' entero seria falso. Un git_commit futuro NO.
    assert not modo_plan.es_de_escritura("git_estado")
    assert not modo_plan.es_de_escritura("git_log")
    assert modo_plan.es_de_escritura("git_commit")
    assert modo_plan.es_de_escritura("git_push")


def test_repo_a_prompt_lee_pero_con_salida_escribe():
    # con '| salida' llama a dev_tools.write_file() (pisa el archivo, deja .bak):
    # estaba en la allowlist de LECTURA y dejaba escribir en modo plan.
    modo_plan.activar("plan")
    ok_lee, _ = modo_plan.puede_usar("repo_a_prompt", args="C:/repos/algo")
    assert ok_lee, "leer un repo es lo que el investigador necesita"
    ok_lee2, _ = modo_plan.puede_usar("repo_a_prompt", args="C:/repos/algo |  ")
    assert ok_lee2, "un '|' sin salida tampoco escribe"
    ok_esc, motivo = modo_plan.puede_usar("repo_a_prompt",
                                          args="C:/repos/algo | spec.md")
    assert not ok_esc and "MODO PLAN" in motivo


@pytest.mark.parametrize("tool", [
    "voz_decir", "voz_clonar", "imagen_quitar_fondo", "musica_orquestar",
])
def test_optin_que_escriben_archivos_estan_bloqueadas(tool):
    # familias opt-in: sin verbo en el nombre y sin danger=True, se colaban
    modo_plan.activar("plan")
    permitido, _ = modo_plan.puede_usar(tool)
    assert not permitido, f"{tool} escribe archivos: no puede pasar en modo plan"


def test_las_optin_bloqueadas_existen_de_verdad():
    """La lista no es imaginaria: esos nombres los registra el codigo real.

    Se llama al register() de cada modulo opt-in con un decorador falso (no
    hace falta prender los flags ni importar tools.py con env). Si alguna se
    renombra o desaparece, este test cae y hay que revisar TOOLS_ESCRITURA.
    """
    from cognia.agent import voz_tools, image_tools, musica_tools
    from cognia.agent import repo_reverse_tool

    registradas = set()

    def tool_falso(nombre, doc, danger=False, desc="", params=None):
        registradas.add(nombre)
        return lambda fn: fn

    for mod in (voz_tools, image_tools, musica_tools, repo_reverse_tool):
        mod.register(tool_falso)

    for nombre in ("voz_decir", "voz_clonar", "imagen_quitar_fondo",
                   "musica_orquestar", "repo_a_prompt"):
        assert nombre in registradas, f"{nombre} ya no se registra asi"
        assert modo_plan.es_de_escritura(nombre, args="x | y"), \
            f"{nombre} escribe: modo_plan tiene que bloquearla"


def test_delegar_subtarea_depende_del_rol():
    modo_plan.activar("plan")
    ok_inv, _ = modo_plan.puede_usar("delegar_subtarea",
                                     args="investigador | leer el modulo X")
    assert ok_inv
    ok_impl, motivo = modo_plan.puede_usar("delegar_subtarea",
                                           args="implementador | escribir X")
    assert not ok_impl and "MODO PLAN" in motivo
    # sin args legibles: conservador
    assert modo_plan.es_de_escritura("delegar_subtarea", args="")


def test_nombre_vacio_se_bloquea():
    assert modo_plan.es_de_escritura("")
    assert modo_plan.es_de_escritura(None)


# ── plan pendiente / aprobacion ───────────────────────────────────────────────

def test_ciclo_completo_guardar_aprobar():
    modo_plan.activar("plan")
    assert modo_plan.plan_pendiente() is None
    modo_plan.guardar_plan("  1. leer tools.py\n2. escribir el modulo  ")
    assert modo_plan.plan_pendiente().startswith("1. leer tools.py")
    aprobado = modo_plan.aprobar_plan()
    assert "escribir el modulo" in aprobado         # el CLI lo inyecta de objetivo
    assert modo_plan.modo_actual() == "ejecutar"    # aprobar saca del modo plan
    assert modo_plan.plan_pendiente() is None
    # y ya no bloquea nada
    permitido, _ = modo_plan.puede_usar("escribir_archivo")
    assert permitido


def test_aprobar_sin_plan_no_cambia_el_modo():
    modo_plan.activar("plan")
    assert modo_plan.aprobar_plan() is None
    assert modo_plan.modo_actual() == "plan"


def test_guardar_plan_vacio_levanta():
    modo_plan.activar("plan")
    with pytest.raises(ValueError):
        modo_plan.guardar_plan("   \n  ")
    assert modo_plan.plan_pendiente() is None


def test_entrar_de_nuevo_en_plan_descarta_el_plan_viejo():
    modo_plan.activar("plan")
    modo_plan.guardar_plan("plan viejo")
    modo_plan.activar("ejecutar")
    assert modo_plan.plan_pendiente() == "plan viejo"   # salir no lo descarta
    modo_plan.activar("plan")
    assert modo_plan.plan_pendiente() is None           # re-entrar si


# ── system prompt ─────────────────────────────────────────────────────────────

def test_sufijo_system_solo_en_modo_plan():
    assert modo_plan.sufijo_system() == ""
    modo_plan.activar("plan")
    sufijo = modo_plan.sufijo_system()
    assert "MODO PLAN" in sufijo and "solo lectura" in sufijo
    assert "pasos numerados" in sufijo
    # explicito, sin depender del modo vigente
    assert modo_plan.sufijo_system("ejecutar") == ""
    assert modo_plan.sufijo_system("plan") == sufijo


def test_sufijo_system_modo_invalido_levanta():
    with pytest.raises(ValueError):
        modo_plan.sufijo_system("act")


# ── contraste contra el registry REAL (no una lista imaginada) ────────────────

def test_contra_el_registry_real():
    """Las tools que el registry marca danger=True se bloquean, y las de
    lectura declaradas existen de verdad (o son de otro modulo opt-in)."""
    from cognia.agent.tools import TOOLS

    modo_plan.activar("plan")
    peligrosas = [n for n, spec in TOOLS.items() if spec.get("danger")]
    assert peligrosas, "el registry deberia tener alguna tool danger=True"
    for nombre in peligrosas:
        permitido, _ = modo_plan.puede_usar(nombre, danger=True)
        assert not permitido, f"{nombre} (danger=True) deberia bloquearse"

    # las tools de escritura del catalogo CORE estan cubiertas por la lista base
    # aunque el registry NO las marque danger (escribir/editar/apendar no lo estan)
    for nombre in ("escribir_archivo", "editar_archivo", "apendar_archivo",
                   "ejecutar"):
        assert nombre in TOOLS, f"{nombre} deberia existir en el registry"
        permitido, _ = modo_plan.puede_usar(nombre,
                                            danger=TOOLS[nombre].get("danger", False))
        assert not permitido, f"{nombre} deberia bloquearse en modo plan"

    # y las git del registry son de lectura: siguen disponibles para investigar
    for nombre in ("git_estado", "git_diff", "git_log"):
        assert nombre in TOOLS
        permitido, _ = modo_plan.puede_usar(nombre,
                                            danger=TOOLS[nombre].get("danger", False))
        assert permitido, f"{nombre} es de lectura: no deberia bloquearse"
