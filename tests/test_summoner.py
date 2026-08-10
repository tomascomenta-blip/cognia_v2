"""
tests/test_summoner.py
======================
Tests del summoner SIN GPU, sin red y sin procesos reales: todo por
monkeypatch de las seams (_salud, _lanzar, _pid_vivo, vram_mib, reloj).

POR QUE tanto fake: hay una medicion GPU en curso y el contrato del summoner
es justamente orquestar procesos pesados -- lo testeable en CPU es la LOGICA
(planes de eviccion, estado, postchecks, ordenes de llamada), que es donde
vivieron los bugs historicos (taskkill /IM global, caches rancios, doble
lanzamiento sobre 503).
"""
from __future__ import annotations

import json
import sys

import pytest

from cognia import summoner as S
from cognia.ux import events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Estado en tmp, reloj congelado en t=1000, sin sleeps reales."""
    monkeypatch.setenv("COGNIA_SUMMONER_STATE", str(tmp_path / "summoner.json"))
    monkeypatch.setattr(S, "_ahora", lambda: 1000.0)
    monkeypatch.setattr(S, "_dormir", lambda s: None)
    return tmp_path


@pytest.fixture
def bus():
    caja = []
    events.suscribir(caja.append)
    yield caja
    events.desuscribir(caja.append)


@pytest.fixture
def invalidadores(monkeypatch):
    """Contadores sobre los 3 caches que mienten; verifican forzar=True."""
    from cognia import backend_activo, llm_local
    from cognia.agent import model_profiles
    reg = {"reset": 0, "detectar": [], "perfil": []}
    monkeypatch.setattr(backend_activo, "resetear_cache",
                        lambda: reg.__setitem__("reset", reg["reset"] + 1))
    monkeypatch.setattr(llm_local, "detectar_backend",
                        lambda forzar=False: reg["detectar"].append(forzar))
    monkeypatch.setattr(model_profiles, "perfil_del_agente",
                        lambda url="", forzar=False: reg["perfil"].append(forzar))
    return reg


def _sembrar(rol, **entrada):
    estado = S._leer_estado()
    estado["roles"][rol] = entrada
    S._guardar_estado(estado)


# ---------------------------------------------------------------------------
# 1. Registry
# ---------------------------------------------------------------------------

def test_registry_roles_exactos():
    assert set(S.ROLES) == {"cerebro", "vlm", "imagen", "tresd", "voces", "musica"}
    assert "stt" not in S.ROLES and "hablar" not in S.ROLES
    assert S.ROLES["cerebro"]["idle_s"] is None
    puertos = [spec["puerto"] for spec in S.ROLES.values()]
    assert len(puertos) == len(set(puertos)), "puertos duplicados"


def test_registry_anti_colision_oficina():
    """C3 del plan: la oficina (identidad.py) usa 8088/8090/8092; los roles
    nuevos van en 8096-8099. Un choque aqui mata un servicio ajeno."""
    oficina = {8088, 8090, 8092}
    for rol in ("imagen", "tresd", "voces", "musica"):
        p = S.ROLES[rol]["puerto"]
        assert p in {8096, 8097, 8098, 8099}, f"{rol} fuera de rango: {p}"
        assert p not in oficina | {8080, 8081}, f"{rol} colisiona: {p}"
    assert S.ROLES["cerebro"]["puerto"] == 8080
    assert S.ROLES["vlm"]["puerto"] == 8081


def test_registry_tipos():
    assert S.ROLES["imagen"]["tipo"] == "job"
    for rol in ("tresd", "voces", "musica"):
        assert S.ROLES[rol]["tipo"] == "presupuesto"
        assert "worker" not in S.ROLES[rol]


def test_escalera_solo_celdas_medidas():
    assert [c["n_ctx"] for c in S.ESCALERA_CTX] == [
        32768, 200192, 262144, 524288, 786432, 1010176]
    assert all(c["cache"] in ("f16", "q8_0", "q4_0")
               for c in S.ESCALERA_CTX)


# ---------------------------------------------------------------------------
# 2. _plan_eviccion (pura)
# ---------------------------------------------------------------------------

def test_plan_vacio_si_cabe():
    assert S._plan_eviccion(10000, 3000, {"vlm": {"ultima": 999}}) == []


def test_plan_job_idle_vencido_primero():
    vivos = {"vlm": {"ultima": 999}, "imagen": {"ultima": 100}}
    plan = S._plan_eviccion(0, 5000, vivos, ahora=1000.0)
    assert plan[0] == "imagen"          # idle 300 vencido (900s sin uso)
    assert plan == ["imagen"]           # 12000 MiB ya cubren


def test_plan_cerebro_solo_con_permiso():
    vivos = {"cerebro": {"ultima": 999}}
    assert S._plan_eviccion(0, 5000, vivos) == []
    assert S._plan_eviccion(0, 5000, vivos, permitir_cerebro=True) == ["cerebro"]


def test_plan_insuficiente_senalado():
    """El plan devuelve todo lo evictable; el caller recomputa cobertura y
    debe fallar visible (asi lo hace ensure -- test de ensure aparte)."""
    vivos = {"vlm": {"ultima": 999}}
    plan = S._plan_eviccion(0, 14000, vivos)
    assert plan == ["vlm"]
    assert 0 + S._vram_de_plan(plan) < 14000 + 512   # deficit detectable


def test_plan_reserva_presupuesto_primero():
    vivos = {"vlm": {"ultima": 999},
             "voces": {"ultima": 999, "reserva": True}}
    plan = S._plan_eviccion(100, 3000, vivos, ahora=1000.0)
    assert plan[0] == "voces"           # borrar una reserva no mata nada


# ---------------------------------------------------------------------------
# 3. _pad256 / _celda_para (puras)
# ---------------------------------------------------------------------------

def test_pad256():
    assert S._pad256(200000) == 200192
    assert S._pad256(32768) == 32768
    assert S._pad256(1) == 256


def test_celda_para():
    assert S._celda_para(32768, S.ESCALERA_CTX)["n_ctx"] == 32768
    assert S._celda_para(50000, S.ESCALERA_CTX)["n_ctx"] == 200192
    assert S._celda_para(300000, S.ESCALERA_CTX)["n_ctx"] == 524288
    assert S._celda_para(2_000_000, S.ESCALERA_CTX) is None
    # con cache explicito devuelve la celda mas chica DE ESE cache
    assert S._celda_para(50000, S.ESCALERA_CTX, cache="q8_0")["n_ctx"] == 262144
    assert S._celda_para(50000, S.ESCALERA_CTX, cache="q5_1") is None


# ---------------------------------------------------------------------------
# 4. Estado
# ---------------------------------------------------------------------------

def test_estado_round_trip(sandbox):
    estado = {"version": 1, "roles": {"vlm": {"pid": 7, "puerto": 8081,
                                              "t_ultima": 5.0}}}
    S._guardar_estado(estado)
    assert S._leer_estado() == estado


def test_estado_corrupto_arranca_limpio(sandbox, capsys):
    S._ruta_estado().write_text("{no es json", encoding="utf-8")
    assert S._leer_estado() == {"version": 1, "roles": {}}
    assert "estado" in capsys.readouterr().err


def test_tocar_actualiza_t_ultima(sandbox, monkeypatch):
    _sembrar("vlm", pid=7, puerto=8081, t_ultima=1.0)
    monkeypatch.setattr(S, "_ahora", lambda: 5555.0)
    S.tocar("vlm")
    assert S._leer_estado()["roles"]["vlm"]["t_ultima"] == 5555.0


def test_vivos_poda_pid_muerto(sandbox, monkeypatch, bus):
    _sembrar("vlm", pid=999, puerto=8081, t_ultima=1000.0)
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: False)
    assert S.vivos() == {}
    assert S._leer_estado()["roles"] == {}
    assert any(isinstance(e, events.Aviso) for e in bus)


# ---------------------------------------------------------------------------
# 5. barrido
# ---------------------------------------------------------------------------

def test_barrido_vence_por_idle_y_avisa(sandbox, monkeypatch, bus):
    _sembrar("vlm", pid=7, puerto=8081, t_ultima=50.0)   # 950s > idle 900
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    liberados = []
    monkeypatch.setattr(S, "liberar", lambda rol: liberados.append(rol) or True)
    assert S.barrido(1000.0) == ["vlm"]
    assert liberados == ["vlm"]
    assert any(isinstance(e, events.Aviso) and "inactividad" in e.texto
               for e in bus)


def test_barrido_respeta_idle_no_vencido(sandbox, monkeypatch):
    _sembrar("vlm", pid=7, puerto=8081, t_ultima=990.0)
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    monkeypatch.setattr(S, "liberar", lambda rol: pytest.fail("no debia liberar"))
    assert S.barrido(1000.0) == []


def test_barrido_salta_worker_ocupado(sandbox, monkeypatch):
    _sembrar("imagen", pid=7, puerto=8096, t_ultima=100.0)  # 900s > idle 300
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    monkeypatch.setattr(S, "_salud",
                        lambda puerto, timeout=3.0: (200, {"ok": True, "ocupado": True}))
    monkeypatch.setattr(S, "liberar", lambda rol: pytest.fail("mato a mitad de job"))
    assert S.barrido(1000.0) == []


# ---------------------------------------------------------------------------
# 6. ensure con fakes
# ---------------------------------------------------------------------------

def _fakes_ensure(monkeypatch, *, vram=(2000, 16311), props=None,
                  pid_vivo=True, slots=1):
    """Arma el escenario tipico: nada servido, lanzamiento fake que 'levanta'
    el server, props verificables. Devuelve el registro de llamadas."""
    reg = {"lanzar": 0, "args": None, "arriba": False}

    def fake_lanzar(rol, spec, args):
        reg["lanzar"] += 1
        reg["args"] = list(args)
        reg["arriba"] = True
        return 4242, ["cmd-fake"]

    def fake_salud(puerto, timeout=3.0):
        return (200, {"ok": True}) if reg["arriba"] else (None, None)

    monkeypatch.setattr(S, "_lanzar", fake_lanzar)
    monkeypatch.setattr(S, "_salud", fake_salud)
    monkeypatch.setattr(S, "vram_mib", lambda: vram)
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: pid_vivo)
    monkeypatch.setattr(S, "_total_slots", lambda url: slots)
    if props is not None:
        monkeypatch.setattr(S, "_props", lambda url: dict(props))
    return reg


def test_ensure_rol_desconocido(sandbox):
    with pytest.raises(S.SummonerError, match="cerebro"):
        S.ensure("nope")


def test_ensure_arranque_frio_e_invalidadores(sandbox, monkeypatch, invalidadores):
    reg = _fakes_ensure(monkeypatch,
                        props={"modelo": "Qwen2.5-VL-3B-Q8_0.gguf", "n_ctx": 8192})
    r = S.ensure("vlm")
    assert r["ok"] and r["arranque_frio"] and r["pid"] == 4242
    assert r["url"] == "http://127.0.0.1:8081"
    assert reg["lanzar"] == 1
    # los 3 caches que mienten, invalidados con forzar=True
    assert invalidadores["reset"] == 1
    assert invalidadores["detectar"] == [True]
    assert invalidadores["perfil"] == [True]
    assert S._leer_estado()["roles"]["vlm"]["pid"] == 4242


def test_ensure_503_no_relanza(sandbox, monkeypatch, invalidadores):
    """503 es 'cargando', no 'muerto': relanzar duplica el proceso y da OOM."""
    _sembrar("vlm", pid=4242, puerto=8081, t_ultima=1000.0)
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    lanzados = {"n": 0}
    monkeypatch.setattr(S, "_lanzar",
                        lambda *a: lanzados.__setitem__("n", lanzados["n"] + 1) or (1, []))
    respuestas = [(503, None), (503, None), (200, None)]
    monkeypatch.setattr(S, "_salud",
                        lambda puerto, timeout=3.0: respuestas.pop(0) if respuestas else (200, None))
    monkeypatch.setattr(S, "_props",
                        lambda url: {"modelo": "Qwen2.5-VL-3B.gguf", "n_ctx": 8192})
    r = S.ensure("vlm")
    assert lanzados["n"] == 0, "relanzo sobre un 503 (doble proceso = OOM)"
    assert r["ok"] and not r["arranque_frio"]


def test_ensure_identidad_ajena(sandbox, monkeypatch, bus):
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    monkeypatch.setattr(S, "_props",
                        lambda url: {"modelo": "gpt-oss-20b.gguf", "n_ctx": 4096})
    with pytest.raises(S.SummonerError, match="ajeno"):
        S.ensure("vlm")
    assert any(isinstance(e, events.Degradado) and e.donde == "summoner"
               for e in bus)


def test_ensure_no_cabe_sin_victimas(sandbox, monkeypatch, bus):
    _fakes_ensure(monkeypatch, vram=(15000, 16311))   # libres 1311 < 3300+512
    with pytest.raises(S.SummonerError, match="no cabe"):
        S.ensure("vlm")
    assert any(isinstance(e, events.Degradado) for e in bus)


def test_ensure_timeout_libera(sandbox, monkeypatch, invalidadores):
    reloj = {"t": 0.0}

    def avanzar():
        reloj["t"] += 30.0
        return reloj["t"]

    monkeypatch.setattr(S, "_ahora", avanzar)
    monkeypatch.setattr(S, "_dormir", lambda s: None)
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    monkeypatch.setattr(S, "_lanzar", lambda *a: (4242, []))
    monkeypatch.setattr(S, "_matar_pid", lambda pid: None)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: None)
    with pytest.raises(S.SummonerError, match="health"):
        S.ensure("vlm", timeout_s=10)
    assert S._leer_estado()["roles"] == {}   # la libero al vencer


def test_ensure_cerebro_args_ctx_y_cache(sandbox, monkeypatch, invalidadores):
    """escalar_ctx delega en ensure(ctx=..., _cache=...): los args del
    lanzamiento deben llevar --ctx exacto, --fit-off (b10066 auto-reduce en
    silencio) y --ctk/--ctv cuando el cache no es f16."""
    reg = _fakes_ensure(monkeypatch,
                        props={"modelo": "Huihui-Qwythos-9B-Q4_K.gguf",
                               "n_ctx": 200192})
    r = S.ensure("cerebro", ctx=200192, _cache="q8_0")
    assert r["ok"] and r["n_ctx"] == 200192
    args = reg["args"]
    assert ["--ctx", "200192"] == args[args.index("--ctx"):args.index("--ctx") + 2]
    assert "--fit-off" in args
    assert ["--ctk", "q8_0", "--ctv", "q8_0"] == \
        args[args.index("--ctk"):args.index("--ctk") + 4]


def test_ensure_cerebro_postcheck_slots(sandbox, monkeypatch, invalidadores):
    """Una build que ignora --parallel 1 sirve HTTP 500 silenciosos: el
    postcheck debe liberar y fallar VISIBLE."""
    _fakes_ensure(monkeypatch, slots=4,
                  props={"modelo": "Huihui-Qwythos-9B-Q4_K.gguf", "n_ctx": 32768})
    monkeypatch.setattr(S, "_matar_pid", lambda pid: None)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: None)
    with pytest.raises(S.SummonerError, match="slots"):
        S.ensure("cerebro")


def test_ensure_relanza_si_pid_muerto(sandbox, monkeypatch, invalidadores):
    _sembrar("vlm", pid=999, puerto=8081, t_ultima=1000.0)
    reg = _fakes_ensure(monkeypatch, pid_vivo=False,
                        props={"modelo": "Qwen2.5-VL-3B.gguf", "n_ctx": 8192})

    # el pid nuevo (4242) debe contar como vivo; solo el rancio (999) esta muerto
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: pid != 999)
    r = S.ensure("vlm")
    assert reg["lanzar"] == 1 and r["pid"] == 4242


# ---------------------------------------------------------------------------
# 7. liberar
# ---------------------------------------------------------------------------

def test_cmd_kill_selectivo_jamas_im():
    cmd = S._cmd_kill(777)
    assert "/IM" not in cmd
    if sys.platform == "win32":
        assert cmd == ["taskkill", "/PID", "777", "/F"]


def test_liberar_mata_por_pid(sandbox, monkeypatch, invalidadores):
    _sembrar("vlm", pid=777, puerto=8081, t_ultima=1000.0)
    muertos = []
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: pid not in muertos)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: True)
    monkeypatch.setattr(S, "_matar_pid", lambda pid: muertos.append(pid))
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    assert S.liberar("vlm") is True
    assert muertos == [777]
    assert S._leer_estado()["roles"] == {}
    assert invalidadores["reset"] == 1   # vlm: caches invalidados


def test_liberar_mismatch_puerto_no_mata(sandbox, monkeypatch, bus):
    _sembrar("vlm", pid=777, puerto=8081, t_ultima=1000.0)
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: False)
    monkeypatch.setattr(S, "_matar_pid",
                        lambda pid: pytest.fail("mato a un inocente"))
    assert S.liberar("vlm") is False
    assert S._leer_estado()["roles"] == {}   # entrada limpiada igual
    assert any(isinstance(e, events.Aviso) for e in bus)


def test_liberar_dormido(sandbox, capsys):
    assert S.liberar("vlm") is False
    assert "dormido" in capsys.readouterr().err


def test_liberar_todo(sandbox, monkeypatch):
    _sembrar("voces", reserva=True, vram_mib=3000, puerto=8098,
             t_arranque=1000.0, t_ultima=1000.0)
    _sembrar("tresd", reserva=True, vram_mib=4000, puerto=8097,
             t_arranque=1000.0, t_ultima=1000.0)
    assert S.liberar_todo() == 2
    assert S._leer_estado()["roles"] == {}


# ---------------------------------------------------------------------------
# 8. invocar
# ---------------------------------------------------------------------------

def _fakes_invocar(monkeypatch, llamadas, *, restore_falla=False):
    monkeypatch.setattr(S, "barrido", lambda ahora=0.0: [])
    monkeypatch.setattr(S, "cabe",
                        lambda rol, con_cerebro=True: (False, "faltan MiB"))
    monkeypatch.setattr(S, "_cerebro_vivo", lambda: True)
    monkeypatch.setattr(S, "_props",
                        lambda url: {"modelo": "Huihui-Qwythos-9B.gguf",
                                     "n_ctx": 32768})
    monkeypatch.setattr(S, "_esperar_vram_libre",
                        lambda mib, tope_s=30.0: None)
    monkeypatch.setattr(S, "tocar", lambda rol: None)

    def fake_liberar(rol):
        llamadas.append(("liberar", rol))
        return True

    def fake_ensure(rol, **kw):
        llamadas.append(("ensure", rol))
        if restore_falla and rol == "cerebro":
            raise S.SummonerError("no arranco")
        return {"ok": True, "rol": rol}

    def fake_job(puerto, payload, timeout):
        llamadas.append(("job", puerto))
        return {"ok": True, "ruta": "C:/tmp/artefacto.png"}

    monkeypatch.setattr(S, "liberar", fake_liberar)
    monkeypatch.setattr(S, "ensure", fake_ensure)
    monkeypatch.setattr(S, "_post_job", fake_job)


def test_invocar_orden_evict_job_liberar_restore(sandbox, monkeypatch):
    llamadas = []
    _fakes_invocar(monkeypatch, llamadas)
    r = S.invocar("imagen", {"op": "generar"})
    assert llamadas == [("liberar", "cerebro"), ("ensure", "imagen"),
                        ("job", 8096), ("liberar", "imagen"),
                        ("ensure", "cerebro")]
    # el restore es lo ULTIMO antes de retornar: la proxima request del loop
    # va al cerebro
    assert r == {"ok": True,
                 "resultado": {"ok": True, "ruta": "C:/tmp/artefacto.png"},
                 "evicto_cerebro": True}


def test_invocar_restore_fallido_incluye_ruta(sandbox, monkeypatch, bus):
    llamadas = []
    _fakes_invocar(monkeypatch, llamadas, restore_falla=True)
    with pytest.raises(S.SummonerError, match=r"artefacto\.png"):
        S.invocar("imagen", {"op": "generar"})
    assert any(isinstance(e, events.Degradado) and "NO restaurado" in e.motivo
               for e in bus)


def test_invocar_evict_apagado(sandbox, monkeypatch):
    monkeypatch.setenv("COGNIA_SUMMONER_EVICT", "0")
    llamadas = []
    _fakes_invocar(monkeypatch, llamadas)
    with pytest.raises(S.SummonerError, match="EVICT"):
        S.invocar("imagen", {"op": "generar"})
    assert llamadas == []   # ni liberar ni ensure: error ANTES de evictar


def test_invocar_sin_eviccion_no_toca_cerebro(sandbox, monkeypatch):
    llamadas = []
    _fakes_invocar(monkeypatch, llamadas)
    monkeypatch.setattr(S, "cabe", lambda rol, con_cerebro=True: (True, ""))
    r = S.invocar("imagen", {"op": "generar"})
    assert ("liberar", "cerebro") not in llamadas
    assert ("liberar", "imagen") not in llamadas   # sin eviccion queda caliente
    assert r["evicto_cerebro"] is False


def test_invocar_rechaza_rol_no_job(sandbox, monkeypatch):
    monkeypatch.setattr(S, "barrido", lambda ahora=0.0: [])
    with pytest.raises(S.SummonerError, match="job"):
        S.invocar("voces", {})


# ---------------------------------------------------------------------------
# 9. escalar_ctx
# ---------------------------------------------------------------------------

def test_escalar_ctx_noop_si_alcanza(sandbox, monkeypatch):
    monkeypatch.setattr(S, "_props", lambda url: {"n_ctx": 200192})
    r = S.escalar_ctx(140000)
    assert r["relanzado"] is False and r["n_ctx"] == 200192


def test_escalar_ctx_celda_no_medida(sandbox, monkeypatch):
    monkeypatch.setattr(S, "_props", lambda url: {"n_ctx": 32768})
    monkeypatch.setenv("COGNIA_CTX_MAX", "5000000")   # sin clamp: 2M no esta medido
    with pytest.raises(S.SummonerError, match="escalera"):
        S.escalar_ctx(2_000_000)   # no hay celda medida tan grande


def test_escalar_ctx_relanza_a_celda(sandbox, monkeypatch):
    monkeypatch.setattr(S, "_props", lambda url: {"n_ctx": 32768})
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    liberados = []
    monkeypatch.setattr(S, "liberar", lambda rol: liberados.append(rol) or True)
    capturado = {}

    def fake_ensure(rol, **kw):
        capturado.update(rol=rol, **kw)
        return {"ok": True, "pid": 1}

    monkeypatch.setattr(S, "ensure", fake_ensure)
    r = S.escalar_ctx(140000)
    assert liberados == ["cerebro"]
    assert capturado["rol"] == "cerebro" and capturado["ctx"] == 200192
    assert r == {"ok": True, "n_ctx": 200192, "cache": "f16",
                 "relanzado": True, "pid": 1}


def test_escalar_ctx_pad256(sandbox, monkeypatch):
    """Pedir 200000 debe apuntar a la celda 200192 (llama-server paddea)."""
    monkeypatch.setattr(S, "_props", lambda url: {"n_ctx": 32768})
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    capturado = {}
    monkeypatch.setattr(S, "ensure",
                        lambda rol, **kw: capturado.update(kw) or {"ok": True, "pid": 1})
    r = S.escalar_ctx(200000)
    assert capturado["ctx"] == 200192 and r["n_ctx"] == 200192


# ---------------------------------------------------------------------------
# 10. Roles tipo presupuesto (reserva sin proceso)
# ---------------------------------------------------------------------------

def test_presupuesto_ensure_sin_proceso(sandbox, monkeypatch):
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    monkeypatch.setattr(S, "_lanzar",
                        lambda *a: pytest.fail("presupuesto no lanza proceso"))
    r = S.ensure("voces")
    assert r == {"ok": True, "rol": "voces", "url": None, "pid": None,
                 "modelo": None, "n_ctx": None, "arranque_frio": False}
    entrada = S._leer_estado()["roles"]["voces"]
    assert entrada["reserva"] is True and entrada["vram_mib"] == 3000


def test_presupuesto_liberar_borra_reserva(sandbox, monkeypatch):
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    monkeypatch.setattr(S, "_matar_pid",
                        lambda pid: pytest.fail("una reserva no se mata"))
    S.ensure("voces")
    assert S.liberar("voces") is True
    assert S._leer_estado()["roles"] == {}


def test_presupuesto_reserva_descuenta_vram(sandbox, monkeypatch, bus):
    """Dos reservas que juntas no caben: la segunda debe evictar la primera
    (borrar reserva) o fallar visible -- nvidia-smi NO ve las reservas."""
    monkeypatch.setattr(S, "vram_mib", lambda: (11000, 16311))  # libres 5311
    S.ensure("tresd")                      # reserva 4000 -> quedan 1311
    S.ensure("voces")                      # 3000+512 > 1311: evicta la reserva tresd
    roles = S._leer_estado()["roles"]
    assert "voces" in roles and "tresd" not in roles


def test_presupuesto_no_cabe_ni_evictando(sandbox, monkeypatch, bus):
    monkeypatch.setattr(S, "vram_mib", lambda: (15500, 16311))  # libres 811
    with pytest.raises(S.SummonerError, match="no cabe"):
        S.ensure("tresd")
    assert any(isinstance(e, events.Degradado) for e in bus)


def test_presupuesto_barrido_expira_reserva(sandbox, monkeypatch, bus):
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    monkeypatch.setattr(S, "_ahora", lambda: 100.0)
    S.ensure("voces")
    monkeypatch.setattr(S, "_matar_pid",
                        lambda pid: pytest.fail("una reserva no se mata"))
    assert S.barrido(1000.0) == ["voces"]   # 900s > idle 300
    assert S._leer_estado()["roles"] == {}


# ---------------------------------------------------------------------------
# 11. estado_roles / cabe
# ---------------------------------------------------------------------------

def test_estado_roles_ascii(sandbox, monkeypatch):
    _sembrar("vlm", pid=7, puerto=8081, t_ultima=900.0, modelo="VL-3B.gguf")
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    lineas = S.estado_roles()
    assert set(lineas) == set(S.ROLES)
    assert lineas["vlm"].startswith("VIVO pid=7 :8081")
    assert lineas["cerebro"] == "dormido"
    assert lineas["voces"] == "dormido (presupuesto)"
    for texto in lineas.values():
        texto.encode("ascii")   # cp1252-safe: sin acentos ni simbolos


def test_cabe_descuenta_reservas(sandbox, monkeypatch):
    monkeypatch.setattr(S, "vram_mib", lambda: (11000, 16311))  # libres 5311
    ok, _ = S.cabe("tresd")
    assert ok
    _sembrar("musica", reserva=True, vram_mib=2500, puerto=8099,
             t_arranque=1000.0, t_ultima=1000.0)
    ok, motivo = S.cabe("tresd")            # 5311-2500=2811 < 4000+512
    assert not ok and "faltan" in motivo


def test_cabe_sin_nvidia_smi(sandbox, monkeypatch):
    monkeypatch.setattr(S, "vram_mib", lambda: (-1, -1))
    ok, motivo = S.cabe("vlm")
    assert not ok and "nvidia-smi" in motivo
