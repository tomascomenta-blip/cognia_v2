# -*- coding: utf-8 -*-
"""
test_autoprueba_guion.py — el "de inicio a fin" de un script de consola.

POR QUE EXISTE: hasta el 2026-08-29 la fase 'arranca' lanzaba el producto con
stdin=DEVNULL y PERDONABA el EOFError, asi que 9 de los 43 productos python de
la biblioteca real "arrancaban" muriendo de teclado sin ejecutar una sola de sus
funciones, y se llevaban los 3 puntos de 'arranca' igual.

ESTOS TESTS EJERCEN EL SUBPROCESO DE VERDAD (nada de mocks): cada uno escribe un
.py real en tmp_path, lo corre con `probar_producto` y afirma sobre EFECTOS
OBSERVABLES — el stdout que produjo, el fichero que dejo en disco, el codigo de
salida y el .autoprueba.json cacheado.

Las tres propiedades que se fijan:
  1. CON GUION el programa llega al final y su logica se ejecuta.
  2. BRAZO B: la MISMA corrida con OTRO guion (mismas lineas, otros valores). Si
     el stdout no cambia, la salida no depende del valor tecleado
     (no_reacciona=True). Es un DATO, no un fallo.
  3. La excusa del EOFError se retira SOLO donde toca: con guion suministrado un
     EOFError es INDETERMINADO (el guion se quedo corto), no "arranco".

CORRECCION DEL 2026-08-30 — POR QUE EL SEGUNDO BRAZO YA NO ES "SIN GUION":
  el brazo nulo corria con stdin=DEVNULL, asi que todo producto con un input()
  que no fuera lo ultimo moria de EOFError ANTES de imprimir el resto y los dos
  stdout diferian siempre. Media "sobrevive al EOF", no "usa el valor": 5/7 de
  acierto sobre formas con verdad conocida, y 3 SANOS CONDENADOS — entre ellos
  el informe honesto que acaba en `input("Pulsa Enter para salir...")`, que
  imprime su prompt antes de leer, muere ahi en el brazo nulo, da los dos stdout
  identicos byte a byte y se llevaba un `ok=False` con la acusacion falsa "no
  ejecuta su logica, solo imprime" (y sin traceback, asi que el lazo de
  reparacion no podia repararlo NUNCA: sello permanente e infalseable).
  Con los dos brazos guionados el EOF cae en el mismo punto en ambos: 7/7.
  Y `no_reacciona` ya NO reprueba, porque no hay corte en esta metrica que
  separe `print("hola"); input("enter")` de ese informe de ventas: son la misma
  forma. Lo que los separa es el CUERPO, y eso ya lo mide sin_stubs.
"""

import json
from pathlib import Path

import pytest

from cognia.autoprueba import (
    NOMBRE_CACHE_GUION,
    derivar_guion,
    descubrir_productos,
    evaluar_producto,
    guion_para,
    guion_variante,
    lee_teclado,
    probar_producto,
    probar_todos,
    salida_de_menu,
)

# ── Productos sinteticos REALES (se ejecutan de verdad) ────────────────────────

# Lee DOS entradas y CALCULA con ellas: sin teclado no puede llegar al resultado.
DOS_INPUTS = '''"""Suma dos numeros que teclea el usuario y deja el total en disco."""


def main():
    a = int(input("primer numero? "))
    b = int(input("segundo numero? "))
    total = a + b
    print("TOTAL:", total)
    with open("resultado.txt", "w", encoding="utf-8") as fh:
        fh.write(str(total))


if __name__ == "__main__":
    main()
'''

# Menu en bucle: UN solo input() en el fuente y muchas respuestas necesarias.
MENU = '''"""Menu de opciones con salida por 0."""


def main():
    while True:
        opcion = input("elige una opcion (0 para salir): ")
        if opcion.strip() == "0":
            print("ADIOS")
            return
        print("hiciste la opcion", opcion)


if __name__ == "__main__":
    main()
'''

# Pide teclado pero NO usa lo que le teclean: la salida es identica con y sin.
IGNORA_LA_ENTRADA = '''"""Imprime siempre lo mismo aunque le teclees."""

import sys


def main():
    print("informe fijo")
    print("linea 2")
    try:
        sys.stdin.read()
    except Exception:
        pass


if __name__ == "__main__":
    main()
'''

# Pide MUCHAS mas entradas de las que caben en el guion -> el guion se queda corto.
INSACIABLE = '''"""Pide entradas para siempre."""

n = 0
while True:
    input("dame otra? ")
    n += 1
    print("van", n)
'''

# EL CASO DECISIVO — un producto SANO que el brazo nulo condenaba.
# Calcula, imprime su informe ENTERO y acaba en "Pulsa Enter para salir". Como
# imprime el prompt ANTES de leer, con stdin cerrado moria justo ahi y los dos
# stdout salian identicos byte a byte: `no_reacciona=True` -> `ok=False` con la
# acusacion falsa "no ejecuta su logica, solo imprime", y sin traceback que
# mandar a reparar, o sea sello permanente e infalseable.
PULSA_ENTER = '''"""Informe de ventas: calcula, ensena el resumen y espera al usuario."""

VENTAS = {"enero": 120, "febrero": 340, "marzo": 90}


def total(v):
    return sum(v.values())


def mejor_mes(v):
    return max(v, key=v.get)


def main():
    print("=== INFORME DE VENTAS ===")
    for mes, n in VENTAS.items():
        print("  %-10s %5d" % (mes, n))
    print("  TOTAL      %5d" % total(VENTAS))
    print("  mejor mes: %s" % mejor_mes(VENTAS))
    input("Pulsa Enter para salir...")


if __name__ == "__main__":
    main()
'''

# No lee teclado en absoluto: no hay guion ni brazo B que valga.
SIN_TECLADO = '''"""No lee nada del usuario."""


def main():
    print("hecho sin preguntar nada")
    print("segunda linea")


if __name__ == "__main__":
    main()
'''


def _biblioteca(tmp_path, productos):
    base = tmp_path / "generated_programs"
    base.mkdir()
    for carpeta, archivos in productos.items():
        d = base / carpeta
        d.mkdir()
        for nombre, contenido in archivos.items():
            (d / nombre).write_text(contenido, encoding="utf-8")
    (base / "index.json").write_text("[]", encoding="utf-8")
    return base


def _uno(base, carpeta):
    prods = [p for p in descubrir_productos(base) if Path(p["directorio"]).name == carpeta]
    assert prods, f"no se descubrio {carpeta}"
    return prods[0]


# ── 1. Derivar el guion del propio fuente ─────────────────────────────────────

def test_deriva_una_respuesta_por_cada_input_del_fuente():
    guion, origen = derivar_guion(DOS_INPUTS)
    assert origen == "derivado"
    # "primer numero?" y "segundo numero?" -> el patron de numero contesta 7.
    assert guion[:2] == ["7", "7"]
    # Cola NUMERICA porque todo lo que pide son numeros: teclearle una "q" a un
    # int(input(...)) fabrica un ValueError que no es del producto (paso de
    # verdad con stem_encryptor el 2026-08-29).
    assert guion[-2:] == ["0", "0"]


def test_la_cola_del_guion_es_numerica_si_todo_lo_que_pide_son_numeros():
    solo_numeros, _ = derivar_guion('a = int(input("cuantos elementos? "))\n')
    assert solo_numeros[-2:] == ["0", "0"]
    con_texto, _ = derivar_guion('n = input("tu nombre? ")\n')
    assert con_texto[-2:] == ["0", "q"]


def test_el_prompt_decide_que_se_teclea():
    guion, origen = derivar_guion('nombre = input("como te llamas? nombre: ")\n')
    assert origen == "derivado" and guion[0] == "Cognia"
    guion2, _ = derivar_guion('op = input("elige una opcion del menu: ")\n')
    assert guion2[0] == "1"


def test_sin_teclado_no_hay_guion():
    assert lee_teclado(SIN_TECLADO) is False
    assert derivar_guion(SIN_TECLADO) == ([], "sin_teclado")


def test_input_con_prompt_en_variable_cae_al_generico():
    codigo = 'pregunta = "que?"\nx = input(pregunta)\n'
    guion, origen = derivar_guion(codigo)
    assert origen == "generico" and guion[0] == "1"


# ── 2. Con guion el producto se EJECUTA de verdad (efecto observable) ─────────

def test_con_guion_ejecuta_su_logica_y_deja_el_fichero_en_disco(tmp_path):
    """El efecto observable es un FICHERO: sin teclado nunca se habria escrito."""
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    prod = _uno(base, "suma")
    res = probar_producto(prod, timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]

    assert arr["ok"] is True, arr["detalle"]
    assert arr["origen_guion"] == "derivado"
    assert "TOTAL: 14" in arr["stdout"]                 # 7 + 7, del guion derivado
    assert (base / "suma" / "resultado.txt").read_text(encoding="utf-8") == "14"
    assert res["fallo_duro"] is None
    assert evaluar_producto(prod, res)["desglose"]["arranca"] == 3.0


def test_el_brazo_B_teclea_OTROS_valores_y_el_producto_los_usa(tmp_path):
    """
    El brazo B corre el MISMO programa con OTRO guion, no con stdin cerrado.

    Efecto observable: los dos brazos suman numeros DISTINTOS. 7+7=14 en el
    brazo A, 3+3=6 en el B. Eso es lo que significa "usa el valor tecleado", y
    es imposible de confundir con "sobrevivio al EOF".
    """
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    res = probar_producto(_uno(base, "suma"), timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]

    assert arr["no_reacciona"] is False
    assert arr["no_reacciona_decidible"] is True
    assert "TOTAL: 14" in arr["stdout"]                  # 7 + 7
    assert "TOTAL: 6" in arr["brazo_b"]["stdout"]        # 3 + 3
    # Y el brazo B TIENE guion: si volviera a ser el brazo nulo, esto seria [].
    assert arr["brazo_b"]["guion"][:2] == ["3", "3"]
    assert len(arr["brazo_b"]["guion"]) == len(arr["guion"])


def test_lo_que_queda_en_DISCO_es_del_brazo_A(tmp_path):
    """
    Los dos brazos corren en la MISMA carpeta, asi que el ultimo pisa lo que el
    producto escriba. El que manda es el A (es el que da el veredicto y el que
    se cita en el sello), asi que corre el ULTIMO. Con el orden al reves este
    fichero decia 6 (3+3, los valores del brazo B) en vez de 14.
    """
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    res = probar_producto(_uno(base, "suma"), timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]

    assert "TOTAL: 6" in arr["brazo_b"]["stdout"]        # el brazo B corrio
    assert (base / "suma" / "resultado.txt").read_text(encoding="utf-8") == "14"


def test_el_menu_en_bucle_llega_a_su_salida(tmp_path):
    """UN input() en el fuente, muchas respuestas: el guion se alarga y sale por 0."""
    base = _biblioteca(tmp_path, {"menu": {"program.py": MENU}})
    res = probar_producto(_uno(base, "menu"), timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]
    assert arr["ok"] is True, arr["detalle"]
    assert "ADIOS" in arr["stdout"]        # llego a la rama de salida
    assert arr["rc"] == 0


# ── 3. Brazo B: mide el VALOR, y es un dato — no una condena ──────────────────

def test_el_guion_variante_cambia_valores_y_respeta_la_salida():
    """
    La pieza que hace honesta la medida: MISMAS lineas, OTROS valores, y los
    tokens de salida intactos. Si el variante cambiara el "0" de un menu, el
    brazo B no llegaria a su despedida y la diferencia mediria el CAMINO, no el
    valor tecleado.
    """
    original = ["7", "Cognia", "s", "datos.txt", "0", "q"]
    variante = guion_variante(original)
    assert len(variante) == len(original)
    assert variante[-2:] == ["0", "q"]            # sentinelas de salida, intactos
    assert variante[:4] == ["3", "Zenta", "n", "otros.txt"]
    # Y es idempotente en forma: nunca devuelve el mismo valor para un no-centinela.
    for antes, despues in zip(original[:4], variante[:4]):
        assert antes != despues


def test_producto_que_ignora_la_entrada_se_ANOTA_pero_NO_se_reprueba(tmp_path):
    """
    EL CAMBIO DE 2026-08-30. Este programa arranca, sale con 0 y no revienta,
    pero su stdout es identico con los dos guiones: no usa lo que le teclean.

    Eso se ANOTA (`no_reacciona=True`, y sale en el detalle y en el sello) y NO
    reprueba. Razon medida: el mismo detector, cuando reprobaba, condenaba a 3
    de 7 productos SANOS, y la forma que condena aqui (imprimir algo fijo y
    tirar lo tecleado) es exactamente la del informe de PULSA_ENTER, que es
    sano. No existe corte en esta metrica que separe los dos.
    """
    base = _biblioteca(tmp_path, {"fijo": {"program.py": IGNORA_LA_ENTRADA}})
    prod = _uno(base, "fijo")
    res = probar_producto(prod, timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]

    assert arr["no_reacciona"] is True                       # el dato se mide
    assert arr["no_reacciona_decidible"] is True
    assert arr["stdout"] == arr["brazo_b"]["stdout"]
    assert "no depende del valor tecleado" in arr["detalle"]  # y se dice
    assert arr["ok"] is True, arr["detalle"]                 # pero no condena
    assert res["fallo_duro"] is None
    assert evaluar_producto(prod, res)["desglose"]["arranca"] == 3.0


def test_el_informe_que_acaba_en_PULSA_ENTER_no_se_condena(tmp_path):
    """
    LA REGRESION QUE NO PUEDE VOLVER (medida por el revisor el 2026-08-29).

    Todo programa de consola que termine en "pulsa Enter para salir" imprime su
    prompt ANTES de leer y moria justo ahi en el brazo nulo: los dos stdout
    salian identicos byte a byte -> `ok=False` -> sello `verificado=False` con
    una acusacion FALSA, y sin traceback que reparar, o sea INFALSEABLE.

    Aqui se ejerce entero: corre, imprime su informe, y sale con 3/3 puntos.
    """
    base = _biblioteca(tmp_path, {"informe": {"program.py": PULSA_ENTER}})
    prod = _uno(base, "informe")
    res = probar_producto(prod, timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]

    assert arr["ok"] is True, arr["detalle"]
    assert res["fallo_duro"] is None
    assert "TOTAL        550" in arr["stdout"]     # ejecuto su logica de verdad
    assert "mejor mes: febrero" in arr["stdout"]
    assert arr["rc"] == 0
    # El dato honesto SI se anota: no usa el valor tecleado, y no pasa nada.
    assert arr["no_reacciona"] is True
    assert "NO REACCIONA" not in arr["detalle"]
    assert evaluar_producto(prod, res)["desglose"]["arranca"] == 3.0


def test_dos_brazos_mudos_no_se_condenan(tmp_path):
    """
    CONTRA-REGLA. Un juego que dibuja pero no imprime nada deja los DOS brazos
    con stdout vacio: identicos, pero la metrica no midio nada. Se dice que no
    es decidible en vez de inventarse un veredicto.
    """
    mudo_interactivo = ('import sys\n'
                        'sys.stdin.readline()\n'
                        'sys.stderr.write("dibujando\\n")\n')
    base = _biblioteca(tmp_path, {"grafico": {"program.py": mudo_interactivo}})
    res = probar_producto(_uno(base, "grafico"), timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]
    assert arr["no_reacciona"] is True            # los stdout son iguales (vacios)
    assert arr["no_reacciona_decidible"] is False
    assert arr["ok"] is True, arr["detalle"]      # pero NO se le reprueba por eso
    assert "no decidible" in arr["detalle"]


def test_guion_de_solo_sentinelas_no_es_decidible(tmp_path):
    """
    El otro modo de "no medi nada": si el guion es todo tokens de salida, el
    variante es IGUAL al original y los dos brazos reciben lo mismo por
    construccion. Decir que el producto "no reacciona" ahi seria mentir.
    """
    base = _biblioteca(tmp_path, {"menu": {"program.py": MENU}})
    (base / "menu" / NOMBRE_CACHE_GUION).write_text(
        json.dumps({"guion": ["0", "q"], "origen": "a_mano"}), encoding="utf-8")
    res = probar_producto(_uno(base, "menu"), timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]

    assert arr["brazo_b"]["guion"] == arr["guion"] == ["0", "q"]
    assert arr["no_reacciona"] is True
    assert arr["no_reacciona_decidible"] is False
    assert arr["ok"] is True, arr["detalle"]
    assert "todo tokens de salida" in arr["detalle"]


# ── 4. La excusa del EOFError, retirada solo donde toca ───────────────────────

def test_guion_corto_es_INDETERMINADO_no_arranco(tmp_path):
    base = _biblioteca(tmp_path, {"insaciable": {"program.py": INSACIABLE}})
    prod = _uno(base, "insaciable")
    res = probar_producto(prod, timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]

    assert arr["ok"] is None, arr["detalle"]            # ni verde ni rojo
    assert arr["indeterminado"] is True
    assert "INDETERMINADO" in arr["detalle"]
    assert res["fallo_duro"] is None                    # no se culpa al producto
    assert res["indeterminado"] == "arranca"
    # Media nota: no se sabe que arranco, pero tampoco revento.
    assert evaluar_producto(prod, res)["desglose"]["arranca"] == 1.5


def test_sin_guion_posible_la_regla_vieja_sigue_viva(tmp_path):
    """Un producto que no lee teclado se corre UNA vez, como siempre."""
    base = _biblioteca(tmp_path, {"mudo": {"program.py": SIN_TECLADO}})
    res = probar_producto(_uno(base, "mudo"), timeout_arranque=8, timeout_import=8)
    arr = res["fases"]["arranca"]
    assert arr["ok"] is True
    assert arr["guion"] == [] and arr["origen_guion"] == "sin_teclado"
    assert arr["brazo_b"] is None and arr["no_reacciona"] is None
    assert "hecho sin preguntar" in arr["stdout"]


# ── 5. Cache del guion junto al producto ──────────────────────────────────────

MENU_QUE_SALE_CON_4 = '''def menu():
    total = 0
    while True:
        print("1. Sumar  2. Ver  4. Salir")
        op = input("Elige opcion: ").strip()
        if op == "1":
            total += int(input("Numero: "))
        elif op == "2":
            print("TOTAL:", total)
        elif op == "4":
            print("Adios,", total)
            return
        else:
            print("no valida")


if __name__ == "__main__":
    menu()
'''


def test_la_opcion_de_salida_se_lee_del_fuente():
    """LA mejora de 2026-08-30: el menu mas comun no sale con 0 ni con q."""
    assert salida_de_menu('print("1. Agregar  2. Listar  3. Buscar  4. Salir")') == "4"
    assert salida_de_menu('print("[3] Exit")') == "3"
    assert salida_de_menu('print("Salir (5)")') == "5"
    assert salida_de_menu('print("0. Salir")') == ""      # 0 ya esta en la cola
    assert salida_de_menu('print("1. Jugar  2. Ver")') == ""


def test_un_menu_que_sale_con_4_LLEGA_a_su_despedida(tmp_path):
    """Antes cerraba INDETERMINADO ('el guion se quedo corto'): el programa
    estaba perfecto y la prueba no podia emitir veredicto. Medido en la tarea
    real de la agenda de contactos."""
    base = _biblioteca(tmp_path, {"agenda": {"program.py": MENU_QUE_SALE_CON_4}})
    prod = _uno(base, "agenda")
    res = probar_producto(prod, timeout_arranque=10, timeout_import=8)
    arranca = res["fases"]["arranca"]
    assert arranca["ok"] is True, arranca["detalle"]
    assert "Adios" in arranca["stdout"]
    assert res["fallo_duro"] is None and res["indeterminado"] is None


def test_el_brazo_B_no_le_quita_la_salida_al_menu():
    """Si el brazo B cambiara el 4 por otro numero, mediria OTRO camino."""
    guion = ["1", "7", "4", "0", "q"]
    assert guion_variante(guion, salida="4")[2] == "4"
    assert guion_variante(guion)[2] != "4"      # sin decirselo, es un valor mas


def test_el_guion_se_cachea_en_autoprueba_json(tmp_path):
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    prod = _uno(base, "suma")
    guion, origen = guion_para(prod)
    ruta = base / "suma" / NOMBRE_CACHE_GUION
    assert ruta.is_file()
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["guion"] == guion and datos["origen"] == origen == "derivado"


def test_el_fichero_escrito_a_mano_MANDA_sobre_el_regex(tmp_path):
    """El dueno escribe el guion real de su juego y la autoprueba lo respeta."""
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    (base / "suma" / NOMBRE_CACHE_GUION).write_text(
        json.dumps({"guion": ["20", "22"], "origen": "a_mano"}), encoding="utf-8")
    prod = _uno(base, "suma")
    assert guion_para(prod) == (["20", "22"], "a_mano")

    res = probar_producto(prod, timeout_arranque=8, timeout_import=8)
    assert "TOTAL: 42" in res["fases"]["arranca"]["stdout"]      # 20 + 22
    assert (base / "suma" / "resultado.txt").read_text(encoding="utf-8") == "42"


def test_un_guion_DERIVADO_caduca_cuando_cambia_el_fuente(tmp_path):
    """LA regresion de 2026-08-30: la cache condenaba a un sano tras reparar.

    Medido tecleando una tarea real con /revision: el modelo escribio un conversor que
    pedia texto, se cacheo el guion generico de texto, la revision lo reprobo, el modelo
    lo REESCRIBIO para pedir numeros -- y la segunda pasada le siguio tecleando "hola
    mundo cognia hola" al programa NUEVO, que contestaba "necesito el monto" y salia con
    exit 1. El producto funcionaba: el instrumento estaba midiendo la version anterior.
    """
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    prod = _uno(base, "suma")
    primero, _ = guion_para(prod)
    ruta = base / "suma" / NOMBRE_CACHE_GUION
    assert json.loads(ruta.read_text(encoding="utf-8"))["huella"]

    # el modelo reescribe el programa: ahora pide OTRA cosa
    (base / "suma" / "program.py").write_text(
        'nombre = input("Como te llamas? ")\nprint("hola", nombre)\n', encoding="utf-8")
    segundo, origen = guion_para(_uno(base, "suma"))
    assert segundo != primero, "el guion viejo se reuso sobre un fuente distinto"
    assert origen == "derivado"


def test_un_guion_SIN_huella_sigue_mandando(tmp_path):
    """El contrato de arriba no cambia: solo caduca lo que el modulo dedujo SOLO.
    Un fichero escrito a mano (o de una version anterior) no trae huella y manda."""
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    (base / "suma" / NOMBRE_CACHE_GUION).write_text(
        json.dumps({"guion": ["20", "22"], "origen": "a_mano"}), encoding="utf-8")
    (base / "suma" / "program.py").write_text(
        'x = input("otra cosa? ")\nprint(x)\n', encoding="utf-8")
    assert guion_para(_uno(base, "suma")) == (["20", "22"], "a_mano")


def test_cache_apagable_por_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_AUTOPRUEBA_CACHE", "0")
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    guion, _ = guion_para(_uno(base, "suma"))
    assert guion                                     # el guion se deriva igual
    assert not (base / "suma" / NOMBRE_CACHE_GUION).exists()   # pero no se escribe


def test_cache_corrupta_no_rompe_nada(tmp_path):
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS}})
    (base / "suma" / NOMBRE_CACHE_GUION).write_text("{esto no es json", encoding="utf-8")
    guion, origen = guion_para(_uno(base, "suma"))
    assert origen == "derivado" and guion[:2] == ["7", "7"]


# ── 6. Los contadores del reporte ─────────────────────────────────────────────

def test_el_reporte_cuenta_guiones_y_no_reaccionan(tmp_path):
    """
    El contador sigue existiendo — lo que cambia es que ya no baja la nota de
    nadie: 2 productos "no usan el valor tecleado" y CERO fallos duros.
    """
    base = _biblioteca(tmp_path, {"suma": {"program.py": DOS_INPUTS},
                                  "fijo": {"program.py": IGNORA_LA_ENTRADA},
                                  "informe": {"program.py": PULSA_ENTER},
                                  "mudo": {"program.py": SIN_TECLADO}})
    rep = probar_todos(base=base, timeout_arranque=8)
    assert rep["total"] == 4
    assert rep["con_guion"] == 3          # suma, fijo e informe leen teclado
    assert rep["no_reaccionan"] == 2      # fijo e informe: se cuentan...
    assert rep["indeterminados"] == 0
    # ...y no condenan a nadie: los 4 arrancan.
    assert rep["arrancan"] == 4
    assert [e["fallo_duro"] for e in rep["evaluaciones"]] == [None] * 4
