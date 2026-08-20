# -*- coding: utf-8 -*-
"""La PUERTA del subsistema TX/LIBRO en el CLI (ESPEC 14.2, bloque M3).

QUE SE FIJA AQUI, y por que cada cosa:

1. Que los comandos EXISTEN donde el dueno los busca (`_CMD_DESCRIPTIONS` y
   `/ayuda`). La regla del repo: codigo sin puerta no esta entregado.
2. Que con COGNIA_TX apagado NO cambia NADA -- ni el registry de tools que ve
   el modelo, ni el import del paquete `cognia.tx`. Es la condicion que puso el
   dueno para todo el subsistema y es la que mas facil se rompe sola: basta un
   import al principio de un fichero.
3. Que `/tx mutar` aborta 3 de 3. Es la definicion-de-hecho (a) del MVP: un
   gate que nunca aborta aprueba cualquier cosa y desde fuera se ve identico a
   un sistema sano.
4. Que cada comando corre en su forma minima sin reventar y DICE algo -- el
   fallo tipico de este sistema es el vacio silencioso, no la excepcion.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PY = sys.executable

TOOLS_TX = ("libro_grep", "libro_ver", "decidir", "afirmar", "pendiente",
            "resolver", "leccion")


# =====================================================================
# fixtures
# =====================================================================

@pytest.fixture
def tx(tmp_path, monkeypatch):
    """Sesion TX aislada: el LIBRO va a tmp_path y el flag esta encendido."""
    monkeypatch.setenv("COGNIA_TX", "1")
    from cognia.tx import libro as almacen
    monkeypatch.setattr(almacen, "dir_tarea",
                        lambda task_id: str(tmp_path / str(task_id)))
    from cognia.tx import driver
    driver._SESION["s"] = None
    driver.desenganchar()
    yield driver
    driver._SESION["s"] = None
    driver.desenganchar()
    almacen.cerrar()


@pytest.fixture
def sembrada(tx, tmp_path):
    """Una tarea ya abierta, con criterio barato y una restriccion."""
    from cognia import cli
    cli._slash_tx('iniciar "objetivo de prueba" --criterio '
                  '"%s -c pass" --restriccion "no tocar loop.py" '
                  '--pasos 3 --horas 1' % PY)
    return tx


def _teclear(cli, capsys, linea):
    """Teclea `linea` como en el REPL y devuelve la salida REAL."""
    if linea.startswith("/tx"):
        cli._slash_tx(linea[len("/tx"):].strip())
    elif linea.startswith("/libro"):
        cli._slash_libro(linea[len("/libro"):].strip())
    else:
        raise AssertionError("linea que no es de este subsistema: " + linea)
    return capsys.readouterr().out


# =====================================================================
# 1. La puerta existe donde se la busca
# =====================================================================

def test_los_comandos_estan_en_cmd_descriptions():
    from cognia import cli
    for cmd in ("/tx", "/libro"):
        assert cmd in cli._CMD_DESCRIPTIONS, cmd
        assert cmd in cli.COMMANDS, cmd


def test_los_comandos_salen_en_ayuda():
    """/ayuda se genera de _CMD_DESCRIPTIONS: si no sale ahi, para el dueno el
    comando no existe."""
    from cognia import cli
    from cognia.harness import ayuda as ah
    texto = ah.todo(cli._CMD_DESCRIPTIONS, 100)
    assert "/tx" in texto
    assert "/libro" in texto
    # Y clasificados en un cajon de verdad, no en el de sobras.
    assert ah.clasificar("/tx", cli._CMD_DESCRIPTIONS["/tx"])
    assert ah.clasificar("/libro", cli._CMD_DESCRIPTIONS["/libro"])


def test_la_descripcion_nombra_los_subcomandos():
    """La descripcion es lo unico que ve el autocompletado: si no nombra los
    subcomandos, `/tx iniciar` es indescubrible."""
    from cognia import cli
    d = cli._CMD_DESCRIPTIONS["/tx"]
    for sub in ("iniciar", "estado", "probar", "commit", "ancho", "bandas",
                "mutar", "vram"):
        assert sub in d, sub
    d2 = cli._CMD_DESCRIPTIONS["/libro"]
    for sub in ("ver", "grep", "auditar", "restringir", "retractar", "fsck",
                "exportar"):
        assert sub in d2, sub


# =====================================================================
# 2. Con COGNIA_TX apagado, CERO cambio de comportamiento
# =====================================================================

def test_apagado_por_defecto(monkeypatch):
    from cognia import cli
    monkeypatch.delenv("COGNIA_TX", raising=False)
    monkeypatch.setattr(cli, "_load_config", lambda: {})
    assert cli._tx_activo() is False


def test_apagado_no_importa_el_paquete_tx(tmp_path):
    """El import PEREZOSO detras del flag. Sin esto, `cognia.tx` entra en el
    arranque del REPL de todo el mundo.

    EN SUBPROCESO, no borrando modulos de `sys.modules` en este: borrarlos hace
    que el siguiente import cree clases NUEVAS, y `pytest.raises(LibroCaido)`
    de otro fichero deja de casar con la excepcion que se lanza. Se paga un
    proceso para no dejar el interprete envenenado -- el mismo motivo por el
    que el registry se comprueba tambien fuera.
    """
    codigo = (
        "import sys\n"
        "from cognia import cli\n"
        "cli._load_config = lambda: {}\n"
        "cli._slash_tx('probar')\n"
        "print('TX_CARGADO=' + str(any(m.startswith('cognia.tx.driver')\n"
        "                              for m in sys.modules)))\n")
    env = dict(os.environ)
    env.pop("COGNIA_TX", None)
    # HOME aislado: el flag tambien sale de la config persistida (`tx.flag`),
    # y sin esto el test mediria si el dueno dejo `/tx on` puesto.
    env["HOME"] = env["USERPROFILE"] = str(tmp_path)
    r = subprocess.run([PY, "-c", codigo], capture_output=True, text=True,
                       env=env, cwd=str(ROOT), timeout=180)
    assert r.returncode == 0, r.stderr
    assert "apagado" in r.stdout.lower(), r.stdout
    assert "TX_CARGADO=False" in r.stdout, r.stdout


def test_apagado_el_registry_de_tools_no_cambia():
    """Las 7 tools del LIBRO NO se registran sin el flag: el catalogo que ve el
    modelo tiene que ser byte-identico al de antes de este subsistema.

    En subproceso a proposito: el registro pasa en el IMPORT del modulo, asi
    que un monkeypatch del env en este proceso llegaria tarde.
    """
    env = dict(os.environ)
    env.pop("COGNIA_TX", None)
    r = subprocess.run(
        [PY, "-c", "import cognia.agent.tools as t;"
                   "print(sorted(n for n in t.TOOLS if n in %r))" % (TOOLS_TX,)],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=180)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("[]"), r.stdout


def test_encendido_las_siete_tools_se_registran():
    env = dict(os.environ)
    env["COGNIA_TX"] = "1"
    r = subprocess.run(
        [PY, "-c", "import cognia.agent.tools as t;"
                   "print(sorted(n for n in t.TOOLS if n in %r))" % (TOOLS_TX,)],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=180)
    assert r.returncode == 0, r.stderr
    for nombre in TOOLS_TX:
        assert nombre in r.stdout, (nombre, r.stdout)


def test_una_tool_apagada_dice_que_falta_el_flag():
    """No "no existe": existe y esta APAGADA. Decir "no existe" hace concluir
    que Cognia no sabe hacerlo y manda al researcher a sintetizar duplicados."""
    from cognia.agent import tools as t
    assert t.flag_de_optin("decidir") == "COGNIA_TX"
    assert t.flag_de_optin("libro_grep") == "COGNIA_TX"


# =====================================================================
# 3. /tx mutar: la definicion-de-hecho (a) del MVP
# =====================================================================

def test_mutar_aborta_3_de_3(sembrada):
    r = sembrada.mutar()
    assert r["total"] == 3
    assert r["abortan"] == 3, [p["nombre"] for p in r["pruebas"] if not p["aborta"]]
    assert r["ok"] is True


def test_mutar_exige_ademas_que_el_gate_apruebe_lo_SANO(sembrada):
    """Un gate que suspende TAMBIEN la version sana no discrimina: aborta
    siempre, y eso es tan inutil como aprobar siempre."""
    r = sembrada.mutar()
    assert r["discriminan"] == 3
    for p in r["pruebas"]:
        assert p["sano"]["ok"] is True, (p["nombre"], p["sano"]["detalle"])


def test_mutar_no_toca_el_libro(sembrada):
    """Las mutaciones son copias en RAM. Si tocaran el LIBRO, el drill
    envenenaria la tarea que dice auditar."""
    antes = sembrada.activa()["libro"].leer()
    sha_p = [e for e in antes if e["banda"] == "P"]
    sembrada.mutar()
    despues = sembrada.activa()["libro"].leer()
    assert [e for e in despues if e["banda"] == "P"] == sha_p
    # Lo unico nuevo es la CONSTANCIA del drill, en banda E.
    nuevos = despues[len(antes):]
    assert nuevos and all(e["banda"] == "E" for e in nuevos)


def test_mutar_dice_EL_GATE_ESTA_ROTO_si_no_aborta(sembrada, monkeypatch, capsys):
    """El contrafactual: con el gate desarmado, el comando tiene que gritar.
    Un `/tx mutar` que solo sabe decir OK no vale para nada."""
    from cognia import cli
    from cognia.tx import gates
    monkeypatch.setattr(gates, "g1_banda_permanente",
                        lambda *a, **k: gates.veredicto("G1", True, "desarmado"))
    monkeypatch.setattr(gates, "g2_trazadores",
                        lambda *a, **k: gates.veredicto("G2", True, "desarmado"))
    monkeypatch.setattr(gates, "g3_artefactos",
                        lambda *a, **k: gates.veredicto("G3", True, "desarmado"))
    salida = _teclear(cli, capsys, "/tx mutar")
    assert "EL GATE ESTA ROTO" in salida
    assert "0/3" in salida


# =====================================================================
# 4. Cada comando en su forma minima
# =====================================================================

def test_tx_iniciar_minimo(tx, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys,
                      '/tx iniciar "objetivo minimo" --criterio "%s -c pass"' % PY)
    assert "TAREA TX ABIERTA" in salida
    assert "sha_P0" in salida
    assert tx.activa() is not None


def test_tx_iniciar_sin_criterio_se_NIEGA(tx, capsys):
    """PUERTA 1 (ESPEC 9.4). Sin criterio ejecutable, G5 no mide monotonia y la
    unica senal que no viene de un LLM no existe: no se arranca."""
    from cognia import cli
    salida = _teclear(cli, capsys, '/tx iniciar "objetivo sin criterio"')
    assert "criterio" in salida.lower()
    assert tx.activa() is None


def test_tx_iniciar_no_se_come_las_barras_de_windows(tx, capsys):
    """Con `posix=True` un token SIN comillas pierde las barras: 'C:\\Users\\x'
    llega como 'C:Usersx' (dentro de comillas si se salva). Una ruta de Windows
    sin comillas es lo que teclea cualquiera, y el fallo seria un workspace
    inexistente sin que nada diga por que."""
    from cognia import cli
    _teclear(cli, capsys,
             r'/tx iniciar "objetivo" --criterio "PYEXE -c pass" --workspace C:\Users\x'
             .replace("PYEXE", PY))
    ses = tx.activa()
    assert ses["workspace"] == r"C:\Users\x"
    assert ses["criterios"] == ["%s -c pass" % PY]


def test_tx_probar_corre_los_gates_sin_destruir(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx probar")
    for gate in ("G1", "G3", "G4", "G5", "G6"):
        assert gate in salida, gate
    # G2 y Q NO estan: se miden despues de destruir, sobre la respuesta.
    assert "G2 " not in salida
    assert sembrada.activa()["ciclo"] == 1


def test_tx_estado_panel(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx estado")
    assert "TAREA TX" in salida
    assert "sha_P0" in salida or "sha_p0" in salida.lower()
    assert "maquinaria" in salida
    assert "BANDAS" in salida


def test_tx_estado_sin_tarea_cae_al_diagnostico(tx, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx estado")
    assert "No hay tarea TX abierta" in salida
    assert "P0-1" in salida        # el panel de prerrequisitos sigue vivo


def test_tx_bandas(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx bandas")
    assert "BANDAS" in salida
    for banda in ("P", "T", "N", "D", "F", "A", "E", "Q"):
        assert ("\n  %s " % banda) in salida, banda


def test_tx_ancho_no_destruye_y_se_cuenta(sembrada, capsys):
    from cognia import cli
    _teclear(cli, capsys, "/tx ancho")
    salida = _teclear(cli, capsys, "/tx commit")
    assert "ANCHO" in salida
    salud = sembrada.activa()["salud"]
    assert salud["anchos"] == 1 and salud["anchos_seguidos"] == 1
    assert sembrada.activa()["history"] is None      # nada se destruyo


def test_tx_commit_verde_destruye_y_mide_Q(sembrada, monkeypatch, capsys):
    """El camino HECHO entero: gates verdes -> destruir -> Q1..Q3 + G2 sobre la
    respuesta de la sesion NUEVA."""
    from cognia import cli
    from cognia.tx import gates
    ses = sembrada.activa()
    # G6 exige un evento MEDIDO en el ciclo: se anota uno como lo haria una
    # tool real (origen medido == hubo exit code entero de verdad).
    ses["libro"].append({
        "t": "comando", "op": "add", "banda": "F", "quien": "harness",
        "origen": "medido", "clave": "cmd:pytest -q", "valor": 0,
        "texto": "la suite del area paso", "estado": "verificado",
        "prov": {"tipo": "ejecutada", "cmd": "pytest", "exit_code": 0},
    }, ciclo=ses["ciclo"])

    def lector_perfecto(texto):
        pregs = gates.preguntas_de_control(ses["libro"].leer())
        return ("\n".join(str(p["esperado"]) for p in pregs) + "\n"
                + " ".join(t["texto"] for t in ses["estado_canal"]["trazadores"]))
    monkeypatch.setattr(sembrada, "responder_por_defecto",
                        lambda *a, **k: lector_perfecto)
    salida = _teclear(cli, capsys, "/tx commit")
    assert "COMMIT" in salida and "Q 3/3" in salida
    assert ses["history"] is not None and len(ses["history"]) == 2
    assert sembrada.activa()["ciclo"] == 2


def test_tx_vram_sin_verificar_solo_lee(sembrada, monkeypatch, capsys):
    from cognia import cli
    monkeypatch.setattr(sembrada, "leer_vram",
                        lambda: ({"usada": 1000, "total": 2000, "gpu": "FALSA"}, ""))
    salida = _teclear(cli, capsys, "/tx vram")
    assert "VRAM" in salida and "FALSA" in salida
    assert "--verificar" in salida


def test_tx_vram_verificar_mide_el_delta(sembrada, monkeypatch, capsys):
    """El axioma medido: el KV se reserva ENTERO al cargar. Destruir la ventana
    no devuelve un MiB, y este comando existe para COMPROBARLO."""
    from cognia import cli
    monkeypatch.setattr(sembrada, "leer_vram",
                        lambda: ({"usada": 12534, "total": 16311, "gpu": "F"}, ""))
    salida = _teclear(cli, capsys, "/tx vram --verificar")
    assert "delta +0.0 %" in salida


def test_tx_vram_sin_gpu_lo_dice(sembrada, monkeypatch, capsys):
    from cognia import cli
    monkeypatch.setattr(sembrada, "leer_vram", lambda: (None, "sin driver"))
    salida = _teclear(cli, capsys, "/tx vram --verificar")
    assert "sin driver" in salida


def test_tx_cerrar_y_reanudar(sembrada, capsys):
    from cognia import cli
    task_id = sembrada.activa()["task_id"]
    ciclo = sembrada.activa()["ciclo"]
    salida = _teclear(cli, capsys, "/tx cerrar")
    assert "cerrada" in salida
    assert sembrada.activa() is None
    salida = _teclear(cli, capsys, "/tx reanudar " + task_id)
    assert "reanudada" in salida
    assert sembrada.activa()["ciclo"] == ciclo


def test_tx_subcomando_desconocido_no_revienta(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx pajaritos")
    assert "No conozco" in salida


# --------------------------------------------------------------- /libro

def test_libro_listado(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/libro 20")
    assert "LIBRO" in salida
    assert "objetivo" in salida and "trazador" in salida


def test_libro_ver(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/libro ver 1 --contexto 2")
    assert "evento n=1" in salida
    assert "vecinos" in salida


def test_libro_grep(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/libro grep loop.py")
    assert "hits" in salida
    salida = _teclear(cli, capsys, "/libro grep zzz-no-existe")
    assert "0 de" in salida       # el vacio se DICE, no se calla


def test_libro_auditar_dice_si_la_cadena_termina_en_medido(sembrada, capsys):
    from cognia import cli
    from cognia.tx import tools as T
    T._pendiente("algo que dijo el modelo")
    n = sembrada.activa()["libro"].leer()[-1]["n"]
    salida = _teclear(cli, capsys, "/libro auditar %d" % n)
    assert "AUDITORIA" in salida
    assert "NO son" in salida     # hoja origen=modelo: no la sostiene un exit


def test_libro_restringir_mueve_el_sha_p0(sembrada, capsys):
    """La banda P solo la toca el HUMANO, y la referencia de G1 se mueve con
    ella: si no, G1 abortaria para siempre por un cambio autorizado."""
    from cognia import cli
    viejo = sembrada.activa()["sha_p0"]
    salida = _teclear(cli, capsys, '/libro restringir "no publicar sin firma"')
    assert "Restriccion anadida" in salida
    nuevo = sembrada.activa()["sha_p0"]
    assert nuevo != viejo
    salida = _teclear(cli, capsys, "/tx probar")
    assert "PASA  G1" in salida


def test_libro_restringir_no_pisa_una_restriccion_anterior(sembrada):
    """El id sale del MAXIMO usado: contando las vivas, tras un retractar el id
    nuevo pisaria uno viejo y el fold lo RESUCITARIA con otro texto."""
    from cognia import cli
    from cognia.tx import bandas
    libro = sembrada.activa()["libro"]
    cli._slash_libro('restringir "segunda restriccion"')
    ids = [e["id"] for e in libro.leer()
           if e["banda"] == "P" and e["t"] == "restriccion"]
    assert len(ids) == len(set(ids))
    texto = bandas.render_banda_permanente(libro.leer())
    assert "no tocar loop.py" in texto and "segunda restriccion" in texto


def test_libro_retractar_invalida_sin_borrar(sembrada, capsys):
    from cognia import cli
    libro = sembrada.activa()["libro"]
    antes = len(libro.leer())
    salida = _teclear(cli, capsys, '/libro retractar 2 "ya no aplica"')
    assert "INVALIDADO" in salida
    despues = libro.leer()
    assert len(despues) == antes + 1        # append-only: nada se borro
    assert any(e["op"] == "invalidate" for e in despues)


def test_libro_fsck_ok(sembrada, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/libro fsck")
    assert "FSCK OK" in salida


def test_libro_fsck_detecta_la_cola_cortada(sembrada, capsys):
    """Un proceso matado a mitad de un append. `fsck` tiene que verlo y
    `--reparar` recortar SOLO la cola."""
    from cognia import cli
    ruta = sembrada.activa()["libro"].ruta
    with open(ruta, "ab") as fh:
        fh.write(b'{"t":"hecho","op":"add"')     # sin cerrar
    salida = _teclear(cli, capsys, "/libro fsck")
    assert "CORRUPTO" in salida
    salida = _teclear(cli, capsys, "/libro fsck --reparar")
    assert "Reparado" in salida
    salida = _teclear(cli, capsys, "/libro fsck")
    assert "FSCK OK" in salida


def test_libro_exportar(sembrada, tmp_path, capsys):
    from cognia import cli
    destino = tmp_path / "export.jsonl"
    salida = _teclear(cli, capsys, "/libro exportar " + str(destino))
    assert "exportado" in salida
    assert destino.exists() and destino.read_text(encoding="utf-8").count("\n") >= 8


def test_libro_sin_tarea_lo_dice(tx, capsys):
    from cognia import cli
    salida = _teclear(cli, capsys, "/libro 20")
    assert "No hay tarea TX abierta" in salida


# =====================================================================
# 5. Las tools que ve el modelo: cada rechazo
# =====================================================================

def test_leccion_rechaza_la_forma_negativa(sembrada):
    from cognia.tx import tools as T
    r = T._leccion("no uses pickle nunca")
    assert r.startswith("ERROR") and "NEGATIVA" in r
    r = T._leccion("serializar con json.dumps")
    assert not r.startswith("ERROR")


def test_leccion_rechaza_la_negativa_con_tilde(sembrada):
    """El texto se normaliza sin diacriticos antes de mirar: 'jamas' con tilde
    se colaba entera."""
    from cognia.tx import tools as T
    # El escape y no el caracter: el codigo del repo es ASCII puro, y lo que
    # se prueba es que el NORMALIZADOR ve la tilde, no que el fichero la tenga.
    assert T._leccion("jam\u00e1s tocar el fichero de config").startswith("ERROR")


def test_decidir_rechaza_sin_base_medida(sembrada):
    from cognia.tx import tools as T
    assert T._decidir("usar json").startswith("ERROR")
    assert T._decidir("usar json | 9999").startswith("ERROR")
    r = T._decidir("usar json | 1")          # n=1 es el objetivo, origen=usuario
    assert not r.startswith("ERROR") and "hipotesis" in r


def test_decidir_rechaza_una_base_que_solo_dijo_el_modelo(sembrada):
    from cognia.tx import tools as T
    T._pendiente("una frase del modelo")
    n = sembrada.activa()["libro"].leer()[-1]["n"]
    r = T._decidir("decision floja | %d" % n)
    assert r.startswith("ERROR") and "MEDIDA" in r


def test_afirmar_rechaza_el_verificador_nulo(sembrada):
    from cognia.tx import tools as T
    r = T._afirmar("la tierra es plana | echo ok | exit==0")
    assert r.startswith("ERROR") and "NULO" in r


def test_afirmar_con_verificador_real_asciende_a_medido(sembrada, monkeypatch):
    from cognia.tx import tools as T
    from cognia.agent import tools as at
    monkeypatch.setattr(at, "_shell",
                        lambda cmd, ctx, **kw: ctx.__setitem__("_exit", 0) or "ok")
    cmd = "pytest -q tests/test_tx_libro.py"
    # CONTROL NEGATIVO (ESPEC 1.1, componente VERIFICADOR): un verificador que
    # en este LIBRO nunca dio !=0 no ha demostrado que PUEDA fallar, y su
    # exit 0 no distingue el hecho de cualquier otra frase. `VERIFICADORES_NULOS`
    # solo caza doce formas literales: 'python --version' o 'git status' no
    # estan, dan 0 siempre, y ascendian cualquier mentira a la banda F -- que
    # es PERSISTENTE y sobrevive a todos los resets.
    r0 = T._afirmar("los tests pasan | %s | exit==0" % cmd)
    assert "NO ASCIENDE" in r0
    monkeypatch.setattr(at, "_shell",
                        lambda c, ctx, **kw: ctx.__setitem__("_exit", 1) or "1 failed")
    T._afirmar("los tests pasan | %s | exit==0" % cmd)   # queda su fallo
    monkeypatch.setattr(at, "_shell",
                        lambda c, ctx, **kw: ctx.__setitem__("_exit", 0) or "ok")
    r = T._afirmar("los tests pasan | %s | exit==0" % cmd)
    assert "VERIFICADO" in r
    ev = sembrada.activa()["libro"].leer()[-1]
    assert ev["banda"] == "F" and ev["origen"] == "medido" and ev["valor"] == 0


def test_afirmar_distingue_bloqueado_de_fallido(sembrada, monkeypatch):
    """exit None NO es exit!=0: el comando no llego a correr. Confundirlos hace
    que el modelo concluya que su hecho es falso cuando nadie lo midio."""
    from cognia.tx import tools as T
    from cognia.agent import tools as at
    monkeypatch.setattr(at, "_shell",
                        lambda cmd, ctx, **kw: ctx.__setitem__("_exit", None) or "BLOQUEADO")
    r = T._afirmar("algo | comando-bloqueado | exit==0")
    assert "NO LLEGO A EJECUTARSE" in r
    monkeypatch.setattr(at, "_shell",
                        lambda cmd, ctx, **kw: ctx.__setitem__("_exit", 3) or "fallo")
    r = T._afirmar("algo | comando-que-falla | exit==0")
    assert "exit=3" in r and "NO LLEGO" not in r


def test_las_tools_sin_tarea_dicen_cual_falta(tx):
    from cognia.tx import tools as T
    r = T._libro_grep("lo que sea")
    assert r.startswith("ERROR") and "no hay tarea" in r.lower()


def test_las_tools_apagadas_dicen_que_esta_apagado(monkeypatch):
    from cognia.tx import tools as T
    monkeypatch.delenv("COGNIA_TX", raising=False)
    r = T._leccion("hacer algo positivo")
    assert r.startswith("ERROR") and "apagado" in r


# =====================================================================
# 6. La linea por ciclo
# =====================================================================

def test_la_linea_del_ciclo_tiene_la_forma_de_la_espec(sembrada, monkeypatch):
    from cognia.tx import gates
    ses = sembrada.activa()
    ses["libro"].append({
        "t": "comando", "op": "add", "banda": "F", "quien": "harness",
        "origen": "medido", "clave": "cmd:pytest -q", "valor": 0,
        "texto": "medido", "estado": "verificado",
        "prov": {"tipo": "ejecutada", "cmd": "pytest", "exit_code": 0},
    }, ciclo=ses["ciclo"])

    def lector(texto):
        pregs = gates.preguntas_de_control(ses["libro"].leer())
        return ("\n".join(str(p["esperado"]) for p in pregs) + "\n"
                + " ".join(t["texto"] for t in ses["estado_canal"]["trazadores"]))
    res = sembrada.commit_ya(responder=lector)
    linea = res["linea"]
    assert linea.startswith("[TX] c1 COMMIT TX-0001 ok")
    for pieza in ("P ", "trz ", "art ", "Q 3/3", "crit ", "maq ", "ctx "):
        assert pieza in linea, (pieza, linea)


def test_sin_medidor_de_ventana_se_DICE(sembrada):
    """Lo que no se puede medir se dice; no se rellena con un numero
    plausible."""
    res = sembrada.commit_ya(responder=lambda t: "")
    assert "ctx sin-medidor" in res["linea"]
    sembrada.marcar_ventana(3500)
    sembrada.marcar_ventana(11800)
    res = sembrada.commit_ya(responder=lambda t: "")
    assert "ctx 3,5k->11,8k" in res["linea"]


def test_g5_sin_criterios_ejecutados_no_se_muestra_como_aprobado(sembrada, capsys):
    """El caso que aparecio TECLEANDO: con `solo_baratos=True`, un criterio caro
    (un pytest de 6 s) se salta desde la segunda medida, y si TODOS son caros
    G5 queda VERDE con total=0.

    El gate es de M2 y no se toca desde la puerta, pero la puerta no puede
    ensenarlo como un aprobado limpio: "no midio" y "midio y paso" son
    exactamente los dos estados que este subsistema existe para no confundir.
    """
    from cognia import cli
    contrato = sembrada.activa()["contrato"]
    contrato.coste_ms = {0: 999999}          # el criterio ya se midio: es caro
    salida = _teclear(cli, capsys, "/tx probar")
    assert "PASA  G5" in salida
    # Con el criterio ya medido como caro, G5 lo ARRASTRA (no lo tira) y la
    # puerta dice que no se midio AHORA: "1/1 medido" y "1/1 heredado" no
    # significan lo mismo, y el numero solo no los distingue.
    assert "sin reejecutarlos" in salida


# =====================================================================
# REGRESION 2026-08-19 -- lo que salio TECLEANDOLO
# =====================================================================

def test_una_comilla_sin_cerrar_no_mata_el_REPL(sembrada, capsys):
    """`_tx_partir` usa shlex y lanzaba `ValueError: No closing quotation`
    FUERA de todo try. El dispatch de `repl()` esta en el cuerpo pelado de su
    `while True:` y nadie envuelve `repl()`: eso era el fin de la sesion -- la
    conversacion, el modelo cargado y la sesion TX (que es estado de proceso)
    -- por olvidarse una comilla en el comando cuyo propio mensaje de ayuda le
    pide comillas."""
    from cognia import cli
    capsys.readouterr()
    salida = _teclear(cli, capsys, '/tx iniciar "arreglar el bug del canal')
    assert "comilla" in salida
    assert "Ejemplo:" in salida
    salida2 = _teclear(cli, capsys, '/libro grep "sin cerrar')
    assert "comilla" in salida2


def test_un_criterio_sin_comillas_no_se_trunca_al_primer_token():
    """Reproducido con el comando de ejemplo de la propia ESPEC sin comillas:
    objetivo -> 'arreglar el canal -m pytest tests/estado -q' y criterio ->
    'venv312\\Scripts\\python.exe'. Las dos cosas se sellan en la banda P con
    conf 1,00 y en el sha_P0, que ya no se puede tocar; y ese criterio da
    exit 0 SIEMPRE, asi que la unica senal del sistema que no viene de un LLM
    quedaba falseada para el resto de la tarea."""
    from cognia import cli
    libres, flags = cli._tx_flags(cli._tx_partir(
        r'"arreglar el canal" --criterio venv312\Scripts\python.exe -m pytest '
        r'tests/estado -q --pasos 8'))
    assert " ".join(libres) == "arreglar el canal"
    assert flags["criterio"] == [
        r"venv312\Scripts\python.exe -m pytest tests/estado -q"]
    assert flags["pasos"] == ["8"]


def test_dos_criterios_siguen_acumulando():
    """Un flag repetido ACUMULA: --criterio dos veces son dos criterios."""
    from cognia import cli
    _libres, flags = cli._tx_flags(cli._tx_partir(
        '"obj" --criterio "a b" --criterio "c d"'))
    assert flags["criterio"] == ["a b", "c d"]


def test_tx_pelado_lista_los_subcomandos(tx, capsys):
    """La rama de ayuda imprimia la lista solo `if sub:`, o sea NUNCA para
    `/tx` pelado -- que es lo primero que teclea cualquiera."""
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx")
    assert "Subcomandos:" in salida
    for sub in ("iniciar", "reanudar", "diagnostico", "mutar"):
        assert sub in salida, sub
    assert "/libro" in salida


def test_la_ayuda_a_80_columnas_no_corta_la_frase():
    """El test viejo comprobaba el STRING del dict y pasaba en verde mientras
    el dueno veia 'Agente de horizonte largo (TX): iniciar|estado|pr...'. Lo
    que hay que asertar es lo que se RENDERIZA."""
    from cognia import cli
    from cognia.harness import ayuda as ah
    for ancho in (80, 100, 120):
        texto = ah.todo(cli._CMD_DESCRIPTIONS, ancho)
        linea = [l for l in texto.splitlines() if l.strip().startswith("/tx ")]
        assert linea, ancho
        assert "..." not in linea[0] and "\u2026" not in linea[0], (ancho, linea[0])


def test_tx_y_libro_tienen_ayuda_larga():
    """30 comandos estan en `_CMD_DETAILS` y el subsistema con MAS subcomandos
    del CLI (12 + 7) no estaba: no habia ningun sitio donde leerlos enteros."""
    from cognia import cli
    for cmd in ("/tx", "/libro"):
        assert cmd in cli._CMD_DETAILS, cmd
    assert "reanudar" in cli._CMD_DETAILS["/tx"]
    assert "huerfanos" in cli._CMD_DETAILS["/libro"]


def test_sin_sesion_el_estado_nombra_reanudar(tx, capsys, monkeypatch):
    """`_SESION` es estado de proceso: al reabrir el REPL no hay tarea viva
    aunque el LIBRO siga en disco. Sin esta linea el unico camino visible era
    abrir OTRA tarea, con otro task_id y otro LIBRO -- en un sistema cuya
    premisa entera es sobrevivir a los resets."""
    from cognia import cli
    monkeypatch.setattr(cli, "_load_config",
                        lambda: {"tx_tarea": "tx-20260819-160447"})
    salida = _teclear(cli, capsys, "/tx estado")
    assert "/tx reanudar" in salida
    assert "tx-20260819-160447" in salida


def test_el_commit_no_repite_el_detalle(sembrada, capsys):
    """`linea_ciclo` ya pega el detalle al final cuando la salida no es HECHO;
    el CLI lo imprimia otra vez debajo. La linea del ciclo repetia literalmente
    su mitad mas larga."""
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx commit")
    cuerpo = " ".join(salida.split())
    # La frase del detalle salia DOS VECES SEGUIDAS: una pegada al final de la
    # linea del ciclo y otra como linea suelta debajo. (Que el motivo aparezca
    # ademas en la tabla de gates es otra cosa: ahi va por gate, y la linea del
    # ciclo es lo que se guarda en el historial de `/tx estado`, donde no hay
    # tabla.)
    assert cuerpo.count("no reseteo, sigo en la misma ventana") == 1, cuerpo


def test_el_ejemplo_de_iniciar_sobrevive_al_modo_sencillo(tx, capsys):
    """`simple_mode.should_show_detail` suprime la LINEA ENTERA que contenga
    [detail], y el modo sencillo es el DEFECTO: el dueno que se equivocaba
    recibia una negativa que cita una seccion de un documento que no tiene
    delante y ni un solo ejemplo de la sintaxis correcta."""
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx iniciar arreglar el canal de estado")
    assert "Ejemplo:" in salida
    assert "--criterio" in salida


def test_iniciar_mide_el_criterio_antes_de_sellar_la_banda_P(tx, capsys):
    """Nada validaba jamas que el criterio fuese EJECUTABLE, y la banda P se
    sella con el sha_P0 y ya no se toca. La secuencia del DIA 1 de la ESPEC
    sembraba `pytest tests/estado`, un path que NO EXISTE, y G5 lo dio por PASA
    tras tirar 5,5 s sin decir que el path no estaba ni que el exit fue 4."""
    from cognia import cli
    _teclear(cli, capsys,
             '/tx iniciar "objetivo" --criterio "%s -c raise_SystemExit" '
             '--pasos 3' % PY)
    ses = tx.activa()
    assert ses is not None
    assert ses["siembra"]["ejecutados"] == 1
    assert ses["siembra"]["verdes"] == 0


def test_iniciar_avisa_si_el_criterio_ya_esta_verde(tx, capsys):
    """Un criterio que ya pasa ANTES de empezar no puede medir progreso: G5 no
    vera avanzar nada por ese lado, y eso hay que decirlo al sembrar."""
    from cognia import cli
    salida = _teclear(cli, capsys,
                      '/tx iniciar "obj" --criterio "%s -c pass"' % PY)
    assert "al sembrar" in salida
    assert "YA esta verde" in salida


def test_el_panel_dice_que_el_disparador_no_esta_cableado(sembrada, capsys):
    """`--pasos N` ofrecia un presupuesto que nada consumia: `driver.paso()` no
    lo llamaba nadie (grep: solo el experimento e0) y `/tx estado` ensenaba
    '(0/N pasos)' congelado para siempre. Ahora el contador se mueve con cada
    tool y el panel dice que el commit es manual."""
    from cognia import cli
    salida = _teclear(cli, capsys, "/tx estado")
    assert "disparador automatico: NO cableado" in salida


def test_los_pasos_se_cuentan_con_cada_tool(sembrada):
    """El contador lo lleva el enganche de `registrar_tool`, que corre en TODAS
    las llamadas a tool con TX encendido."""
    from cognia.harness import interceptor
    ses = sembrada.activa()
    antes = ses["pasos_del_ciclo"]
    interceptor.despues("ejecutar", "echo hola", {}, "RESULTADO (exit 0)", True,
                        exit_code=0)
    assert ses["pasos_del_ciclo"] == antes + 1


def test_probar_en_verde_dice_que_el_reset_no_esta_cableado(sembrada, capsys,
                                                            monkeypatch):
    """`destruir_por_defecto` escribe `ses['history']`, y un grep confirma que
    ese campo no lo lee NADIE: la conversacion del REPL sigue intacta. El
    mensaje VERDE afirmaba un efecto que no ocurre."""
    from cognia import cli
    from cognia.tx import commit as C
    monkeypatch.setattr(C, "preparar", lambda ctx, topes=None: {
        "proyeccion": "p", "eventos": [], "informe": {"tokens": 1},
        "gates": [], "fallos": [], "abre": True, "ms_proy": 0, "ms_gates": 0,
        "fuzzy": None, "p_desborda": False, "p_tokens": 1, "diag": {}})
    salida = _teclear(cli, capsys, "/tx probar")
    assert "VERDE" in salida
    assert "NO esta cableado al bucle" in salida


def test_el_flag_es_UNO_solo_para_los_cuatro_lectores(monkeypatch, tmp_path):
    """Habia CUATRO lecturas del mismo flag y no coincidian: `cli._tx_activo` y
    `driver.activo` leian env O config; `agent.tools` (registro de las 7 tools)
    y `harness.interceptor._libro` (la escritura en el LIBRO) leian SOLO el env.
    Medido: con `tx_activo=true` guardado y sin la variable puesta, `/tx estado`
    decia ACTIVO, `/tx iniciar` abria la tarea y una llamada real a run_tool
    dejaba el libro en los mismos 7 eventos de la siembra, sin un solo aviso."""
    from cognia.tx import flag
    from cognia.harness import interceptor
    monkeypatch.delenv("COGNIA_TX", raising=False)
    cfg = tmp_path / ".cognia_config.json"
    cfg.write_text('{"tx_activo": true}', encoding="utf-8")
    monkeypatch.setattr(flag, "ruta_config", lambda: cfg)
    flag.olvidar_cache()
    assert flag.activo() is True
    # Y PROPAGA: los otros tres lectores ven lo mismo a partir de aqui.
    assert os.environ.get("COGNIA_TX") == "1"
    assert interceptor._tx_encendido() is True
    flag.olvidar_cache()


def test_tx_on_registra_las_siete_tools_en_caliente(tx, capsys, monkeypatch):
    """El registro va en el IMPORT de `cognia.agent.tools`, que ya ocurrio
    antes de que el REPL acepte la primera tecla. Reproducido: tras `/tx on`
    `run_tool('libro_grep', ...)` contestaba "'libro_grep' no existe" -- justo
    el mensaje que el comentario de `_OPTIN_NOMBRES` dice haber eliminado, y el
    que manda al background researcher a sintetizar duplicados."""
    from cognia import cli
    from cognia.agent import tools as at
    # El registry es GLOBAL del proceso: hay que devolverlo como estaba o el
    # siguiente fichero de tests ve 7 tools de mas (`test_wp2_tools` asserta
    # que el catalogo por defecto es CORE_TOOLS y nada mas).
    previas = {n: at.TOOLS[n] for n in TOOLS_TX if n in at.TOOLS}
    for nombre in TOOLS_TX:
        at.TOOLS.pop(nombre, None)
    monkeypatch.setattr(cli, "_save_config", lambda cfg: None)
    monkeypatch.setattr(cli, "_load_config", lambda: {})
    try:
        salida = _teclear(cli, capsys, "/tx on")
        assert "tools del LIBRO" in salida
        for nombre in TOOLS_TX:
            assert nombre in at.TOOLS, nombre
    finally:
        for nombre in TOOLS_TX:
            at.TOOLS.pop(nombre, None)
        at.TOOLS.update(previas)
        from cognia.tx import flag
        flag.olvidar_cache()
