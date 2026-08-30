# -*- coding: utf-8 -*-
"""E2E de `/flujoteca ejecutar` -- GATE de pre-release del NODO PROMPT.

POR QUE EXISTE (PLAN2, seccion RELEASE paso 2). El nodo de entrada obligatorio
se entrego con 37 tests en verde y ninguno ejecutaba el flujo que
`asegurar_prompt` produce DE VERDAD: los tres ficheros de test escriben
`{{prompt}}` a mano en el flujo. Es el test que pasa por el motivo equivocado.
Este gate corre el flujo POR EL COMANDO -- la misma linea que teclea el dueno,
despachada como en `cognia/cli.py:20914` (`_slash_flujoteca(raw[10:], ai)`) --
y mira el DISCO. Un flujo que dice "OK" y no deja el fichero falla aqui.

QUE MIDE (5 comprobaciones, todas de efecto observable, cero modelo):
  1. el fichero aparece: `/flujoteca ejecutar <n> <prompt>` deja el .txt;
  2. el CONTENIDO lo dicta el prompt del CLI, no el default del nodo;
  3. sin argumento, el default del nodo es el que manda;
  4. `prompt_fijo` corre con la CONSTANTE, ignora el argumento y lo AVISA;
  5. un flujo cuyo nodo de entrada NO se usa (ningun nodo interpola
     `{{prompt}}`) AVISA -- es el defecto que casi se publica: el nodo se
     anade en todo guardado y nadie lo cablea, asi que el texto del dueno no
     llega a ninguna tool y el flujo corre igual, en silencio.

Ninguna comprobacion mira la respuesta de un modelo: el flujo usa `prompt` +
`escribir_archivo`, asi que el veredicto es determinista y tarda segundos.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_flujo_cli.py
Salida: 'E2E FLUJO CLI: N/5 OK'; exit 0 si 5/5, 1 si alguna falla.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
# TODO lo que redirige estado va ANTES de importar cognia (mismo motivo que en
# scripts/e2e_happy_path.py): first_run congela COGNIA_HOME en el import, y
# dev_tools congela AGENT_WORKSPACE_ROOT en el import. Un setdefault tardio
# deja el gate escribiendo en la casa del dueno.
_TMP = Path(tempfile.mkdtemp(prefix="e2eflujo_")).resolve()
_HOME = _TMP / "home"
_FLUJOS = _TMP / "flujoteca"
_WS = _TMP / "ws"
for _d in (_HOME, _FLUJOS, _WS):
    _d.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("COGNIA_EFIMERO", "1")
os.environ["COGNIA_HOME"] = str(_HOME)
os.environ["COGNIA_FLUJOTECA_DIR"] = str(_FLUJOS)
os.environ["COGNIA_AGENT_WORKSPACE"] = str(_WS)
os.environ.setdefault("COGNIA_WORKFLOWS_DIR", str(_TMP / "corridas"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    marca = "OK " if ok else "FAIL"
    linea = "  [" + marca + "] " + nombre
    if detalle:
        linea += " -- " + str(detalle)[:170]
    print(linea, flush=True)


def _plano(texto):
    """Minusculas, sin acentos y con los espacios colapsados.

    El gate compara CONTRA EL TEXTO que ve el dueno, y ese texto lo escribe
    otra persona: exigir la tilde exacta de 'ningun' convertiria el gate en un
    test de redaccion. Se normaliza para que mida el AVISO, no la ortografia."""
    t = " ".join(str(texto).split()).lower()
    for a, b in ((chr(225), "a"), (chr(233), "e"), (chr(237), "i"),
                 (chr(243), "o"), (chr(250), "u"), (chr(241), "n"),
                 (chr(252), "u")):
        t = t.replace(a, b)
    return t


def _flujo(nombre, entrada_tool, entrada_args, args_escritura):
    """Un flujo de dos nodos: la ENTRADA y un `escribir_archivo`.

    `wires` son los SUCESORES (misma convencion que `flows.asegurar_prompt`,
    que cuelga el nodo nuevo de las raices previas)."""
    return {
        "nombre": nombre,
        "descripcion": "gate e2e del nodo de entrada",
        "nodos": [
            {"id": "prompt", "tool": entrada_tool, "args": entrada_args,
             "wires": ["escribe"]},
            {"id": "escribe", "tool": "escribir_archivo",
             "args": args_escritura, "wires": []},
        ],
    }


def main():
    # `apply_config` alinea first_run con el COGNIA_HOME de AHORA (arranque.py
    # explica por que hace falta: las constantes se congelan en el import).
    from cognia.first_run import apply_config
    apply_config()
    from cognia.agent import flujoteca as _ft
    from cognia import cli as _cli
    import cognia.agents.workers.dev_tools as _dev

    # El gate se cae ANTES de medir nada si el aislamiento no agarro: un e2e
    # que escribe en ~/.cognia mide la casa del dueno, no el producto.
    if Path(_ft.dir_base()).resolve() != _FLUJOS:
        print("ABORTA: la flujoteca no es la temporal: " + str(_ft.dir_base()))
        return 2
    raiz = Path(_dev._root_actual()).resolve()
    if raiz != _WS:
        print("ABORTA: el workspace de escritura no es el temporal: " + str(raiz))
        return 2

    # -- se teclea la linea entera y se despacha como el REPL ---------------
    _orig_print, _orig_show = _cli._print_line, _cli._show_response

    def teclear(raw):
        """Corre `raw` (p.ej. '/flujoteca ejecutar x hola') y devuelve TODO lo
        que el comando imprimio. Se ENVUELVE `_print_line`/`_show_response` en
        vez de sustituirlos: el camino real sigue corriendo (colores, modo
        sencillo, filtros) y ademas queda grabado."""
        buf = []

        def _tee_print(text):
            buf.append(str(text))
            return _orig_print(text)

        def _tee_show(texto, *a, **k):
            buf.append(str(texto))
            return _orig_show(texto, *a, **k)

        _cli._print_line, _cli._show_response = _tee_print, _tee_show
        try:
            # La MISMA linea que el REPL (cli.py:20914-20915). Se entra por el
            # handler del comando, no por flows.ejecutar: el defecto que este
            # gate persigue vive en el cableado del comando, no en el motor.
            _cli._slash_flujoteca(raw[len("/flujoteca"):].strip(), None)
        finally:
            _cli._print_line, _cli._show_response = _orig_print, _orig_show
        return "\n".join(buf)

    def leido(nombre):
        p = _WS / nombre
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8", errors="replace")

    t0 = time.time()

    # -- 1 y 2: nodo VARIABLE, cableado, con prompt del CLI ----------------
    _ft.guardar(_flujo("gatevar", "prompt", "DEFECTO_DEL_NODO",
                       "gatevar.txt | {{prompt}}"), nombre="gatevar")
    salida = teclear("/flujoteca ejecutar gatevar HOLA_DEL_CLI")
    cont = leido("gatevar.txt")
    check("1. el comando deja el fichero en disco", cont is not None,
          "esperaba " + str(_WS / "gatevar.txt") + "; salida="
          + " ".join(salida.split())[:110])
    check("2. el contenido lo dicta el PROMPT del CLI",
          cont is not None and cont.strip() == "HOLA_DEL_CLI",
          "contenido=" + repr(cont))

    # -- 3: sin argumento manda el default del nodo ------------------------
    (_WS / "gatevar.txt").unlink(missing_ok=True)
    salida = teclear("/flujoteca ejecutar gatevar")
    cont = leido("gatevar.txt")
    check("3. sin argumento manda el default del nodo",
          cont is not None and cont.strip() == "DEFECTO_DEL_NODO",
          "contenido=" + repr(cont))

    # -- 4: nodo CONSTANTE con argumento: constante + AVISO ----------------
    _ft.guardar(_flujo("gatefijo", "prompt_fijo", "CONSTANTE_DEL_FLUJO",
                       "gatefijo.txt | {{prompt}}"), nombre="gatefijo")
    salida = teclear("/flujoteca ejecutar gatefijo ARGUMENTO_QUE_SE_IGNORA")
    cont = leido("gatefijo.txt")
    plano = _plano(salida)
    aviso_fijo = "fijo" in plano and ("ignoro" in plano or "ignora" in plano)
    usa_constante = (cont is not None and cont.strip() == "CONSTANTE_DEL_FLUJO"
                     and "ARGUMENTO_QUE_SE_IGNORA" not in cont)
    check("4. prompt_fijo usa la CONSTANTE, ignora el argumento y lo AVISA",
          usa_constante and aviso_fijo,
          "contenido=" + repr(cont) + " aviso="
          + ("si" if aviso_fijo else "NO LO DIJO"))

    # -- 5: nodo de entrada SIN USAR: tiene que AVISAR ---------------------
    # El flujo es valido y corre; lo que NO puede hacer es callarse. El dueno
    # escribe un prompt, ningun nodo interpola {{prompt}}, y su texto no llega
    # a ninguna tool: si nadie lo dice, el flujo "funciona" y no hace lo que
    # le pidieron. Es exactamente el defecto que casi se publica -- y la razon
    # de que este gate sea obligatorio antes de publicar.
    _ft.guardar(_flujo("gatesuelto", "prompt", "",
                       "gatesuelto.txt | TEXTO_FIJO_DEL_NODO"),
                nombre="gatesuelto")
    salida = teclear("/flujoteca ejecutar gatesuelto ESTE_TEXTO_NO_LLEGA")
    cont = leido("gatesuelto.txt")
    plano = _plano(salida)
    # Se acepta CUALQUIERA de las formas razonables de decirlo: lo que el gate
    # exige es que el comando lo DIGA, no una frase concreta.
    avisa = "prompt" in plano and any(f in plano for f in (
        "no usa", "no lo usa", "nadie usa", "no se usa", "ningun nodo",
        "no llega", "sin usar", "no lo interpola", "no interpola"))
    check("5. nodo de entrada SIN USAR: el comando AVISA", avisa,
          "escribio=" + repr(cont) + "; el comando NO dijo que el prompt del "
          "dueno no llega a ninguna tool")

    fallos = [n for n, ok in CHECKS if not ok]
    print("")
    print("E2E FLUJO CLI: " + str(len(CHECKS) - len(fallos)) + "/"
          + str(len(CHECKS)) + " OK en " + ("%.1f" % (time.time() - t0)) + "s",
          flush=True)
    if fallos:
        print("FALLARON: " + str(fallos), flush=True)
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
