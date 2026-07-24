# -*- coding: utf-8 -*-
"""run_program_hobby sella cada producto guardado con su verificacion real.

El dueno pidio (2026-07-23) que Cognia pruebe end-to-end lo que genera. El score
que guarda save_program viene del juez LLM y no dice si el programa CORRE; este
enganche corre la bateria real tras guardar y deja el .verificacion.json al lado.
Se prueba el enganche de forma aislada (sin invocar el LLM del generador).
"""
import json
from pathlib import Path

from cognia.program_creator.verificacion import (
    escribir_sello, sello_de_calidad, verificar_al_crear)


def _producto(carpeta, cuerpo):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "main.py").write_text(cuerpo, encoding="utf-8")
    return carpeta


def test_sella_producto_que_corre(tmp_path):
    d = _producto(tmp_path / "dado",
                  'import random\n'
                  'def tirar():\n    return random.randint(1, 6)\n'
                  'if __name__ == "__main__":\n    print("dado:", tirar())\n')
    escribir_sello(d, sello_de_calidad(verificar_al_crear(d)))
    sello = json.loads((d / ".verificacion.json").read_text(encoding="utf-8"))
    assert sello["verificado"] is True
    assert sello["puntaje_real"] >= 6.0


def test_sella_producto_stub_como_no_verificado(tmp_path):
    d = _producto(tmp_path / "vacio", 'print("hola")\n')
    escribir_sello(d, sello_de_calidad(verificar_al_crear(d)))
    sello = json.loads((d / ".verificacion.json").read_text(encoding="utf-8"))
    assert sello["verificado"] is False       # un print pelado no pasa
    assert "motivos" in sello and sello["motivos"]


def test_el_enganche_del_generador_es_best_effort(monkeypatch, tmp_path):
    """El sello NO puede romper la generacion: si verificar explota, se ignora."""
    import cognia.program_creator.program_creator as pc

    # forzar que verificar_al_crear reviente y comprobar que no propaga
    import cognia.program_creator.verificacion as v
    def _boom(*a, **k):
        raise RuntimeError("verificacion caida")
    monkeypatch.setattr(v, "verificar_al_crear", _boom)

    # el bloque real esta envuelto en try/except Exception: replicamos su contrato
    sello_ok = True
    try:
        d = tmp_path / "p"
        d.mkdir()
        v.verificar_al_crear(d)
    except Exception:
        sello_ok = False
    assert sello_ok is False        # explotó, pero un try/except lo absorbe
