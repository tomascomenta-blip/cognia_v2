# -*- coding: utf-8 -*-
"""
Regresiones del area program_creator (worklist F2, area A5 — 2026-08-01).

Cuatro bugs cazados por la auditoria, cada test falla sin su fix:

1. juez_ejecutable._cerrar: un producto que reprobaba el 100% de su contrato
   salia APROBADO (4.0) porque solo se miraban los checks criticos y los pasos
   de contrato nacen con critico=False.
2. storage.auto_cleanup: _score_num(null)->0.0 convertia las entradas legacy
   NUNCA medidas (total_score=null) en candidatas de borrado masivo.
3. Los Disyuntor de program_creator se creaban sin ruta_log: el corte no
   dejaba rastro en .disciplina/ y la calibracion del modo sombra no podia
   contar esos disparos.
4. _llm_de_cognia devolvia el closure sin url_base y el audit registraba
   "inyectado(url desconocida)" con :8080 supuesto (110 entradas).
"""

import json
import types

from cognia.program_creator import juez_ejecutable as je
from cognia.program_creator import program_creator as pc
from cognia.program_creator import storage as st
from cognia.program_creator.generator import GeneratedProgram
from cognia.program_creator.sandbox_runner import ExecutionResult


# ── 1. contrato reprobado => FALLIDO aunque ningun paso sea critico ──────────

def _veredicto_base():
    v = je.Veredicto(producto="x", con_contrato=True)
    v.checks = [
        je.Check("carga", True, "", critico=True),
        je.Check("contenido", True, "", critico=True),
        je.Check("sin_errores_js", True, ""),
        je.Check("interactivo", True, ""),
    ]
    return v


def test_contrato_fallado_sin_criticos_no_aprueba():
    """Los pasos de contrato nacen critico=False (_ejecutar_paso): que fallen
    TODOS no puede terminar en APROBADO — el contrato es la especificacion."""
    v = _veredicto_base()
    v.checks += [je.Check("las cartas nacen tapadas", False, "16 destapadas"),
                 je.Check("click voltea una carta", False, "no reacciona")]
    v = je._cerrar(v)
    assert v.aprobado is False
    assert v.estado == "FALLIDO"
    assert v.puntaje_ejecucion is None          # roto = sin puntaje
    assert v.motivo.startswith("contrato incumplido")


def test_contrato_todo_en_verde_sigue_aprobando():
    v = _veredicto_base()
    v.checks += [je.Check("las cartas nacen tapadas", True, ""),
                 je.Check("click voltea una carta", True, "")]
    v = je._cerrar(v)
    assert v.aprobado is True
    assert v.estado == "APROBADO"
    assert v.puntaje_ejecucion == 10.0


def test_sin_contrato_un_universal_no_critico_no_tumba():
    """El cambio es SOLO para checks de contrato: sin contrato, que falle
    'interactivo' (no critico) sigue dando VIVO, como siempre."""
    v = _veredicto_base()
    v.con_contrato = False
    v.checks[3] = je.Check("interactivo", False, "no reacciona")
    v = je._cerrar(v)
    assert v.aprobado is True
    assert v.estado == "VIVO"


# ── 2. auto_cleanup no toca lo NUNCA medido ──────────────────────────────────

def test_auto_cleanup_no_borra_entradas_nunca_medidas(tmp_path):
    index = [{"id": f"ok{i}", "title": f"OK{i}", "total_score": 9.0,
              "created_at": "2026-07-01", "category": "juego"}
             for i in range(6)]
    index += [{"id": "malo", "title": "Malo", "total_score": 1.0,
               "created_at": "2026-07-02", "category": "juego"},
              {"id": "legacyA", "title": "Legacy A", "total_score": None,
               "created_at": "", "category": "(de construidos/)"},
              {"id": "legacyB", "title": "Legacy B", "total_score": None,
               "created_at": "2026-07-24", "category": ""}]
    for e in index:
        (tmp_path / e["id"]).mkdir()
    (tmp_path / st.INDEX_FILE).write_text(json.dumps(index), encoding="utf-8")

    borrados = st.auto_cleanup(storage_dir=tmp_path, keep_minimum=1,
                               verbose=False)

    ids = {e["id"] for e in json.loads(
        (tmp_path / st.INDEX_FILE).read_text(encoding="utf-8"))}
    # lo medido y malo se limpia; lo NUNCA medido sobrevive
    assert borrados == 1
    assert "malo" not in ids
    assert {"legacyA", "legacyB"} <= ids
    assert (tmp_path / "legacyA").exists() and (tmp_path / "legacyB").exists()


def test_replace_if_better_no_borra_entradas_nunca_medidas(tmp_path):
    index = [{"id": "legacyA", "title": "Legacy A", "total_score": None,
              "created_at": "", "category": "juego"}]
    (tmp_path / "legacyA").mkdir()
    (tmp_path / st.INDEX_FILE).write_text(json.dumps(index), encoding="utf-8")

    nuevo = GeneratedProgram(title="Nuevo", description="d", code="x",
                             category="juego")
    ev = types.SimpleNamespace(total_score=9.0)
    assert st.replace_if_better(nuevo, ev, storage_dir=tmp_path) is False
    assert (tmp_path / "legacyA").exists()


# ── 3. el corte del disyuntor "reparar" deja pc_*.jsonl con el disparo ───────

def test_disyuntor_reparar_persiste_el_disparo(tmp_path, monkeypatch):
    """Se fuerza el bucle de reparacion esteril (mismo sintoma dos veces) y se
    comprueba que el corte queda en .disciplina/pc_*.jsonl como evento
    'disparo' — sin ruta_log este JSONL no existia y el corte era invisible."""
    monkeypatch.setattr(pc, "DIR_ESTADO", tmp_path / "disciplina")

    prog = GeneratedProgram(title="rotito", description="d",
                            code="raise ValueError('x')", category="tools")
    fallo = ExecutionResult(success=False, execution_output="",
                            execution_errors="ValueError: siempre el mismo",
                            exit_code=1, timed_out=False)

    monkeypatch.setattr(pc, "generate_program", lambda *a, **k: prog)
    monkeypatch.setattr(pc, "run_in_sandbox", lambda code: fallo)
    monkeypatch.setattr(pc, "reparar_python", lambda p, e, llm=None: prog)

    pc.run_program_hobby(max_attempts=1, storage_dir=tmp_path / "lib",
                         verbose=False)

    logs = list((tmp_path / "disciplina").glob("pc_*.jsonl"))
    assert logs, "el disyuntor corto sin dejar pc_*.jsonl"
    eventos = [json.loads(l) for l in
               logs[0].read_text(encoding="utf-8").splitlines()]
    disparos = [e for e in eventos if e.get("evento") == "disparo"]
    assert disparos and disparos[0]["motivo"]


# ── 4. el closure de _llm_de_cognia lleva su url real ────────────────────────

def test_llm_de_cognia_expone_url_base(monkeypatch):
    import cognia.llm_local as llm_local
    monkeypatch.setattr(llm_local, "detectar_backend",
                        lambda forzar=False: {"tipo": "llama",
                                              "url": "http://127.0.0.1:8080"})
    inst = types.SimpleNamespace(_orchestrator=object())
    llm = pc._llm_de_cognia(inst)
    assert llm is not None
    # generator._call_llm lee este atributo para el audit (rol="inyectado")
    assert getattr(llm, "url_base", None) == "http://127.0.0.1:8080"
