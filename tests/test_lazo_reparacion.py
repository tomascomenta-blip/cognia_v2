# -*- coding: utf-8 -*-
"""
test_lazo_reparacion.py — el lazo probar -> reparar -> reprobar, CABLEADO.

POR QUE EXISTE: hasta el 2026-08-29 `reintentar_si_falla()` redactaba el pedido
de correccion con el error medido y NO TENIA UN SOLO LLAMADOR en todo el repo.
El cableado estaba escrito COMO COMENTARIO al final de verificacion.py y nunca
se aplico. Consecuencia medida: 24 productos con verificado=false intactos en
disco desde julio.

QUE EJERCEN ESTOS TESTS (y por que no son un mock de teatro): los productos son
.py y .html REALES en tmp_path, la verificacion corre los subprocesos de verdad
(compila/importa/arranca/sin_stubs) y las aserciones son sobre EFECTOS
OBSERVABLES: el contenido del fichero en disco DESPUES del lazo, el
.verificacion.json escrito al lado, el numero de llamadas al reparador y el
puntaje medido. Lo unico inyectado es `reparar_fn`, que en produccion habla con
el modelo: por eso existe la inyeccion, para poder probar el lazo sin backend.
"""

import json
from pathlib import Path

import pytest

from cognia.program_creator.verificacion import (
    MAX_REPARACIONES_LAZO,
    NOMBRE_SELLO,
    error_accionable,
    lazo_reparacion,
    leer_sello,
    verificar_al_crear,
)

# ── Productos sinteticos ──────────────────────────────────────────────────────

ROTO_EN_RUNTIME = '''"""Divide dos numeros y muestra el resultado."""


def dividir(a, b):
    return a / b


def main():
    print("dividiendo")
    print(dividir(10, 0))


if __name__ == "__main__":
    main()
'''

SANO = '''"""Divide dos numeros y muestra el resultado."""


def dividir(a, b):
    if b == 0:
        return None
    return a / b


def main():
    print("dividiendo")
    print(dividir(10, 2))


if __name__ == "__main__":
    main()
'''

NO_COMPILA = '''"""Sumador roto."""


def sumar(a, b:
    return a + b


print(sumar(1, 2))
'''

# Igual de roto que el original, pero DISTINTO: mueve el sintoma sin arreglarlo.
OTRO_ROTO = '''"""Divide dos numeros y muestra el resultado."""


def dividir(a, b):
    return a / b


def main():
    print("dividiendo")
    print(dividir(10, int("no soy un numero")))


if __name__ == "__main__":
    main()
'''

# Peor que el original: ya ni compila. Sirve para probar la restauracion.
PEOR = '''def main(
    print("me cargue el parentesis")
'''


def _producto(tmp_path, nombre, archivos, index=None):
    base = tmp_path / "generated_programs"
    base.mkdir(exist_ok=True)
    if not (base / "index.json").exists():
        (base / "index.json").write_text(json.dumps(index or []), encoding="utf-8")
    d = base / nombre
    d.mkdir()
    for fichero, contenido in archivos.items():
        (d / fichero).write_text(contenido, encoding="utf-8")
    return d


class Reparador:
    """reparar_fn inyectado que devuelve respuestas fijadas y cuenta llamadas."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, pedido, codigo, archivo, lenguaje=None):
        self.llamadas.append({"pedido": pedido, "codigo": codigo,
                              "archivo": archivo, "lenguaje": lenguaje})
        if not self.respuestas:
            return None
        return self.respuestas.pop(0)


# ── 1. Producto roto -> UNA vuelta -> verificado, y el DISCO cambio ───────────

def test_producto_roto_se_repara_en_una_vuelta_y_el_fichero_cambia(tmp_path):
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    antes = (d / "program.py").read_text(encoding="utf-8")
    assert verificar_al_crear(d)["ok"] is False        # de partida NO corre

    rep = Reparador(SANO)
    res = lazo_reparacion(d, reparar_fn=rep)

    assert res["ok"] is True, res["motivo_corte"]
    assert res["intentos"] == 1 and len(rep.llamadas) == 1
    assert res["motivo_corte"] == "reparado al intento 1"
    # EFECTO OBSERVABLE: el fichero en disco es OTRO, y ahora corre.
    ahora = (d / "program.py").read_text(encoding="utf-8")
    assert ahora != antes and ahora == SANO
    assert verificar_al_crear(d)["ok"] is True
    # Y el error inicial quedo registrado con su nombre propio.
    assert "ZeroDivisionError" in res["error_inicial"]
    assert res["error_final"] == ""


def test_el_pedido_que_recibe_el_reparador_trae_el_error_MEDIDO(tmp_path):
    """Un pedido sin el error exacto es el parcheo a ciegas que la regla 11 prohibe."""
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    rep = Reparador(SANO)
    lazo_reparacion(d, reparar_fn=rep)

    pedido = rep.llamadas[0]["pedido"]
    assert "PEDIDO DE CORRECCION (intento 1/2)" in pedido
    assert "program.py" in pedido
    assert "ZeroDivisionError" in pedido               # el error, literal
    assert "ERROR EXACTO (medido corriendolo, no es una opinion)" in pedido
    # Y se le pasa el codigo TAL COMO ESTA EN DISCO, no otra version.
    assert rep.llamadas[0]["codigo"] == ROTO_EN_RUNTIME
    assert Path(rep.llamadas[0]["archivo"]).name == "program.py"


def test_tambien_repara_un_fallo_de_compilacion(tmp_path):
    d = _producto(tmp_path, "sumador", {"program.py": NO_COMPILA})
    res = lazo_reparacion(d, reparar_fn=Reparador(SANO))
    assert res["ok"] is True
    assert (d / "program.py").read_text(encoding="utf-8") == SANO


# ── 2. Irreparable: para en 2 y el sello lo cuenta ───────────────────────────

def test_irreparable_para_en_dos_y_el_sello_dice_la_verdad(tmp_path):
    """
    TOPE 2, no 3: el tercer intento del creador ya esta medido como parcheo a
    ciegas. Cada respuesta MUEVE el sintoma (si no, corta antes el Disyuntor).
    """
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    rep = Reparador(OTRO_ROTO, ROTO_EN_RUNTIME.replace("10, 0", "20, 0"))
    res = lazo_reparacion(d, reparar_fn=rep)

    assert res["ok"] is False
    assert res["intentos"] == MAX_REPARACIONES_LAZO == 2
    assert len(rep.llamadas) == 2                     # ni una llamada de mas
    assert res["error_inicial"] and res["error_final"]
    assert "ZeroDivisionError" in res["error_inicial"]

    sello = leer_sello(d)
    assert sello is not None and (d / NOMBRE_SELLO).is_file()
    assert sello["verificado"] is False
    assert sello["intentos"] == 2
    assert "ZeroDivisionError" in sello["error_inicial"]
    assert sello["error_final"]
    assert sello["motivo_corte"]


def test_una_reparacion_que_EMPEORA_no_se_queda_en_disco(tmp_path):
    """El producto entra roto en runtime y sale roto en runtime, no sin compilar."""
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    res = lazo_reparacion(d, reparar_fn=Reparador(PEOR, PEOR + "\n# otra vez\n"))

    assert res["ok"] is False
    assert res["restaurado"] is True
    assert (d / "program.py").read_text(encoding="utf-8") == ROTO_EN_RUNTIME
    assert "RESTAURADO" in res["motivo_corte"]


def test_una_reparacion_que_EMPATA_tampoco_se_queda_en_disco(tmp_path):
    """
    EL CORTE ES `<=`, NO `<` (medido por el revisor el 2026-08-29).

    Empatar no es empeorar, pero perder el fuente del dueno a cambio de NADA
    tampoco es lo que promete el docstring. En la corrida del revisor los dos
    intentos dieron 5.5 contra 5.5 inicial: no se restauraba, y en disco quedaba
    la reescritura del modelo en vez del original.

    Aqui se afirma primero el EMPATE (si no, el test probaria el caso `<`, que
    ya estaba cubierto) y despues que el original volvio a disco.
    """
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    puntaje_inicial = verificar_al_crear(d)["puntaje"]
    otro = OTRO_ROTO.replace('"no soy un numero"', '"tampoco soy un numero"')
    res = lazo_reparacion(d, reparar_fn=Reparador(OTRO_ROTO, otro))

    assert res["ok"] is False
    # EMPATE, no bajada: es lo que hace decisivo este test.
    assert res["reparaciones"], res["motivo_corte"]
    assert res["reparaciones"][-1]["puntaje_despues"] == puntaje_inicial
    assert res["restaurado"] is True
    assert (d / "program.py").read_text(encoding="utf-8") == ROTO_EN_RUNTIME
    assert "RESTAURADO" in res["motivo_corte"]
    assert "no subia" in res["motivo_corte"]


def test_sin_escritura_en_disco_no_hay_restauracion_que_hacer(tmp_path):
    """
    El respaldo se toma DESPUES de escribir, no antes.

    Con el corte en `<=`, guardarlo antes hacia que un reparador que revienta
    (o que no devuelve nada) entrara igual en la rama de restauracion: no habia
    tocado el disco, `reparaciones` estaba vacia, y el IndexError se lo comia el
    `except Exception: pass` dejando `restaurado=True` con un motivo a medias.
    """
    for nombre, reparador in (("vacio", Reparador()),
                              ("explota", lambda **kw: (_ for _ in ()).throw(
                                  RuntimeError("el backend se cayo")))):
        d = _producto(tmp_path, "divisor_" + nombre, {"program.py": ROTO_EN_RUNTIME})
        res = lazo_reparacion(d, reparar_fn=reparador)
        assert res["ok"] is False
        assert res["restaurado"] is False, res["motivo_corte"]
        assert res["reparaciones"] == []
        assert "RESTAURADO" not in res["motivo_corte"]
        assert (d / "program.py").read_text(encoding="utf-8") == ROTO_EN_RUNTIME
        assert leer_sello(d) is not None                 # se sella igual, honesto


def test_el_disyuntor_corta_cuando_el_sintoma_no_se_mueve(tmp_path):
    """Dos parches con el MISMO sintoma: se deja de adivinar (regla 11 del repo)."""
    igual_de_roto = ROTO_EN_RUNTIME.replace('print("dividiendo")',
                                            'print("dividiendo")  # parche 1')
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    rep = Reparador(igual_de_roto, igual_de_roto + "\n# parche 2\n")
    res = lazo_reparacion(d, reparar_fn=rep)

    assert res["ok"] is False
    # O corta el disyuntor, o se agotan las 2: en ningun caso hay una tercera.
    assert len(rep.llamadas) <= MAX_REPARACIONES_LAZO


# ── 3. Cuando NO hay que reparar (lo caro es llamar al modelo de mas) ─────────

def test_producto_sano_no_llama_al_reparador(tmp_path):
    d = _producto(tmp_path, "ok", {"program.py": SANO})
    rep = Reparador(ROTO_EN_RUNTIME)
    res = lazo_reparacion(d, reparar_fn=rep)

    assert res["ok"] is True and res["intentos"] == 0
    assert rep.llamadas == []
    assert "no hizo falta reparar" in res["motivo_corte"]
    assert leer_sello(d)["verificado"] is True


def test_un_stub_que_CORRE_no_se_manda_a_reparar(tmp_path):
    """
    Un cascaron corre con exit 0: no es un fallo DURO. Mandarlo a reparar
    significa llamar al modelo por productos que funcionan, que es justo el
    coste que este lazo no puede permitirse en el camino de /crear.
    """
    d = _producto(tmp_path, "hueco", {"program.py": "def hacer():\n    pass\n"})
    ver = verificar_al_crear(d)
    assert ver["ok"] is False and ver["fallo_duro"] == "stubs"
    accionable, motivo = error_accionable(ver)
    assert accionable is False and "CORRE" in motivo

    rep = Reparador(SANO)
    res = lazo_reparacion(d, reparar_fn=rep)
    assert rep.llamadas == []
    assert res["ok"] is False and res["intentos"] == 0
    assert leer_sello(d)["verificado"] is False        # honesto, pero sin gastar modelo


def test_carpeta_sin_codigo_no_se_manda_a_reparar(tmp_path):
    d = _producto(tmp_path, "vacia", {})
    (d / "input_images").mkdir()
    rep = Reparador(SANO)
    res = lazo_reparacion(d, reparar_fn=rep)
    assert rep.llamadas == [] and res["ok"] is False
    assert "no hay archivo que corregir" in res["motivo_corte"]


def test_indeterminado_no_se_manda_a_reparar(tmp_path):
    """El guion de teclado se quedo corto: no hay error medido que corregir."""
    insaciable = ('"""Pregunta sin parar, con cuerpo real para no ser un stub."""\n'
                  '\n'
                  'def contar(n):\n'
                  '    total = 0\n'
                  '    for i in range(n):\n'
                  '        total += i\n'
                  '    return total\n'
                  '\n'
                  'def main():\n'
                  '    n = 0\n'
                  '    while True:\n'
                  '        input("dame otro? ")\n'
                  '        n += 1\n'
                  '        print("acumulado", contar(n))\n'
                  '\n'
                  'if __name__ == "__main__":\n'
                  '    main()\n')
    d = _producto(tmp_path, "insaciable", {"program.py": insaciable})
    ver = verificar_al_crear(d)
    assert ver["resultado"]["indeterminado"] == "arranca"
    accionable, motivo = error_accionable(ver)
    assert accionable is False and "indeterminado" in motivo

    rep = Reparador(SANO)
    res = lazo_reparacion(d, reparar_fn=rep)
    assert rep.llamadas == []


# ── 4. Bordes que no pueden tumbar /crear ────────────────────────────────────

def test_reparador_que_devuelve_None_corta_limpio(tmp_path):
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    res = lazo_reparacion(d, reparar_fn=Reparador())     # sin respuestas
    assert res["ok"] is False
    assert "no devolvio codigo nuevo" in res["motivo_corte"]
    assert (d / "program.py").read_text(encoding="utf-8") == ROTO_EN_RUNTIME


def test_reparador_que_revienta_se_reporta_no_se_traga(tmp_path):
    def explota(**kw):
        raise RuntimeError("el backend se cayo")

    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    res = lazo_reparacion(d, reparar_fn=explota)
    assert res["ok"] is False
    assert "el reparador reviento" in res["motivo_corte"]
    assert "RuntimeError" in res["motivo_corte"]
    assert leer_sello(d) is not None                    # se sella igual, honesto


def test_presupuesto_agotado_corta_antes_de_llamar(tmp_path):
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    rep = Reparador(SANO)
    res = lazo_reparacion(d, reparar_fn=rep, presupuesto_seg=0.0)
    assert rep.llamadas == []
    assert "presupuesto agotado" in res["motivo_corte"]


def test_sin_reparador_solo_sella(tmp_path):
    d = _producto(tmp_path, "divisor", {"program.py": ROTO_EN_RUNTIME})
    res = lazo_reparacion(d, reparar_fn=None)
    assert res["ok"] is False
    assert "sin reparador inyectado" in res["motivo_corte"]
    assert leer_sello(d)["verificado"] is False


# ── 5. El sello y el INDICE se reescriben juntos ─────────────────────────────

def test_sello_e_indice_se_actualizan_en_la_misma_pasada(tmp_path):
    """Reescribir el producto sin tocar el index deja un veredicto rancio."""
    base = tmp_path / "generated_programs"
    base.mkdir()
    (base / "index.json").write_text(json.dumps([
        {"id": "divisor", "directory": "divisor", "title": "Divisor",
         "description": "divide numeros", "total_score": 8.0}]), encoding="utf-8")
    d = base / "divisor"
    d.mkdir()
    (d / "program.py").write_text(ROTO_EN_RUNTIME, encoding="utf-8")

    res = lazo_reparacion(d, reparar_fn=Reparador(SANO))
    assert res["ok"] is True

    entradas = json.loads((base / "index.json").read_text(encoding="utf-8"))
    assert entradas[0]["verificado"] is True
    assert entradas[0]["puntaje_real"] == leer_sello(d)["puntaje_real"]
    assert entradas[0]["total_score"] == 8.0           # la nota del juez no se toca
