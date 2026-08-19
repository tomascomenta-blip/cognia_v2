# -*- coding: utf-8 -*-
"""
tests/test_multiverso_instantanea.py
====================================
Tests de cognia/multiverso/instantanea.py. Sin modelo, sin red, sin subprocess:
todo corre sobre tmp_path y el almacen se aisla con `almacen=` en cada llamada
(nunca se toca ~/.cognia).

Los casos de Windows (solo lectura, fichero ABIERTO, objeto enlazado mutado
in-place) NO son decorativos: salen de sondas medidas en esta maquina y son
justo donde un rollback se rompe en silencio.
"""

import hashlib
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognia.multiverso import instantanea as ins  # noqa: E402


# -- utilidades del test ------------------------------------------------
def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _huella(raiz):
    """{ruta_relativa: sha256} de TODO el arbol, sin exclusiones. Es la
    verificacion de que restaurar deja el disco EXACTAMENTE igual."""
    out = {}
    for r, _d, ns in os.walk(str(raiz)):
        for n in ns:
            p = os.path.join(r, n)
            rel = os.path.relpath(p, str(raiz)).replace("\\", "/")
            with open(p, "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


@pytest.fixture()
def ws(tmp_path):
    """Workspace de partida: 3 ficheros, un subdirectorio y un dir vacio."""
    w = tmp_path / "ws"
    (w / "src").mkdir(parents=True)
    (w / "vacio").mkdir()
    (w / "a.txt").write_text("contenido A", encoding="utf-8")
    (w / "src" / "b.py").write_text("print('b')\n", encoding="utf-8")
    (w / "src" / "c.md").write_text("# c\n", encoding="utf-8")
    return w


@pytest.fixture()
def alm(tmp_path):
    return tmp_path / "almacen"


# -- 1. round-trip completo --------------------------------------------
def test_round_trip_exacto_por_hash(ws, alm):
    """Crear, modificar y borrar; restaurar tiene que devolver el arbol al
    estado EXACTO, verificado por sha256 de cada fichero."""
    antes = _huella(ws)
    snap = ins.tomar(ws, etiqueta="base", almacen=alm)

    # la rama hace de las suyas
    (ws / "nuevo.txt").write_text("basura de la rama", encoding="utf-8")
    (ws / "src" / "nuevo2.py").write_text("x=1", encoding="utf-8")
    (ws / "a.txt").write_text("MODIFICADO por la rama", encoding="utf-8")
    (ws / "src" / "c.md").unlink()
    (ws / "dir_rama").mkdir()

    r = ins.restaurar(snap)
    assert r["ok"] is True, r
    assert sorted(r["borrados"]) == ["nuevo.txt", "src/nuevo2.py"]
    assert r["restaurados"] == ["a.txt"]
    assert r["recuperados"] == ["src/c.md"]
    assert r["dirs_borrados"] == ["dir_rama"]
    assert _huella(ws) == antes
    assert not (ws / "dir_rama").exists()
    assert (ws / "vacio").is_dir()      # el dir vacio que existia sigue ahi
    assert isinstance(r["ms"], float)


def test_dir_vacio_borrado_se_recupera(ws, alm):
    snap = ins.tomar(ws, almacen=alm)
    (ws / "vacio").rmdir()
    r = ins.restaurar(snap)
    assert r["ok"] is True
    assert "vacio" in r["dirs_creados"]
    assert (ws / "vacio").is_dir()


def test_restaurar_dos_veces_es_idempotente(ws, alm):
    snap = ins.tomar(ws, almacen=alm)
    (ws / "a.txt").write_text("otra cosa", encoding="utf-8")
    ins.restaurar(snap)
    r2 = ins.restaurar(snap)
    assert r2["ok"] is True
    assert r2["restaurados"] == [] and r2["recuperados"] == []
    assert r2["sin_cambio"] == len(snap.manifiesto)


# -- 2. almacen: dedup y contabilidad ----------------------------------
def test_segunda_instantanea_no_escribe_bytes(ws, alm):
    s1 = ins.tomar(ws, almacen=alm)
    assert s1.bytes_nuevos == s1.bytes_totales > 0
    s2 = ins.tomar(ws, almacen=alm)
    assert s2.bytes_nuevos == 0            # todo por dedup
    assert s2.modo_contenido == "dedup"
    est = ins.estadisticas_almacen(alm)
    assert est["objetos"] == 3


def test_base_delta_evita_rehash(ws, alm):
    s1 = ins.tomar(ws, almacen=alm)
    s2 = ins.tomar(ws, almacen=alm, base=s1)
    assert s2.modo_contenido == "dedup"
    assert s2.manifiesto == s1.manifiesto
    (ws / "a.txt").write_text("cambia", encoding="utf-8")
    s3 = ins.tomar(ws, almacen=alm, base=s2)
    assert s3.manifiesto["a.txt"]["sha"] != s1.manifiesto["a.txt"]["sha"]
    assert s3.manifiesto["src/b.py"] == s1.manifiesto["src/b.py"]


# -- 3. diferencia ------------------------------------------------------
def test_diferencia_clasifica_bien(ws, alm):
    a = ins.tomar(ws, almacen=alm)
    (ws / "nuevo.txt").write_text("n", encoding="utf-8")
    (ws / "a.txt").write_text("m", encoding="utf-8")
    (ws / "src" / "c.md").unlink()
    b = ins.tomar(ws, almacen=alm)
    d = ins.diferencia(a, b)
    assert d["creados"] == ["nuevo.txt"]
    assert d["modificados"] == ["a.txt"]
    assert d["borrados"] == ["src/c.md"]
    assert d["n_iguales"] == 1                       # src/b.py
    assert d["shas"]["src/c.md"] is None
    assert d["shas"]["nuevo.txt"] == b.manifiesto["nuevo.txt"]["sha"]


def test_diferencia_de_uno_consigo_mismo_es_vacia(ws, alm):
    a = ins.tomar(ws, almacen=alm)
    d = ins.diferencia(a, a)
    assert d["creados"] == [] and d["modificados"] == [] and d["borrados"] == []


# -- 4. aplicar_diferencia (el MERGE) ----------------------------------
def test_aplicar_diferencia_mueve_el_efecto(tmp_path, ws, alm):
    """La rama trabaja en su copia; el efecto se lleva al workspace real."""
    real = tmp_path / "real"
    real.mkdir()
    for rel in ("a.txt", "src/b.py", "src/c.md"):
        d = real / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_bytes((ws / rel).read_bytes())

    a = ins.tomar(ws, almacen=alm)
    (ws / "feature.py").write_text("def f(): return 42\n", encoding="utf-8")
    (ws / "a.txt").write_text("A mejorado", encoding="utf-8")
    (ws / "src" / "c.md").unlink()
    b = ins.tomar(ws, almacen=alm)

    r = ins.aplicar_diferencia(ins.diferencia(a, b), ws, real, almacen=alm)
    assert r["ok"] is True, r
    assert sorted(r["escritos"]) == ["a.txt", "feature.py"]
    assert r["borrados"] == ["src/c.md"]
    assert (real / "feature.py").read_text(encoding="utf-8").startswith("def f")
    assert (real / "a.txt").read_text(encoding="utf-8") == "A mejorado"
    assert not (real / "src" / "c.md").exists()
    assert _sha(real / "feature.py") == b.manifiesto["feature.py"]["sha"]


def test_aplicar_diferencia_tira_del_almacen_si_la_rama_ya_no_esta(
        tmp_path, ws, alm):
    """El merge sobrevive a que el workspace de la rama se haya borrado."""
    import shutil
    real = tmp_path / "real"
    real.mkdir()
    a = ins.tomar(ws, almacen=alm)
    (ws / "feature.py").write_text("cuerpo de la feature\n", encoding="utf-8")
    b = ins.tomar(ws, almacen=alm)
    dif = ins.diferencia(a, b)
    shutil.rmtree(str(ws))               # la rama desaparece del disco

    r = ins.aplicar_diferencia(dif, ws, real, almacen=alm)
    assert r["ok"] is True, r
    assert r["escritos"] == ["feature.py"]
    assert (real / "feature.py").read_text(encoding="utf-8") == \
        "cuerpo de la feature\n"


def test_aplicar_diferencia_reporta_ausentes_y_no_finge_ok(tmp_path):
    """Sin fuente viva y sin objeto: `ausentes`, ok=False. Nada de fingir."""
    real = tmp_path / "real"
    real.mkdir()
    dif = {"creados": ["x.txt"], "modificados": [], "borrados": [],
           "shas": {"x.txt": "0" * 64}}
    r = ins.aplicar_diferencia(dif, tmp_path / "no_existe", real,
                               almacen=tmp_path / "almacen_vacio")
    assert r["ok"] is False
    assert r["ausentes"] == ["x.txt"]
    assert r["escritos"] == []


# -- 5. exclusiones y tope ---------------------------------------------
def test_exclusiones_por_defecto(ws, alm):
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: x", encoding="utf-8")
    (ws / "__pycache__").mkdir()
    (ws / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"\x00\x01")
    (ws / "venv312").mkdir()
    (ws / "venv312" / "pyvenv.cfg").write_text("home=x", encoding="utf-8")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "p.js").write_text("//", encoding="utf-8")
    (ws / "suelto.pyc").write_bytes(b"\x00")

    s = ins.tomar(ws, almacen=alm)
    rutas = set(s.manifiesto)
    assert rutas == {"a.txt", "src/b.py", "src/c.md"}
    motivos = {o["ruta"]: o["motivo"] for o in s.omitidos}
    for d in (".git", "__pycache__", "venv312", "node_modules"):
        assert motivos.get(d) == "dir_excluido"
    assert motivos.get("suelto.pyc") == "fichero_excluido"
    # y lo excluido NO se borra al restaurar: sigue vivo
    assert ins.restaurar(s)["ok"] is True
    assert (ws / ".git" / "HEAD").exists()
    assert (ws / "suelto.pyc").exists()


def test_tope_de_tamano_omite_y_declara(ws, alm):
    (ws / "grande.bin").write_bytes(b"x" * 200_000)
    s = ins.tomar(ws, almacen=alm, tope_mb=0.1)      # 100 KB
    assert "grande.bin" not in s.manifiesto
    om = [o for o in s.omitidos if o["ruta"] == "grande.bin"]
    assert om and om[0]["motivo"] == "supera_tope" and om[0]["tam"] == 200_000
    # LIMITE DECLARADO: lo que pasa el tope SOBREVIVE a restaurar
    ins.restaurar(s)
    assert (ws / "grande.bin").exists()


def test_exclusiones_configurables(ws, alm):
    s = ins.tomar(ws, almacen=alm, excluir_dirs=["src"], excluir_ficheros=[])
    assert set(s.manifiesto) == {"a.txt"}


# -- 6. Windows: solo lectura ------------------------------------------
def test_fichero_solo_lectura_se_captura_y_se_repone_el_bit(ws, alm):
    ro = ws / "ro.txt"
    ro.write_text("intocable", encoding="utf-8")
    os.chmod(str(ro), stat.S_IREAD)
    s = ins.tomar(ws, almacen=alm)
    assert s.manifiesto["ro.txt"]["ro"] is True

    os.chmod(str(ro), stat.S_IWRITE)
    ro.write_text("ya no", encoding="utf-8")
    r = ins.restaurar(s)
    assert r["ok"] is True, r
    assert ro.read_text(encoding="utf-8") == "intocable"
    assert not (os.stat(str(ro)).st_mode & stat.S_IWRITE)   # bit repuesto
    os.chmod(str(ro), stat.S_IWRITE)                        # limpieza


def test_borrar_creado_de_solo_lectura_no_rompe(ws, alm):
    """En Windows unlink de un readonly da PermissionError (medido): el modulo
    quita el bit y lo borra igual."""
    s = ins.tomar(ws, almacen=alm)
    intruso = ws / "intruso.txt"
    intruso.write_text("de la rama", encoding="utf-8")
    os.chmod(str(intruso), stat.S_IREAD)
    r = ins.restaurar(s)
    assert r["ok"] is True, r
    assert r["borrados"] == ["intruso.txt"]
    assert not intruso.exists()


# -- 7. Windows: fichero EN USO ----------------------------------------
@pytest.mark.skipif(sys.platform != "win32",
                    reason="el bloqueo obligatorio de ficheros es de Windows")
def test_fichero_en_uso_se_reporta_no_se_traga(ws, alm):
    s = ins.tomar(ws, almacen=alm)
    (ws / "a.txt").write_text("modificado", encoding="utf-8")
    f = open(str(ws / "a.txt"), "w", encoding="utf-8")   # handle abierto
    try:
        r = ins.restaurar(s)
    finally:
        f.close()
    assert r["ok"] is False                       # NO finge exito
    assert r["fallos"], r
    fallo = [x for x in r["fallos"] if x["ruta"] == "a.txt"]
    assert fallo and "PermissionError" in fallo[0]["error"]
    # y el resto del arbol si se restauro: el fallo es LOCAL, no aborta todo
    ins.restaurar(s)                               # ya sin el handle
    assert (ws / "a.txt").read_text(encoding="utf-8") == "contenido A"


@pytest.mark.skipif(sys.platform != "win32", reason="bloqueo de Windows")
def test_creado_en_uso_no_se_puede_borrar_y_se_reporta(ws, alm):
    s = ins.tomar(ws, almacen=alm)
    nuevo = ws / "abierto.txt"
    nuevo.write_text("x", encoding="utf-8")
    f = open(str(nuevo), "r", encoding="utf-8")
    try:
        r = ins.restaurar(s)
    finally:
        f.close()
    assert r["ok"] is False
    assert any(x["ruta"] == "abierto.txt" and x["op"] == "borrar"
               for x in r["fallos"]), r["fallos"]


# -- 8. enlaces duros: el riesgo MEDIDO se detecta ---------------------
def test_enlace_mutado_in_place_se_detecta_como_corrupto(ws, alm):
    """Sonda medida en esta maquina: con enlaces, un write_text() in-place
    sobre el fichero vivo MUTA el objeto del almacen. Restaurar tiene que
    cazarlo por sha, no devolver basura."""
    s = ins.tomar(ws, almacen=alm, enlaces=True)
    assert s.modo_contenido == "enlace"
    original = (ws / "a.txt").read_text(encoding="utf-8")
    # misma longitud: asi el chequeo de tamano no lo caza y tiene que ser el sha
    (ws / "a.txt").write_text("X" * len(original), encoding="utf-8")
    r = ins.restaurar(s)
    assert r["ok"] is False
    assert any(c["ruta"] == "a.txt" and "CORRUPTO" in c["error"]
               for c in r["corruptos"]), r
    # y NO se escribio basura donde estaba el original
    assert (ws / "a.txt").read_text(encoding="utf-8") == "X" * len(original)


def test_enlace_mutado_y_luego_ROTO_sigue_detectandose(ws, alm):
    """El agujero que caza el contrafactual: si tras mutar el objeto in-place
    el enlace se ROMPE (borrar o reemplazar el fichero), st_nlink vuelve a 1 y
    la corrupcion ya ocurrida se vuelve invisible. Con la marca del almacen se
    sigue verificando. Sin este test el mecanismo pasaria por el motivo
    equivocado: el otro caso se detecta de casualidad, por nlink."""
    s = ins.tomar(ws, almacen=alm, enlaces=True)
    original = (ws / "a.txt").read_text(encoding="utf-8")
    (ws / "a.txt").write_text("X" * len(original), encoding="utf-8")  # muta obj
    (ws / "a.txt").unlink()                       # rompe el enlace: nlink -> 1
    obj = ins._ruta_objeto(alm, s.manifiesto["a.txt"]["sha"])
    assert obj.stat().st_nlink == 1               # el disparador viejo ya no ve nada
    r = ins.restaurar(s)
    assert r["ok"] is False
    assert any(c["ruta"] == "a.txt" and "CORRUPTO" in c["error"]
               for c in r["corruptos"]), r
    assert not (ws / "a.txt").exists()            # no se escribio basura


def test_almacen_de_solo_copia_no_lleva_marca(ws, alm):
    """La verificacion cara NO la paga el modo por defecto."""
    ins.tomar(ws, almacen=alm)
    assert not (alm / ins._MARCA_ENLACES).exists()
    assert ins._hubo_enlaces(alm) is False


def test_enlaces_no_copian_bytes(ws, alm):
    s = ins.tomar(ws, almacen=alm, enlaces=True)
    assert s.bytes_nuevos == 0 and s.bytes_totales > 0
    assert ins.estadisticas_almacen(alm)["objetos"] == 3


def test_enlaces_por_variable_de_entorno(ws, alm, monkeypatch):
    monkeypatch.setenv("COGNIA_MULTIVERSO_ENLACES", "1")
    assert ins.tomar(ws, almacen=alm).modo_contenido == "enlace"


# -- 8b. el LIMITE del atajo (tamano, mtime) y su escape --------------
def test_atajo_por_mtime_no_ve_una_mutacion_que_lo_preserva(ws, alm):
    """El limite DECLARADO, comprobado: si algo reescribe el fichero con el
    mismo tamano y repone el mtime_ns exacto, restaurar() por defecto lo da por
    intacto. Se documenta con un test para que no sea una sorpresa."""
    s = ins.tomar(ws, almacen=alm)
    ent = s.manifiesto["a.txt"]
    (ws / "a.txt").write_text("X" * ent["tam"], encoding="utf-8")
    os.utime(str(ws / "a.txt"), ns=(ent["ns"], ent["ns"]))   # mtime repuesto
    r = ins.restaurar(s)
    assert r["ok"] is True
    assert r["restaurados"] == []                 # no lo vio
    assert (ws / "a.txt").read_text(encoding="utf-8") == "X" * ent["tam"]


def test_verificar_true_si_ve_esa_mutacion(ws, alm):
    """El escape del limite anterior: `verificar=True` compara por sha256."""
    s = ins.tomar(ws, almacen=alm)
    ent = s.manifiesto["a.txt"]
    (ws / "a.txt").write_text("X" * ent["tam"], encoding="utf-8")
    os.utime(str(ws / "a.txt"), ns=(ent["ns"], ent["ns"]))
    r = ins.restaurar(s, verificar=True)
    assert r["ok"] is True
    assert r["restaurados"] == ["a.txt"]
    assert (ws / "a.txt").read_text(encoding="utf-8") == "contenido A"


# -- 9. serializacion y forma del manifiesto ---------------------------
def test_manifiesto_corto_es_mtime_tam_sha(ws, alm):
    s = ins.tomar(ws, almacen=alm)
    m = s.manifiesto_corto()
    mtime, tam, sha = m["a.txt"]
    assert isinstance(mtime, float) and tam == len("contenido A")
    assert len(sha) == 12 and s.manifiesto["a.txt"]["sha"].startswith(sha)


def test_guardar_y_cargar_json(tmp_path, ws, alm):
    s = ins.tomar(ws, etiqueta="rama-1", almacen=alm)
    p = s.guardar(tmp_path / "snaps" / "s1.json")
    s2 = ins.Instantanea.cargar(p)
    assert s2.id == s.id and s2.etiqueta == "rama-1"
    assert s2.manifiesto == s.manifiesto
    (ws / "a.txt").write_text("roto", encoding="utf-8")
    assert ins.restaurar(s2)["ok"] is True      # el JSON restaura de verdad
    assert (ws / "a.txt").read_text(encoding="utf-8") == "contenido A"


def test_almacen_por_variable_de_entorno(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_MULTIVERSO_DIR", str(tmp_path / "env_alm"))
    s = ins.tomar(ws)
    assert s.almacen == str(tmp_path / "env_alm")
    assert (tmp_path / "env_alm" / "objetos").is_dir()


# -- 10. errores de entrada --------------------------------------------
def test_workspace_inexistente_levanta(tmp_path):
    with pytest.raises(NotADirectoryError):
        ins.tomar(tmp_path / "no_existe")


def test_restaurar_a_otro_workspace(tmp_path, ws, alm):
    """restaurar(workspace=) materializa el arbol en un destino VACIO: es como
    se abre una rama nueva sin tocar el original."""
    s = ins.tomar(ws, almacen=alm)
    destino = tmp_path / "rama"
    r = ins.restaurar(s, workspace=destino)
    assert r["ok"] is True, r
    assert sorted(r["recuperados"]) == ["a.txt", "src/b.py", "src/c.md"]
    assert _huella(destino) == _huella(ws)
