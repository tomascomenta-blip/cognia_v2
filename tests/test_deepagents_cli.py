# -*- coding: utf-8 -*-
"""
tests/test_deepagents_cli.py
============================
Regresion SIN modelo de las piezas portadas de deepagents 0.7.8 al CLI
(2026-08-24): memoria como DATO en el agente y en el chat (P11,
middleware/memory.py), indice de skills con topes + cuerpo bajo demanda
(P10, middleware/skills.py), medida del prompt (P9, 'lean prompts') y las
puertas pedidas por los agentes bucle/tools (/bucle fichero, fila de
harness en /modelo, historial volcado en /compactar estado).
"""
from __future__ import annotations

import os
import types
from pathlib import Path

import pytest

import cognia.cli as cli
from cognia.agent import skills as SK


# ── helpers ─────────────────────────────────────────────────────────────────

@pytest.fixture
def salida(monkeypatch):
    """Captura lo que imprimen los handlers (con markup, sin rich)."""
    lineas = []
    monkeypatch.setattr(cli, "_print_line", lambda t: lineas.append(str(t)))
    monkeypatch.setattr(cli, "_show_response",
                        lambda t, *a, **k: lineas.append(str(t)))
    return lineas


@pytest.fixture
def config_falsa(monkeypatch):
    """_load_config/_save_config sobre un dict: los tests NUNCA tocan
    ~/.cognia_config.json (es la config real del dueno)."""
    cfg = dict(cli._CONFIG_DEFAULTS)
    monkeypatch.setattr(cli, "_load_config", lambda: dict(cfg))
    monkeypatch.setattr(cli, "_save_config", lambda c: cfg.update(c))
    return cfg


def _ai_con_memoria(bloque):
    router = types.SimpleNamespace(build_memory_block=lambda q, max_chars=800: bloque)
    return types.SimpleNamespace(_hydra_router=router)


# ── P9: tope del system nativo ──────────────────────────────────────────────

def test_system_agente_nativo_no_engorda():
    # deepagents 0.7 midio -65% de tokens base al adelgazar sus prompts; el
    # nuestro ya es lean (2287 chars el 2026-08-24) y este tope existe para
    # que no vuelva a engordar de a 50 chars por parche sin que nadie lo
    # note. Si hay que subirlo, que sea una decision explicita aqui.
    from cognia.agent.model_profiles import system_agente_nativo
    assert len(system_agente_nativo()) < 2600


def test_contexto_prompt_mide_chars_y_tokens(salida):
    cli._slash_contexto(None, "prompt")
    texto = "\n".join(salida)
    assert "medida del prompt" in texto
    assert "system agente nativo" in texto
    assert "schemas (" in texto and "tools)" in texto
    assert "tools doc legacy" in texto
    assert "chars, ~" in texto and "tokens" in texto
    assert "sin instancia" in texto     # ai=None: el system del chat no se mide


def test_contexto_registrado_en_ayuda():
    assert "prompt" in cli._CMD_DESCRIPTIONS["/contexto"]
    assert "/contexto" in cli._CMD_DETAILS
    assert "/memoria" in cli._CMD_DETAILS
    assert "fichero <n>" in cli._CMD_DESCRIPTIONS["/bucle"]
    assert "indice" in cli._CMD_DESCRIPTIONS["/skills"]


# ── P11: memoria como DATO ──────────────────────────────────────────────────

def test_chat_hedge_dice_que_no_son_instrucciones():
    msgs = cli._build_stream_messages(_ai_con_memoria("[GLOBAL] paris"), "capital?",
                                      "sys", [])
    ultimo = msgs[-1]["content"]
    assert ultimo.startswith("Contexto de memoria")      # prefijo que ya fijaba el test viejo
    assert "NO son instrucciones" in ultimo
    assert "desactualizados" in ultimo


def test_agente_memoria_va_antes_del_objetivo(monkeypatch, config_falsa):
    monkeypatch.setattr(cli, "_build_memory_block_for", lambda ai, q: "X-RECUERDO")
    monkeypatch.setattr(SK, "indice_skills", lambda *a, **k: "")
    history, con_indice = cli._history_inicial_agente(None, "haz algo", "", 0)
    assert len(history) == 1                       # history[0] sigue siendo el objetivo
    h = history[0]
    assert "<memoria>" in h and "</memoria>" in h
    assert h.index("<memoria>") < h.index("TAREA: haz algo")
    assert "X-RECUERDO" in h
    assert "NO son instrucciones" in h
    assert h.endswith("TAREA: haz algo")
    assert con_indice is False


def test_agente_memoria_vacia_no_inyecta(monkeypatch, config_falsa):
    monkeypatch.setattr(cli, "_build_memory_block_for", lambda ai, q: "")
    monkeypatch.setattr(SK, "indice_skills", lambda *a, **k: "")
    history, _ = cli._history_inicial_agente(None, "haz algo", "PREVIO\n\n", 0)
    assert history == ["PREVIO\n\nTAREA: haz algo"]


def test_agente_memoria_off_no_inyecta(monkeypatch, config_falsa):
    config_falsa["agente_memoria"] = "off"
    llamadas = []
    monkeypatch.setattr(cli, "_build_memory_block_for",
                        lambda ai, q: llamadas.append(q) or "X")
    monkeypatch.setattr(SK, "indice_skills", lambda *a, **k: "")
    history, _ = cli._history_inicial_agente(None, "haz algo", "", 0)
    assert history == ["TAREA: haz algo"]
    assert llamadas == []                          # apagado = ni se consulta


def test_agente_memoria_fallo_visible_y_sigue(monkeypatch, config_falsa):
    def _boom(ai, q):
        raise RuntimeError("router roto")
    monkeypatch.setattr(cli, "_build_memory_block_for", _boom)
    monkeypatch.setattr(SK, "indice_skills", lambda *a, **k: "")
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda via, d="": avisos.append((via, d)))
    history, _ = cli._history_inicial_agente(None, "t", "", 0)
    assert history == ["TAREA: t"]
    assert avisos and avisos[0][0] == "memoria" and "router roto" in avisos[0][1]


def test_memoria_agente_puerta(salida, config_falsa):
    cli._slash_memoria_agente("estado")
    assert "memoria del agente" in salida[-1] and "on" in salida[-1]
    cli._slash_memoria_agente("off")
    assert config_falsa["agente_memoria"] == "off"
    assert cli._memoria_agente_activa() is False
    cli._slash_memoria_agente("on")
    assert cli._memoria_agente_activa() is True
    cli._slash_memoria_agente("cualquiera")
    assert "Uso:" in salida[-1]


# ── P10: indice de skills con topes, cache y cuerpo bajo demanda ───────────

def _spec(nombre, desc, body="cuerpo"):
    return SK.SkillSpec(nombre, desc, body, f"/x/{nombre}.md", "cognia")


def test_indice_capa_descripciones_largas():
    skills = {f"s{i}": _spec(f"s{i}", f"d{i} " * 1000) for i in range(3)}
    idx = SK.indice_skills(skills)
    lineas = [ln for ln in idx.splitlines() if ln.startswith("- ")]
    assert len(lineas) == 3
    for i, ln in enumerate(lineas):
        nombre = f"s{i}"
        assert ln.startswith(f"- {nombre}: ")
        assert ln.endswith(f" -> skill_leer {nombre}")
        desc = ln[len(f"- {nombre}: "):-len(f" -> skill_leer {nombre}")]
        assert len(desc) <= SK.MAX_DESC_INDICE                   # 1024 (deepagents)
        assert len(ln) <= SK.MAX_DESC_INDICE + 2 * len(nombre) + len("- :  -> skill_leer ")
    assert "skill_leer <nombre>" in idx.splitlines()[0]


def test_indice_capa_nombre_y_vacio():
    largo = "n" * 200
    idx = SK.indice_skills({largo: _spec(largo, "d")}, cap_nombre=64)
    assert len(idx.splitlines()[1].split(":")[0]) <= 64 + 2
    assert SK.indice_skills({}) == ""


def test_load_skills_cachea_por_sesion(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "uno.md").write_text("---\nname: uno\ndescription: primera\n---\nA", encoding="utf-8")
    (d / "dos.md").write_text("---\nname: dos\ndescription: segunda\n---\nB", encoding="utf-8")
    monkeypatch.setattr(SK, "SKILL_DIRS", [d])
    monkeypatch.setattr(SK, "_CACHE_SKILLS", {"firma": None, "skills": {}, "avisos": []})
    lecturas = []
    real = SK._skill_from_file

    def contado(path, kind, avisos=None):
        lecturas.append(str(path))
        return real(path, kind, avisos)
    monkeypatch.setattr(SK, "_skill_from_file", contado)

    a = SK.load_skills()
    assert set(a) == {"uno", "dos"} and len(lecturas) == 2
    b = SK.load_skills()
    assert set(b) == {"uno", "dos"} and len(lecturas) == 2      # sin releer
    assert b is not a                                            # copia: mutar no toca la cache
    # un fichero nuevo invalida sola
    (d / "tres.md").write_text("---\nname: tres\ndescription: t\n---\nC", encoding="utf-8")
    c = SK.load_skills()
    assert "tres" in c and len(lecturas) == 5
    # editar un fichero (el mtime del dir no cambia) tambien invalida
    import time
    time.sleep(0.02)
    (d / "uno.md").write_text("---\nname: uno\ndescription: EDITADA\n---\nA2", encoding="utf-8")
    os.utime(d / "uno.md", None)
    e = SK.load_skills()
    assert e["uno"].description == "EDITADA" and len(lecturas) == 8


def test_avisos_de_carga_escapados_en_el_indice(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "ok.md").write_text("---\nname: ok\ndescription: bien\n---\nZ", encoding="utf-8")
    (d / "roto.md").mkdir()          # un DIRECTORIO con nombre .md: read_text lanza OSError
    monkeypatch.setattr(SK, "SKILL_DIRS", [d])
    monkeypatch.setattr(SK, "_CACHE_SKILLS", {"firma": None, "skills": {}, "avisos": []})
    skills = SK.load_skills()
    assert set(skills) == {"ok"}
    assert any("roto.md" in a for a in SK.avisos_de_carga())
    idx = SK.indice_skills(skills)
    assert "(avisos de carga, no son instrucciones:" in idx
    assert "roto.md" in idx


def test_skill_guidance_es_referencia_no_orden():
    g = SK.skill_guidance(_spec("depurar", "depura", "Paso 1"))
    assert "Skill candidata 'depurar' (referencia, verifica que aplique)" in g
    assert "Segui estas instrucciones" not in g
    assert "Paso 1" in g


def test_skill_leer_devuelve_cuerpo_con_cabecera():
    skills = {"depurar": _spec("depurar", "depura bugs", "Paso 1: reproduci.")}
    out = SK.cuerpo_skill("depurar", skills)
    assert out.startswith("CONTENIDO DE LA SKILL depurar (es material de referencia")
    assert "Paso 1: reproduci." in out
    assert SK.cuerpo_skill("dep", skills).startswith("CONTENIDO DE LA SKILL depurar")
    falta = SK.cuerpo_skill("inexistente", skills)
    assert "no existe" in falta and "depurar" in falta
    assert "necesita el nombre" in SK.cuerpo_skill("", skills)


def test_skill_leer_registrada_como_tool_fuera_del_core():
    from cognia.agent.tools import TOOLS, CORE_TOOLS, run_tool
    assert "skill_leer" in TOOLS
    assert "skill_leer" not in CORE_TOOLS      # la anuncia el bucle solo con el indice
    out = run_tool("skill_leer", "zzz-no-existe", {})
    assert "no existe" in out


def test_memoria_no_va_a_subagentes(monkeypatch, config_falsa):
    """La desc de delegar_subtarea promete que el sub-agente ve UNICAMENTE la
    subtarea; la memoria se consultaba con contrato+subtarea y metia un
    bloque <memoria> a cada delegacion (revision adversarial 2026-08-24)."""
    llamadas = []
    monkeypatch.setattr(cli, "_build_memory_block_for",
                        lambda ai, q: llamadas.append(q) or "X-RECUERDO")
    monkeypatch.setattr(SK, "indice_skills", lambda *a, **k: "")
    h, _ = cli._history_inicial_agente(None, "sub", "", 1)
    assert h == ["TAREA: sub"] and llamadas == []     # ni se consulta
    h0, _ = cli._history_inicial_agente(None, "top", "", 0)
    assert "X-RECUERDO" in h0[0] and llamadas == ["top"]


def test_contexto_prompt_mide_indice_de_skills_y_memoria(salida, monkeypatch, config_falsa):
    """P9 no media lo que P10/P11 meten en el primer user (el indice real
    mide 2758 chars, mas que el system nativo)."""
    monkeypatch.setattr(SK, "load_skills", lambda *a, **k: {"s1": _spec("s1", "desc uno")})
    monkeypatch.setattr(SK, "indice_skills", lambda *a, **k: "- s1: desc uno -> skill_leer s1")
    monkeypatch.setattr(cli, "_build_memory_block_for", lambda ai, q: "RECUERDO-LARGO " * 10)
    monkeypatch.setattr(cli, "_ULTIMO_PRIMER_USER", {"memoria": "", "indice": ""})
    cli._slash_contexto(None, "prompt")
    texto = "\n".join(salida)
    assert "indice de skills (1 skills, primer user)" in texto
    assert "31 chars" in texto                          # len del indice falso
    assert "memoria del agente (primer user)" in texto and "0 chars" in texto
    salida.clear()
    cli._history_inicial_agente(None, "t", "", 0)
    assert cli._ULTIMO_PRIMER_USER["memoria"].startswith("<memoria>")
    assert cli._ULTIMO_PRIMER_USER["indice"].startswith("- s1:")
    cli._slash_contexto(None, "prompt")
    texto = "\n".join(salida)
    assert "memoria del agente (ultimo /hacer, primer user)" in texto
    assert f"{len(cli._ULTIMO_PRIMER_USER['memoria'])} chars" in texto


def test_indice_va_al_history_y_no_a_subagentes(monkeypatch, config_falsa):
    monkeypatch.setattr(cli, "_build_memory_block_for", lambda ai, q: "")
    monkeypatch.setattr(SK, "indice_skills", lambda *a, **k: "- s1: d -> skill_leer s1")
    h, ci = cli._history_inicial_agente(None, "t", "", 0)
    assert ci is True and "skill_leer s1" in h[0] and h[0].endswith("TAREA: t")
    h2, ci2 = cli._history_inicial_agente(None, "t", "", 1)
    assert ci2 is False and h2 == ["TAREA: t"]


def test_slash_skills_indice(salida):
    cli._slash_skills("indice")
    texto = "\n".join(salida)
    assert "Indice de skills tal como lo ve el agente" in texto
    assert "-> skill_leer " in texto


# ── P12/P8/P4: pedidos de los agentes bucle y tools ────────────────────────

def test_bucle_fichero_persiste_y_siembra(salida, config_falsa, monkeypatch):
    from cognia.harness import repeticion as _rep
    monkeypatch.delenv(_rep.ENV_UMBRAL_FICHERO, raising=False)
    cli._slash_bucle("fichero 4")
    assert config_falsa["repeticion_umbral_fichero"] == "4"
    assert os.environ[_rep.ENV_UMBRAL_FICHERO] == "4"
    assert _rep.umbral_fichero() == 4
    assert "nudge a las 4 ediciones" in salida[-1]
    # invalido: grita y no guarda
    cli._slash_bucle("fichero 1")
    assert "Uso: /bucle fichero" in salida[-1]
    assert config_falsa["repeticion_umbral_fichero"] == "4"
    cli._slash_bucle("fichero")
    assert "falta el umbral" in salida[-1]


def test_bucle_estado_tiene_fila_por_fichero(salida, config_falsa, monkeypatch):
    from cognia.harness import repeticion as _rep
    monkeypatch.setenv(_rep.ENV_UMBRAL_FICHERO, "5")
    cli._slash_bucle("estado")
    texto = "\n".join(salida)
    assert "por fichero" in texto
    assert "nudge a las 5 ediciones del mismo fichero" in texto
    cli._slash_bucle("zzz")
    assert "fichero <n>" in salida[-1]


def test_aplicar_config_bucle_siembra_umbral_fichero(config_falsa, monkeypatch):
    from cognia.harness import repeticion as _rep
    monkeypatch.delenv(_rep.ENV_UMBRAL_FICHERO, raising=False)
    config_falsa["repeticion_umbral_fichero"] = "7"
    cli._aplicar_config_bucle()
    assert os.environ[_rep.ENV_UMBRAL_FICHERO] == "7"
    # basura en la config: default 3 y aviso, nunca reventar
    monkeypatch.delenv(_rep.ENV_UMBRAL_FICHERO, raising=False)
    config_falsa["repeticion_umbral_fichero"] = "cero"
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda via, d="": avisos.append(d))
    cli._aplicar_config_bucle()
    assert os.environ[_rep.ENV_UMBRAL_FICHERO] == "3"
    assert any("repeticion_umbral_fichero" in a for a in avisos)


def test_compactar_estado_muestra_historial_volcado(salida, monkeypatch):
    from cognia.harness import compactacion as _comp
    import time
    monkeypatch.setattr(_comp, "_ULTIMA", {
        "modo": "resumen", "tokens_antes": 900, "tokens_despues": 300,
        "ts": time.time(), "mensajes_descartados": 4,
        "historial_ruta": "C:/off/comp-1.txt", "historial_handle": "res:1"})
    cli._slash_compactar("estado")
    # el render envuelve las filas largas con sangria colgante: comparar plano
    texto = " ".join("\n".join(salida).split())
    assert "historial en C:/off/comp-1.txt" in texto
    monkeypatch.setattr(_comp, "_ULTIMA", {
        "modo": "resumen", "tokens_antes": 900, "tokens_despues": 300,
        "ts": time.time(), "historial_error": "disco lleno"})
    salida.clear()
    cli._slash_compactar("estado")
    assert "volcado del historial FALLO: disco lleno" in " ".join("\n".join(salida).split())


def test_modelo_muestra_harness_por_familia(salida, config_falsa, monkeypatch):
    from cognia.agent import model_profiles as MP
    monkeypatch.setattr(cli, "_modelo_activo_nombre", lambda llama: "Nemotron-3.5-x.gguf")
    monkeypatch.setattr(MP, "_cfg_familia", lambda nombre, ruta="": (
        {"harness": {"sufijo_prompt": "usa path", "renombres": {"file": "path"},
                     "defaults": {"leer_archivo": {"limit": 100}}}}, "nemotron"))
    import shattering.model_constants as MC
    monkeypatch.setattr(MC, "discover_gguf_registry", lambda: {})
    cli._slash_modelo(types.SimpleNamespace(_orchestrator=None), "")
    texto = "\n".join(salida)
    assert "Harness (nemotron): sufijo de system 8 chars; renombres file->path; " \
           "defaults leer_archivo=['limit']" in texto
    salida.clear()
    monkeypatch.setattr(MP, "_cfg_familia", lambda nombre, ruta="": ({}, "qwen"))
    cli._slash_modelo(types.SimpleNamespace(_orchestrator=None), "")
    assert "Harness (qwen): ninguno" in "\n".join(salida)


def test_system_nativo_recibe_el_perfil_en_cli():
    # P8: el sufijo harness.sufijo_prompt solo llega al modelo si cli pasa el
    # perfil; con system_agente_nativo() pelado el shim de prompt era muerto.
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert src.count("system_agente_nativo(_perfil_modelo)") == 2
    assert "system_agente_nativo())" not in src      # ninguna llamada pelada
    # /contexto prompt mide el system CON el perfil (sufijo harness incluido).
    assert src.count("system_agente_nativo(_perfil)") == 1


def test_contexto_prompt_pasa_el_perfil_al_system(salida, monkeypatch):
    from cognia.agent import model_profiles as mp
    monkeypatch.setattr(mp, "perfil_del_agente",
                        lambda *a, **k: {"harness": {"sufijo_prompt": "SUFIJO-HARNESS-XYZ"}})
    visto = {}
    real = mp.system_agente_nativo

    def _sys(perfil=None):
        visto["perfil"] = perfil
        return real(perfil)
    monkeypatch.setattr(mp, "system_agente_nativo", _sys)
    cli._slash_contexto(None, "prompt")
    assert visto["perfil"]["harness"]["sufijo_prompt"] == "SUFIJO-HARNESS-XYZ"
    assert "system agente nativo (con sufijo harness)" in "\n".join(salida)
