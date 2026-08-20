# -*- coding: utf-8 -*-
"""LIBRO -- el almacen append-only (ESPEC 3.2, 8.4; bloque M1).

Los tres que la ESPEC 14.2 exige nominalmente:
  - la cadena `prev` rota se DETECTA;
  - `prov.tipo='dicha'` en banda persistente se RECHAZA;
  - `conf > 0,30` con `origen='modelo'` se RECHAZA.

Mas los de corrupcion: una escritura cortada a mitad no puede dejar el libro
mintiendo ni tumbarlo.
"""

import json
import os

import pytest

from cognia.tx import libro as L
from cognia.tx.errores import EventoInvalido, LibroCaido


@pytest.fixture
def lib(tmp_path):
    return L.Libro(str(tmp_path / "t1"))


def _objetivo(texto="cablear el canal de estado"):
    return {"t": "objetivo", "op": "add", "id": "P-000", "banda": "P",
            "quien": "usuario", "origen": "usuario", "texto": texto,
            "prov": {"tipo": "dada", "cita": texto[:20], "ref": "tarea#0"}}


def test_append_devuelve_n_monotono(lib):
    assert lib.append(_objetivo()) == 1
    assert lib.append({"t": "restriccion", "op": "add", "id": "P-001",
                       "banda": "P", "quien": "usuario", "origen": "usuario",
                       "clave": "regla:venv", "valor": "si",
                       "texto": "usar venv312",
                       "prov": {"tipo": "dada", "cita": "venv312",
                                "ref": "CLAUDE.md#12"}}) == 2
    eventos = lib.leer()
    assert [e["n"] for e in eventos] == [1, 2]
    assert eventos[0]["prev"] is None
    assert eventos[1]["prev"] == eventos[0]["sha"]


def test_conf_es_funcion_pura_del_origen(lib):
    """El modelo no emite `conf`: se DERIVA de `origen` (ESPEC 3.3)."""
    lib.append(_objetivo())
    assert lib.leer()[0]["conf"] == 1.00


def test_cadena_prev_rota_se_detecta(lib):
    """EL TEST NOMINAL. Editar el libro a mano rompe el sha y se ve."""
    lib.append(_objetivo())
    lib.append(_objetivo("otro objetivo"))
    crudo = open(lib.ruta, "r", encoding="utf-8").read().splitlines(True)
    ev = json.loads(crudo[1])
    ev["prev"] = "deadbeefcafe00"
    crudo[1] = json.dumps(ev, ensure_ascii=True, separators=(",", ":")) + "\n"
    open(lib.ruta, "w", encoding="utf-8", newline="").write("".join(crudo))

    diag = {}
    eventos = L.Libro(lib.dir).leer(diag=diag)
    assert len(eventos) == 1, "el prefijo valido se corta en la linea rota"
    assert diag["cadena_rota"] == 1
    assert "cadena prev rota" in diag["motivo"]


def test_texto_manipulado_rompe_el_sha(lib):
    """El sha es content-addressed: cambiar el texto sin re-firmar se ve."""
    lib.append(_objetivo())
    ev = json.loads(open(lib.ruta, encoding="utf-8").read().strip())
    ev["texto"] = "un objetivo que nadie tecleo"
    open(lib.ruta, "w", encoding="utf-8", newline="").write(
        json.dumps(ev, ensure_ascii=True, separators=(",", ":")) + "\n")
    diag = {}
    assert L.Libro(lib.dir).leer(diag=diag) == []
    assert "sha no casa" in diag["motivo"]


def test_dicha_en_banda_persistente_se_rechaza(lib):
    """EL TEST NOMINAL. Lo que el modelo DIJO no toca una banda persistente."""
    for banda in L.BANDAS_PERSISTENTES:
        with pytest.raises(EventoInvalido) as exc:
            lib.append({"t": "afirmacion", "op": "add", "id": banda + "-9",
                        "banda": banda, "quien": "ejecutor", "origen": "modelo",
                        "texto": "render() ya respeta el orden",
                        "prov": {"tipo": "dicha"}})
        assert "dicha" in str(exc.value)
    assert lib.leer() == [], "nada de eso llego al disco"


def test_dicha_en_banda_x_si_entra(lib):
    """La contrapartida: en X vive y muere en el reset. Si tampoco entrase
    aqui, la prosa del modelo no quedaria registrada en ningun sitio."""
    n = lib.append({"t": "afirmacion", "op": "add", "id": "X-001", "banda": "X",
                    "quien": "ejecutor", "origen": "modelo",
                    "texto": "creo que ya esta", "prov": {"tipo": "dicha"}})
    assert n == 1


def test_conf_por_encima_del_techo_del_modelo_se_rechaza(lib):
    """EL TEST NOMINAL. origen='modelo' tiene techo DURO 0,30."""
    with pytest.raises(EventoInvalido) as exc:
        lib.append({"t": "decision", "op": "add", "id": "D-1", "banda": "D",
                    "quien": "ejecutor", "origen": "modelo", "conf": 0.95,
                    "clave": "dec:jsonl_no_pickle", "valor": "jsonl",
                    "texto": "jsonl y no pickle",
                    "prov": {"tipo": "derivada", "fn": "decidir", "base": []}})
    assert "0,30" in str(exc.value) or "0.30" in str(exc.value)


def test_clave_fuera_del_vocabulario_se_rechaza(lib):
    with pytest.raises(EventoInvalido):
        lib.append({"t": "hecho", "op": "add", "id": "F-1", "banda": "F",
                    "quien": "harness", "origen": "medido",
                    "clave": "loquesea:x", "valor": 1, "texto": "x",
                    "prov": {"tipo": "derivada", "fn": "f", "base": []}})


def test_no_existe_delete_ni_update(lib):
    for op in ("delete", "update"):
        with pytest.raises(EventoInvalido):
            lib.append(dict(_objetivo(), op=op))


def test_escritura_cortada_deja_el_libro_consistente(lib):
    """EL escenario de corte de luz: la ultima linea quedo a medias.

    `leer()` devuelve el prefijo valido y lo DICE; el siguiente append sanea la
    cola y deja constancia en el propio LIBRO -- no lo esconde.
    """
    lib.append(_objetivo())
    lib.append(_objetivo("segundo"))
    with open(lib.ruta, "a", encoding="utf-8", newline="") as fh:
        fh.write('{"n":3,"t":"hecho","op":"a')      # sin cerrar, sin \n

    diag = {}
    otro = L.Libro(lib.dir)
    eventos = otro.leer(diag=diag)
    assert [e["n"] for e in eventos] == [1, 2]
    assert diag["truncadas"] == 1
    assert diag["bytes_descartados"] > 0

    n = otro.append(_objetivo("tercero"))
    assert n == 3
    eventos = otro.leer()
    assert [e["n"] for e in eventos] == [1, 2, 3, 4]
    assert eventos[3]["t"] == "contradiccion", "la cola parcial deja constancia"
    assert otro.fsck()["ok"] is True


def test_fsck_informa_de_la_corrupcion(lib):
    lib.append(_objetivo())
    with open(lib.ruta, "a", encoding="utf-8", newline="") as fh:
        fh.write("esto no es json\n")
    inf = L.Libro(lib.dir).fsck()
    assert inf["ok"] is False
    assert inf["ilegibles"] == 1
    assert inf["eventos"] == 1


def test_libro_caido_si_no_se_puede_escribir(tmp_path, monkeypatch):
    """P0-2: el fallo de disco NO degrada a no hacer nada. Sube y para."""
    lib = L.Libro(str(tmp_path / "t2"))

    def revienta(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "open", revienta)
    with pytest.raises(LibroCaido) as exc:
        lib.append(_objetivo())
    assert "pasado incompleto" in str(exc.value)


def test_registrar_tool_sin_tarea_avisa_y_no_lanza(capsys):
    """COGNIA_TX=1 sin `/tx iniciar` es un estado LEGITIMO, distinto de roto.
    Se anuncia una vez y devuelve 0; no revienta el bucle del agente."""
    L.cerrar()
    L._AVISADO["sin_tarea"] = False
    assert L.registrar_tool({"t": "comando", "op": "add", "banda": "E",
                             "quien": "harness", "origen": "medido",
                             "texto": "x", "prov": {"tipo": "derivada",
                                                    "fn": "f", "base": []}}) == 0
    assert "no hay tarea abierta" in capsys.readouterr().err


def test_registrar_tool_escribe_el_envelope_del_interceptor(tmp_path, monkeypatch):
    """El hueco que el interceptor ya llama: el envelope entra tal cual y los
    campos que el esquema del LIBRO no tiene se guardan DENTRO de prov."""
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tmp_path))
    from cognia.harness import interceptor
    lib = L.abrir("tarea-x")
    try:
        ev = interceptor.envelope("ejecutar", "pytest -q", {}, "1 failed",
                                  False, exit_code=1)
        n = L.registrar_tool(ev, ctx={"_tx_ciclo": 7})
        assert n == 1
        guardado = lib.leer()[0]
        assert guardado["origen"] == "medido"
        assert guardado["ciclo"] == 7
        assert guardado["prov"]["exit_code"] == 1
        # La clave la canoniza `claves.canonica` (ESPEC 3.4): un pytest es una
        # clave `test:` y su valor canonico es el BOOLEANO exit==0, no el exit.
        # Antes el interceptor cableaba 'cmd:'+nombre_de_la_tool a mano y
        # `canonica` no la llamaba nadie, asi que la banda A nunca se escribia.
        assert guardado["clave"].startswith("test:")
        assert guardado["valor"] is False
    finally:
        L.cerrar()


def test_leer_hasta_tx_es_un_prefijo(lib):
    lib.append(_objetivo())
    lib.append({"t": "tx", "op": "add", "id": "TX-0001", "banda": "E",
                "quien": "harness", "origen": "derivado", "texto": "commit",
                "prov": {"tipo": "derivada", "fn": "commit", "base": []}})
    lib.append(_objetivo("posterior"))
    assert [e["n"] for e in lib.leer(hasta_tx="TX-0001")] == [1, 2]
    with pytest.raises(LibroCaido):
        lib.leer(hasta_tx="TX-9999")


# =====================================================================
# REGRESION 2026-08-19 -- los tres agujeros del almacen
# =====================================================================

def test_la_firma_cubre_origen_conf_estado_y_quien(lib):
    """El sha v1 NO firmaba los cuatro campos que deciden si una fila vale.

    MEDIDO: {origen:'modelo', conf:0.30, estado:'hipotesis'} y
    {origen:'medido', conf:1.00, estado:'verificado'} daban EL MISMO sha, y los
    dos pasaban validar(). Con eso, cambiando dos palabras en una linea del
    fichero, una frase del modelo se convertia en base MEDIDA valida para
    tool.decidir: `_parsear` no veia nada (sha casa, prev casa) y fsck decia OK.
    """
    lib.append({"t": "hecho", "op": "add", "id": "F-1", "banda": "F",
                "quien": "ejecutor", "origen": "modelo", "estado": "hipotesis",
                "texto": "el bug esta arreglado",
                "prov": {"tipo": "derivada", "fn": "x"}})
    ev = json.loads(open(lib.ruta, encoding="utf-8").read().splitlines()[0])
    assert ev["v"] == L.VERSION_EVENTO
    forjado = dict(ev, origen="medido", conf=1.00, estado="verificado")
    with open(lib.ruta, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(forjado, ensure_ascii=True,
                            separators=(",", ":")) + "\n")
    otro = L.Libro(lib.dir)
    assert otro.leer() == [], "el forjado tiene que romper la cadena"
    inf = otro.fsck()
    assert inf["ok"] is False and "sha no casa" in inf["motivo"]


def test_la_firma_vieja_se_acepta_pero_se_marca_como_DEBIL(lib):
    """Los libros ya escritos (sin `v`) siguen leyendose -- versionar sin
    poder leer lo anterior seria borrar la memoria de las tareas abiertas --
    pero fsck dice que su garantia es mas floja en vez de darlos por buenos."""
    viejo = {"t": "hecho", "op": "add", "id": "F-1", "banda": "F",
             "quien": "ejecutor", "origen": "medido", "conf": 1.0,
             "estado": "verificado", "texto": "viejo", "ciclo": 0, "refs": [],
             "ts": 0.0, "prov": {"tipo": "ejecutada", "cmd": "x"}, "n": 1,
             "prev": None}
    viejo["sha"] = L.sha_evento(viejo)          # sin 'v' -> firma v1
    with open(lib.ruta, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(viejo, ensure_ascii=True,
                            separators=(",", ":")) + "\n")
    otro = L.Libro(lib.dir)
    assert len(otro.leer()) == 1
    assert otro.fsck()["firma_debil"] == [1]


def test_sanear_no_borra_los_eventos_buenos_de_detras_del_corte(lib):
    """`/libro fsck --reparar` truncaba desde la PRIMERA linea mala tanto si
    era una cola parcial (correcto) como si la corrupcion estaba en medio
    (mal): reproducido, 5 eventos con la linea 3 corrompida perdian 757 bytes
    -- los eventos 3, 4 y 5, DOS de ellos con JSON y sha perfectos -- y el CLI
    lo llamaba 'cola parcial recortada'. Sin copia, ademas."""
    for i in range(5):
        lib.append({"t": "hecho", "op": "add", "banda": "F", "quien": "ejecutor",
                    "origen": "medido", "texto": "evento %d" % i,
                    "prov": {"tipo": "ejecutada", "cmd": "x"}})
    with open(lib.ruta, "rb") as fh:
        lineas = fh.read().split(b"\n")
    lineas[2] = lineas[2][:20] + b"XX" + lineas[2][22:]
    with open(lib.ruta, "wb") as fh:
        fh.write(b"\n".join(lineas))

    saneo = L.Libro(lib.dir)._sanear()
    assert saneo["solo_cola"] is False, "no fue una escritura cortada"
    assert saneo["eventos_rescatados"] == 2, "los dos intactos de detras"
    assert os.path.exists(saneo["respaldo"]), "la copia entera, antes de tocar"
    assert os.path.exists(saneo["huerfanos"])
    rescatados = open(saneo["huerfanos"], encoding="utf-8").read().splitlines()
    assert len(rescatados) == 2
    assert all(json.loads(r)["sha"] for r in rescatados)


def test_sanear_no_deja_el_libro_en_cero_bytes(lib):
    """`open(ruta,'wb')` TRUNCA antes de escribir: un corte en esa ventana
    dejaba la memoria de la tarea vacia. Y no es un camino raro -- `append`
    llama a `_sanear` en CADA escritura. Ahora es tmp + fsync + os.replace,
    igual que `escribir_cabecera` 40 lineas mas abajo."""
    import inspect
    fuente = inspect.getsource(L.Libro._sanear)
    assert "os.replace" in fuente
    assert "open(self.ruta, \"wb\")" not in fuente

    lib.append(_objetivo())
    with open(lib.ruta, "ab") as fh:
        fh.write(b'{"t":"hecho","op":"add"')          # cola cortada
    lib.append(_objetivo("otro mas"))
    eventos = L.Libro(lib.dir).leer()
    assert [e["texto"] for e in eventos][:2] == ["cablear el canal de estado",
                                                 "otro mas"]
    # Y la constancia dice que fue una COLA, porque esta vez si lo fue.
    assert any("cola parcial" in str(e.get("texto")) for e in eventos)
