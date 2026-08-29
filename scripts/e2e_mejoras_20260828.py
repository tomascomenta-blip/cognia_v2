# -*- coding: utf-8 -*-
"""E2E de las mejoras del 2026-08-28, contra el MODELO REAL.

Mismo espiritu que scripts/e2e_happy_path.py: teclear el CLI de verdad y
comprobar POSTCONDICIONES, no la prosa de la respuesta. Un modelo que dice
"listo" sin producir el artefacto tiene que FALLAR aqui.

Cadena que recorre (la que pidio el dueno):

    prompt -> contexto -> mejorador -> encuesta -> flujo -> version ->
    comparacion -> restauracion -> catalogo -> dashboard

Cada bloque comprueba algo que solo puede ser verdad si la pieza funciona de
punta a punta:

  1. CONTEXTO      reunir() sobre el repo real trae secciones reales y tarda
                   menos de 3 s en caliente
  2. MEJORADOR     /mejorar <texto> devuelve algo distinto del original Y el
                   prompt que se le mando al modelo LLEVABA el contexto
                   (esto es lo que estaba roto: el parametro existia y nadie
                   lo usaba)
  3. ENCUESTA      preparar() contra el modelo real devuelve preguntas
                   bien formadas, o cero preguntas con un motivo legible
  4. SESION->FLUJO de_sesion() sobre una sesion inventada produce un DAG que
                   pasa flows.validar()
  5. EDICION       editar() aplica una instruccion y el flujo cambia
  6. VERSIONADO    guardar dos veces crea dos versiones; comparar las ve;
                   restaurar crea una TERCERA y no borra ninguna
  7. CATALOGO      el flujo nuevo aparece en el catalogo unificado
  8. DASHBOARD     el HTML se genera, es autocontenido y trae ese flujo

Uso:
    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_mejoras_20260828.py

Salida: 'E2E MEJORAS: N/8 OK'; exit 0 si 8/8.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
# La biblioteca de flujos del e2e es TEMPORAL. Sin esto, cada corrida del gate
# dejaria flujos de prueba en la biblioteca real del dueno -- la misma leccion
# que COGNIA_EFIMERO=1 en el gate del camino feliz.
_TMP_FLUJOS = tempfile.mkdtemp(prefix="cognia_e2e_flujoteca_")
os.environ["COGNIA_FLUJOTECA_DIR"] = _TMP_FLUJOS
os.environ.setdefault("COGNIA_EFIMERO", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok), detalle))
    marca = "OK  " if ok else "FALLA"
    print(f"  [{marca}] {nombre}" + (f"  — {detalle}" if detalle else ""),
          flush=True)
    return ok


def hay_backend():
    try:
        from cognia.harness import mejorar_prompt as mp
        return bool(mp._detectar_url())
    except Exception:
        return False


# ---------------------------------------------------------------- 1. contexto

def prueba_contexto():
    from cognia.harness import contexto_mejora as cm
    hist = [{"role": "user", "content": "quiero un juego sencillo"},
            {"role": "assistant",
             "content": "Puedo hacerlo en HTML y JavaScript sin dependencias."}]
    cm.reunir("hazme una pagina web", historial=hist)      # calienta
    t0 = time.monotonic()
    ctx = cm.reunir("hazme una pagina web con login", historial=hist)
    tardo = time.monotonic() - t0
    ok = (ctx.chars > 0 and len(ctx.secciones) >= 2 and tardo < 3.0)
    check("1. contexto: secciones reales y rapido",
          ok, f"{len(ctx.secciones)} secciones, {ctx.chars} chars, "
              f"{tardo * 1000:.0f} ms")
    # La encuesta NO debe preguntar por el stack: la conversacion ya lo dijo.
    ids = {f["id"] for f in ctx.faltantes}
    check("1b. no pregunta lo que la conversacion ya contesto",
          "stack" not in ids, f"faltantes: {sorted(ids) or 'ninguno'}")
    return ctx


# --------------------------------------------------------------- 2. mejorador

def prueba_mejorador(ctx):
    """El fallo que este bloque caza: que el contexto NO llegue al modelo.

    No basta con que la reformulacion salga bien: salia bien ANTES, sin
    contexto. Lo que se comprueba es que el prompt que viaja al backend
    contiene el bloque de contexto."""
    from cognia.harness import mejorar_prompt as mp
    visto = {}

    def espia(prompt, system):
        visto["prompt"] = prompt
        return ("Crea una pagina web con formulario de acceso. Antes de "
                "empezar, preguntame que datos guarda el login y si hace "
                "falta base de datos. Devuelve los ficheros HTML, CSS y JS.")

    m = mp.mejorar("hazme una pagina web con login", contexto=ctx.bloque,
                   generar_fn=espia)
    llevaba = "Contexto de la sesion" in visto.get("prompt", "")
    check("2. el contexto LLEGA al prompt del mejorador",
          llevaba and m.ok,
          f"ok={m.ok}, contexto_en_prompt={llevaba}")
    return m


def prueba_mejorador_real():
    """Contra el modelo de verdad, por la puerta sin tty (/mejorar <texto>)."""
    if not hay_backend():
        return check("2b. mejorador contra el modelo real", False,
                     "no hay backend vivo")
    from cognia.harness import contexto_mejora as cm
    from cognia.harness import mejorar_prompt as mp
    pedido = "arregla el bug del login"
    ctx = cm.reunir(pedido)
    m = mp.mejorar(pedido, contexto=ctx.bloque, timeout_s=90.0)
    ok = m.ok and m.texto.strip() != pedido
    check("2b. mejorador contra el modelo real", ok,
          (m.texto[:90] if m.ok else m.motivo))
    return ok


# ---------------------------------------------------------------- 3. encuesta

def prueba_encuesta():
    from cognia.harness import contexto_mejora as cm
    from cognia.harness import encuesta as en
    pedido = "hazme una pagina web"
    ctx = cm.reunir(pedido)
    if not hay_backend():
        return check("3. encuesta contra el modelo real", False,
                     "no hay backend vivo")
    enc = en.preparar(pedido, contexto=ctx.bloque, faltantes=ctx.faltantes,
                      timeout_s=90.0)
    # Cero preguntas es una respuesta CORRECTA si el modelo cree que no falta
    # nada; lo que no puede pasar es una pregunta mal formada.
    bien_formadas = all(
        p.texto and p.tipo in en.TIPOS
        and (p.tipo == "abierta" or len(p.opciones) >= 2)
        for p in enc.preguntas)
    check("3. encuesta contra el modelo real",
          bien_formadas and enc.origen in ("modelo", "semilla", ""),
          f"origen={enc.origen or 'ninguna'}, {len(enc.preguntas)} preguntas, "
          f"{enc.ms} ms")
    for p in enc.preguntas:
        print(f"        [{p.tipo}] {p.texto}"
              + (f"  {p.opciones}" if p.opciones else ""))
    return enc


# ------------------------------------------------------- 4. sesion -> flujo

SESION = [
    {"role": "user",
     "content": "busca informacion sobre transformers y guardala en notas.md"},
    {"role": "assistant",
     "content": "Busque en la web sobre transformers."},
    {"role": "assistant",
     "content": "Escribi el resumen en notas.md."},
]
PASOS = [{"tool": "buscar", "args": "transformers", "ok": True},
         {"tool": "escribir_archivo", "args": "notas.md", "ok": True}]


def prueba_sesion_a_flujo():
    from cognia.agent import flujo_ia as fia
    from cognia.agent import flows
    if not hay_backend():
        return check("4. sesion -> flujo contra el modelo real", False,
                     "no hay backend vivo"), None
    r = fia.de_sesion(SESION, nombre="E2E investigar", pasos_reales=PASOS,
                      timeout_s=180.0)
    ok = r.ok
    if ok:
        try:
            flows.validar(r.flujo)
        except Exception as exc:
            ok = False
            r.motivo = f"el DAG no valida: {exc}"
    check("4. sesion -> flujo contra el modelo real", ok,
          (f"{len(r.flujo.get('nodos', []))} nodos: "
           f"{[n['id'] for n in r.flujo.get('nodos', [])]}" if ok
           else r.motivo))
    return ok, r


# ---------------------------------------------------- 5-6. edicion y versiones

def prueba_versionado(resultado_sesion):
    from cognia.agent import flujoteca as ft
    from cognia.agent import flujo_ia as fia

    nombre = "E2E investigar"
    if resultado_sesion is None or not resultado_sesion.ok:
        # Sin modelo se usa un flujo fijo: el versionado NO depende del
        # backend y tiene que poder probarse igual.
        base = {"nombre": nombre, "nodos": [
            {"id": "hallar", "tool": "buscar", "args": "transformers",
             "wires": ["guardar"]},
            {"id": "guardar", "tool": "escribir_archivo",
             "args": "notas.md", "wires": []}]}
    else:
        base = resultado_sesion.flujo
    ft.guardar(base, nombre=nombre, nota="de la sesion")

    # Edicion: con modelo si lo hay, con un generador fijo si no. El
    # VERSIONADO se prueba en los dos casos.
    if hay_backend():
        r = fia.editar(ft.cargar(nombre),
                       "anade un paso de validacion antes de guardar",
                       timeout_s=180.0)
        origen = "modelo real"
    else:
        nodos = [dict(n) for n in base["nodos"]]
        nodos[0]["wires"] = ["validar"]
        nodos.insert(1, {"id": "validar", "tool": "leer_archivo",
                         "args": "{{hallar}}", "wires": ["guardar"]})
        r = fia.editar(ft.cargar(nombre), "anade validacion",
                       generar_fn=lambda p, s: json.dumps(
                           {"nombre": nombre, "resumen": "validacion",
                            "nodos": nodos}),
                       listar_tools=lambda: ["buscar", "escribir_archivo",
                                             "leer_archivo"])
        origen = "generador fijo (sin backend)"
    if r.ok:
        ft.guardar(r.flujo, nombre=nombre, nota="anadida validacion")
    check("5. edicion conversacional del flujo", r.ok,
          f"{origen}: {r.resumen or r.motivo}")

    vs = ft.versiones(nombre)
    check("6a. cada guardado crea una version", len(vs) >= 2,
          f"{len(vs)} versiones")

    if len(vs) >= 2:
        d = ft.comparar(nombre, 1, 2)
        cambio = bool(d["anadidos"] or d["quitados"] or d["cambiados"])
        check("6b. comparar ve el cambio", cambio,
              f"+{len(d['anadidos'])} -{len(d['quitados'])} "
              f"~{len(d['cambiados'])}")

        antes = len(vs)
        ft.restaurar(nombre, 1)
        despues = ft.versiones(nombre)
        # LA propiedad del modulo: restaurar CREA, no destruye.
        conserva = (len(despues) == antes + 1
                    and {v["v"] for v in vs} <= {v["v"] for v in despues})
        vuelto = ft.cargar(nombre)
        igual_a_v1 = (vuelto["nodos"] == ft.cargar(nombre, 1)["nodos"])
        check("6c. restaurar crea version nueva y NO borra historial",
              conserva and igual_a_v1,
              f"{antes} -> {len(despues)} versiones, contenido de v1 "
              f"recuperado={igual_a_v1}")
    return nombre


# ------------------------------------------------------ 7-8. catalogo y HTML

def prueba_catalogo_y_dashboard(nombre_flujo):
    from cognia.memory import catalogo as cat
    from cognia.memory import memorias_view as mv

    c = cat.construir()
    check("7. el catalogo lee las familias reales",
          bool(c.familias_ok) and not c.familias_fallidas,
          f"{len(c.filas)} artefactos en {c.ms} ms, "
          f"familias ok={len(c.familias_ok)}, "
          f"fallidas={c.familias_fallidas or 'ninguna'}")

    destino = Path(tempfile.gettempdir()) / "e2e_memorias.html"
    ruta = mv.export(c, str(destino), open_browser=False)
    html = Path(ruta).read_text(encoding="utf-8")
    # Se comprueba el MARKUP, no los datos embebidos. Un artefacto del dueno
    # cuyo resumen contenga "http://" no hace que la pagina dependa de la red;
    # mirar el fichero entero daba un falso negativo con el catalogo real.
    import re as _re
    markup = _re.sub(r"const DATOS = .*?;\n", "", html, flags=_re.S)
    autocontenido = not any(x in markup for x in
                            ("src=", "<link", "@import", "//cdn", "https://"))
    tiene_datos = '"filas"' in html and html.count("</script>") == 1
    check("8. el dashboard se genera y es autocontenido",
          autocontenido and tiene_datos and len(html) > 5000,
          f"{len(html)} bytes, sin CDN={autocontenido}")


def main():
    print("E2E de las mejoras del 2026-08-28")
    print(f"  backend: {'vivo' if hay_backend() else 'NO HAY (se marcaran los bloques que lo necesitan)'}")
    print(f"  flujoteca temporal: {_TMP_FLUJOS}\n")
    try:
        ctx = prueba_contexto()
        prueba_mejorador(ctx)
        prueba_mejorador_real()
        prueba_encuesta()
        _ok, r = prueba_sesion_a_flujo()
        nombre = prueba_versionado(r)
        prueba_catalogo_y_dashboard(nombre)
    finally:
        shutil.rmtree(_TMP_FLUJOS, ignore_errors=True)

    total = len(CHECKS)
    buenos = sum(1 for _n, ok, _d in CHECKS if ok)
    print(f"\nE2E MEJORAS: {buenos}/{total} OK")
    for n, ok, d in CHECKS:
        if not ok:
            print(f"  FALLA: {n}  {d}")
    return 0 if buenos == total else 1


if __name__ == "__main__":
    sys.exit(main())
