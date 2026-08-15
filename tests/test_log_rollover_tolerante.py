# -*- coding: utf-8 -*-
"""El rollover del log no puede tumbar el arranque (2026-08-15).

En Windows rotar exige RENOMBRAR el archivo, y eso falla con
`PermissionError [WinError 32]` cuando otro proceso de Cognia tiene el mismo
log abierto. Medido en el e2e: dos arranques concurrentes escupían ~40 líneas
de traceback cada uno, 2 de 2 veces.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.logger_config import _RotatingTolerante


def _registro(msg="x" * 200):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def test_una_rotacion_bloqueada_no_lanza(tmp_path, monkeypatch, capsys):
    ruta = tmp_path / "cognia.log"
    h = _RotatingTolerante(str(ruta), maxBytes=100, backupCount=1,
                           encoding="utf-8")
    _RotatingTolerante._aviso_dado = False
    # El renombrado falla como en Windows con el archivo tomado.
    monkeypatch.setattr(
        logging.handlers.RotatingFileHandler, "doRollover",
        lambda self: (_ for _ in ()).throw(PermissionError("WinError 32")))
    try:
        h.emit(_registro())          # dispara la rotación
        h.emit(_registro())          # y sigue escribiendo después
    finally:
        h.close()
    err = capsys.readouterr().err
    assert "no pude rotar el log" in err
    assert "Traceback" not in err
    assert ruta.exists() and ruta.stat().st_size > 0


def test_el_aviso_sale_UNA_vez_no_en_cada_rotacion(tmp_path, monkeypatch,
                                                   capsys):
    ruta = tmp_path / "c.log"
    h = _RotatingTolerante(str(ruta), maxBytes=50, backupCount=1,
                           encoding="utf-8")
    _RotatingTolerante._aviso_dado = False
    monkeypatch.setattr(
        logging.handlers.RotatingFileHandler, "doRollover",
        lambda self: (_ for _ in ()).throw(PermissionError("WinError 32")))
    try:
        for _ in range(5):
            h.emit(_registro())
    finally:
        h.close()
    # Cambiar un ruido de 40 líneas por otro de 5 avisos no sería arreglarlo.
    assert capsys.readouterr().err.count("no pude rotar") == 1


def test_cuando_SI_puede_rotar_rota(tmp_path):
    ruta = tmp_path / "c.log"
    h = _RotatingTolerante(str(ruta), maxBytes=120, backupCount=2,
                           encoding="utf-8")
    try:
        for _ in range(6):
            h.emit(_registro())
    finally:
        h.close()
    # Contrafactual: sin bloqueo, el comportamiento es el de siempre.
    assert (tmp_path / "c.log.1").exists()
