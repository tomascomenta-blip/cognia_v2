# -*- coding: utf-8 -*-
"""
scripts/medir_instantanea.py
============================
MEDICION real de cognia/multiverso/instantanea.py sobre esta maquina.

POR QUE EXISTE: ramificar el trabajo del agente solo es viable si tomar y
restaurar una instantanea cuesta menos que la tarea. Ese coste no se declara:
se mide. Sin este numero, todo el multiverso es fe.

QUE MIDE (ms de pared con perf_counter, y bytes REALES escritos al almacen):
  (a) 50 ficheros pequenos (generados)
  (b) el directorio cognia/ del repo, TAL CUAL (lectura; no lo toca)
  (c) un CLON de cognia/ en temp, donde si se puede medir restaurar()

Para cada caso: tomar en frio, tomar con dedup, tomar con base= (delta),
restaurar sin cambios, restaurar tras una rama real (modifica/crea/borra), y
las dos vias de ingreso (copia y enlace duro).

Uso:  PYTHONUTF8=1 ./venv312/Scripts/python.exe scripts/medir_instantanea.py
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.multiverso import instantanea as ins   # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _ms(fn):
    t0 = time.perf_counter()
    r = fn()
    return r, (time.perf_counter() - t0) * 1000.0


def _kb(n):
    return "%.1f KB" % (n / 1024.0)


def _linea(txt=""):
    print(txt, flush=True)


def _crear_n(raiz: Path, n=50):
    raiz.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        d = raiz / ("sub%d" % (i % 5))
        d.mkdir(exist_ok=True)
        (d / ("f%03d.txt" % i)).write_text(
            ("linea %d\n" % i) * 40, encoding="utf-8")


def _rama(ws: Path, n_mod=10, n_new=5, n_del=3):
    """Simula lo que hace una rama del agente. Devuelve (mod, new, borr)."""
    fich = sorted(p for p in ws.rglob("*") if p.is_file()
                  and p.suffix not in (".pyc",) and "__pycache__" not in str(p))
    mod = fich[:n_mod]
    for p in mod:
        try:
            with open(str(p), "ab") as f:
                f.write(b"\n# tocado por la rama\n")
        except OSError:
            pass
    for i in range(n_new):
        (ws / ("rama_%d.py" % i)).write_text("x = %d\n" % i, encoding="utf-8")
    borr = fich[n_mod:n_mod + n_del]
    for p in borr:
        try:
            p.unlink()
        except OSError:
            pass
    return len(mod), n_new, len(borr)


def medir(nombre: str, ws: Path, almacen: Path, restaurar_ok: bool,
          enlaces: bool):
    via = "ENLACE DURO" if enlaces else "COPIA"
    _linea("-" * 72)
    _linea("%s  [via de ingreso: %s]" % (nombre, via))
    _linea("  workspace: %s" % ws)

    s1, t1 = _ms(lambda: ins.tomar(ws, etiqueta="base", almacen=almacen,
                                   enlaces=enlaces))
    _linea("  tomar EN FRIO      %8.1f ms | %5d ficheros | arbol %10s | "
           "al almacen %10s | modo=%s"
           % (t1, len(s1.manifiesto), _kb(s1.bytes_totales),
              _kb(s1.bytes_nuevos), s1.modo_contenido))
    _linea("  omitidos: %d (%s)"
           % (len(s1.omitidos),
              ", ".join(sorted({o["motivo"] for o in s1.omitidos})) or "-"))

    s2, t2 = _ms(lambda: ins.tomar(ws, almacen=almacen, enlaces=enlaces))
    _linea("  tomar DEDUP        %8.1f ms | al almacen %10s | modo=%s"
           % (t2, _kb(s2.bytes_nuevos), s2.modo_contenido))

    s3, t3 = _ms(lambda: ins.tomar(ws, almacen=almacen, enlaces=enlaces,
                                   base=s2))
    _linea("  tomar con base=    %8.1f ms | (delta: ni hash ni copia)" % t3)

    if not restaurar_ok:
        _linea("  restaurar: NO SE MIDE aqui (es el repo vivo, no se toca)")
        return

    r0, tr0 = _ms(lambda: ins.restaurar(s1))
    _linea("  restaurar SIN CAMBIOS  %8.1f ms | ok=%s sin_cambio=%d"
           % (tr0, r0["ok"], r0["sin_cambio"]))

    rv, trv = _ms(lambda: ins.restaurar(s1, verificar=True))
    _linea("  restaurar VERIFICADO   %8.1f ms | ok=%s (sha256 de todo el arbol)"
           % (trv, rv["ok"]))

    nm, nn, nb = _rama(ws)
    _linea("  ...la rama toca el arbol: %d modificados, %d creados, %d borrados"
           % (nm, nn, nb))
    r1, tr1 = _ms(lambda: ins.restaurar(s1))
    _linea("  restaurar TRAS RAMA    %8.1f ms | ok=%s | restaurados=%d "
           "borrados=%d recuperados=%d fallos=%d CORRUPTOS=%d"
           % (tr1, r1["ok"], len(r1["restaurados"]), len(r1["borrados"]),
              len(r1["recuperados"]), len(r1["fallos"]), len(r1["corruptos"])))
    for f in r1["fallos"][:2]:
        _linea("     fallo: %s" % f)
    for c in r1["corruptos"][:2]:
        _linea("     corrupto: %s" % c)

    # CONTRAFACTUAL del propio restaurar: tras restaurar, una instantanea nueva
    # tiene que dar diferencia VACIA contra la original. Si no, no restauro.
    s4 = ins.tomar(ws, almacen=almacen, enlaces=enlaces)
    d = ins.diferencia(s1, s4)
    igual = not (d["creados"] or d["modificados"] or d["borrados"])
    _linea("  CONTRAFACTUAL: diferencia(base, tras_restaurar) vacia? %s  "
           "(creados=%d modificados=%d borrados=%d)"
           % ("SI" if igual else "NO -- EL ROLLBACK NO ES EXACTO",
              len(d["creados"]), len(d["modificados"]), len(d["borrados"])))

    est = ins.estadisticas_almacen(almacen)
    _linea("  almacen acumulado: %d objetos, %s" % (est["objetos"],
                                                    _kb(est["bytes"])))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="medir_multiverso_"))
    _linea("=" * 72)
    _linea("MEDICION cognia/multiverso/instantanea.py")
    _linea("  python   : %s" % sys.version.split()[0])
    _linea("  plataforma: %s" % sys.platform)
    _linea("  temp      : %s" % tmp)
    _linea("=" * 72)
    try:
        # (a) 50 ficheros pequenos ------------------------------------
        ws_a = tmp / "caso_a"
        for enl in (False, True):
            shutil.rmtree(str(ws_a), ignore_errors=True)
            _crear_n(ws_a, 50)
            medir("(a) 50 ficheros pequenos", ws_a,
                  tmp / ("alm_a_%s" % int(enl)), True, enl)

        # (a2) 200 ficheros: el punto que pedia el encargo ------------
        ws_a2 = tmp / "caso_a2"
        for enl in (False, True):
            shutil.rmtree(str(ws_a2), ignore_errors=True)
            _crear_n(ws_a2, 200)
            medir("(a2) 200 ficheros pequenos", ws_a2,
                  tmp / ("alm_a2_%s" % int(enl)), True, enl)

        # (b) cognia/ del repo, TAL CUAL (solo lectura) ---------------
        medir("(b) cognia/ del repo (SOLO LECTURA, no se restaura)",
              REPO / "cognia", tmp / "alm_b", False, False)
        medir("(b) cognia/ del repo (SOLO LECTURA, no se restaura)",
              REPO / "cognia", tmp / "alm_b_enl", False, True)

        # (c) clon de cognia/ en temp: aqui SI se mide restaurar -------
        ws_c = tmp / "clon_cognia"
        t0 = time.perf_counter()
        shutil.copytree(str(REPO / "cognia"), str(ws_c),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        _linea("-" * 72)
        _linea("clonando cognia/ a temp para poder medir restaurar(): %.0f ms"
               % ((time.perf_counter() - t0) * 1000.0))
        medir("(c) CLON de cognia/ (mismo arbol, restaurar medido)", ws_c,
              tmp / "alm_c", True, False)
        medir("(c) CLON de cognia/ (mismo arbol, restaurar medido)", ws_c,
              tmp / "alm_c_enl", True, True)
    finally:
        _linea("-" * 72)
        _linea("limpiando %s" % tmp)
        shutil.rmtree(str(tmp), ignore_errors=True)


if __name__ == "__main__":
    main()
