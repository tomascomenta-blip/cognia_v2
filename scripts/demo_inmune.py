# -*- coding: utf-8 -*-
"""VERIFICACION REAL del sistema inmune, fuera de pytest y sobre FICHEROS DE VERDAD.

POR QUE EXISTE
--------------
Regla de este repo: "codigo que corre o no cuenta" y "pytest es necesario pero no
suficiente". Los tests de `tests/test_inmune_anticuerpos.py` fabrican el fallo a
mano. Este guion NO: usa la herramienta REAL del agente (`editar_archivo` del
registry de `cognia/agent/tools.py`) contra un fichero REAL, deja que falle de
verdad, toma el mensaje de error TAL CUAL lo produce el repo, y con eso sintetiza
el anticuerpo. Si el formato del error del repo cambia, este guion lo nota; los
tests no.

El ciclo completo que demuestra:
   fallo real -> informe causal -> sintetizar -> CUARENTENA (no veta) ->
   examinar contra sanos held-out -> ACTIVO -> veta la repeticion ->
   deja pasar la version corregida -> sobrevive a "otra instancia" ->
   se retira solo tras N falsos positivos.

USO
    PYTHONUTF8=1 ./venv312/Scripts/python.exe scripts/demo_inmune.py
Devuelve 0 si los 9 CHECKs pasan.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

FALLOS = []


def check(etiqueta: str, cond: bool, detalle: str = "") -> None:
    marca = "CHECK OK  " if cond else "CHECK FALLA"
    print(f"  [{marca}] {etiqueta}" + (f"\n               {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(etiqueta)


def main() -> int:
    taller = Path(tempfile.mkdtemp(prefix="inmune_demo_"))
    almacen = Path(tempfile.mkdtemp(prefix="inmune_alm_"))
    os.environ["COGNIA_INMUNE_DIR"] = str(almacen)
    os.environ["COGNIA_INMUNE_TTL"] = "0"          # ver el disco al instante
    os.environ["COGNIA_AGENT_WORKSPACE"] = str(taller)

    from cognia.agent.tools import run_tool
    from cognia.inmune import anticuerpos as ac
    ac.recargar()

    try:
        # ── 0) Un fichero REAL en un taller REAL ──────────────────────────────
        objetivo = taller / "app.py"
        objetivo.write_text(
            "def saludar(nombre):\n"
            "    return f'hola {nombre}'\n"
            "\n"
            "def despedir(nombre):\n"
            "    return f'adios {nombre}'\n",
            encoding="utf-8")
        print(f"\nTALLER : {taller}")
        print(f"ALMACEN: {ac.ruta_almacen()}\n")

        # ── 1) El fallo REAL: editar a ciegas un fichero que no se leyo ───────
        bloque_malo = ("<<<<<<< SEARCH\n"
                       "def saludar(nombre):\n"
                       "    return 'hola ' + nombre\n"      # NO es el texto real
                       "=======\n"
                       "def saludar(nombre):\n"
                       "    return f'HOLA {nombre}'\n"
                       ">>>>>>> REPLACE")
        args_malos = f"{objetivo} | {bloque_malo}"
        salida = run_tool("editar_archivo", args_malos, {})
        print("1) LA TOOL REAL FALLA (salida literal del repo):")
        print("   " + "\n   ".join(salida.strip().splitlines()[:4]))
        fallo_real = "ERROR" in salida.upper()
        check("la herramienta real fallo de verdad (no es un fallo inventado)", fallo_real)
        intacto = "return f'hola {nombre}'" in objetivo.read_text(encoding="utf-8")
        check("el fichero real quedo intacto tras el fallo", intacto)

        # ── 2) El informe causal que produciria el replay contrafactual ───────
        trayectoria = {
            "id": "demo-inmune-01",
            "pasos": [
                {"tool": "listar", "args": str(taller), "ok": True},
                {"tool": "editar_archivo", "args": args_malos, "ok": False,
                 "error": salida},                     # el error REAL, sin tocar
            ],
        }
        informe = {"trayectoria": "demo-inmune-01", "paso_culpable": 1,
                   "confianza": 0.85,
                   "modo_fallo": "edito un fichero que nunca leyo"}

        ab = ac.sintetizar(informe, trayectoria)
        print("\n2) SINTESIS desde el fallo real:")
        print(f"   chequeo  = {ab['chequeo'] if ab else None}")
        print(f"   estado   = {ab['estado'] if ab else None}")
        print(f"   remedio  = {(ab['remedio'] if ab else '')[:78]}...")
        check("sintetizo un chequeo determinista desde el error REAL",
              ab is not None and ab["chequeo"] == {"tipo": "precondicion_fichero",
                                                   "exige": "leido_antes"})

        # ── 3) CUARENTENA: registrado pero SIN poder vetar ────────────────────
        ac.registrar(ab)
        ctx_ciego = {"leidos": []}
        veto_en_cuarentena = ac.evaluar("editar_archivo", args_malos, ctx_ciego)
        print("\n3) EN CUARENTENA:")
        print(f"   activos()={len(ac.activos())}  evaluar()->{veto_en_cuarentena}")
        check("en cuarentena NO veta, aunque la llamada reproduzca el fallo",
              veto_en_cuarentena is None and ac.activos() == [])

        # ── 4) LA COMPUERTA con casos SANOS held-out de verdad ────────────────
        positivos = [{"tool": "editar_archivo", "args": args_malos, "ctx": {"leidos": []}}]
        sanos = [
            {"tool": "editar_archivo", "args": args_malos,
             "ctx": {"leidos": [str(objetivo)]}},                  # lo leyo antes
            {"tool": "editar_archivo", "args": f"{taller / 'otro.py'} | x",
             "ctx": {"leidos": [str(taller / "otro.py")]}},
            {"tool": "editar_archivo", "args": args_malos, "ctx": {}},  # sin ctx
        ]
        res = ac.examinar(ab, positivos, sanos)
        print("\n4) LA COMPUERTA:")
        print(f"   {res['motivo']}")
        check("paso el examen: veta el fallo y NO toca los sanos",
              res["activado"] is True and res["falsos_positivos"] == [])

        # ── 5) YA ACTIVO: veta la repeticion y el modelo lee el remedio ───────
        veto = ac.evaluar("editar_archivo", args_malos, ctx_ciego)
        print("\n5) EL VETO QUE LEE EL MODELO:")
        print("   " + "\n   ".join(veto["mensaje"].splitlines()))
        check("veta la repeticion exacta del fallo", bool(veto and veto["veto"]))
        check("el mensaje trae remedio y origen",
              "leer_archivo" in veto["mensaje"] and "demo-inmune-01" in veto["mensaje"])

        # ── 6) El camino CORRECTO sigue abierto: leer y despues editar ────────
        leido = run_tool("leer_archivo", str(objetivo), {})
        ctx_sano = {"leidos": [str(objetivo)]}
        pasa = ac.evaluar("editar_archivo", args_malos, ctx_sano)
        bloque_bueno = ("<<<<<<< SEARCH\n"
                        "    return f'hola {nombre}'\n"
                        "=======\n"
                        "    return f'HOLA {nombre}'\n"
                        ">>>>>>> REPLACE")
        args_buenos = f"{objetivo} | {bloque_bueno}"
        salida2 = run_tool("editar_archivo", args_buenos, {})
        print("\n6) EL CAMINO CORRECTO (leer -> editar):")
        print(f"   leer_archivo devolvio {len(leido)} chars; evaluar()->{pasa}")
        print("   " + salida2.strip().splitlines()[0])
        aplicado = "HOLA" in objetivo.read_text(encoding="utf-8")
        check("tras leer, el anticuerpo deja pasar y la edicion REAL se aplica",
              pasa is None and aplicado)

        # ── 7) Persistencia: "otra instancia" del proceso ─────────────────────
        ac.recargar()
        vivo = [a["id"] for a in ac.activos()]
        print(f"\n7) OTRA INSTANCIA (recargar desde {ac.ruta_almacen().name}):")
        print(f"   activos tras recargar = {vivo}")
        check("el anticuerpo sobrevive a una instancia nueva",
              vivo == [ab["id"]]
              and ac.evaluar("editar_archivo", args_malos, ctx_ciego) is not None)

        # ── 8) Retiro automatico tras N falsos positivos ──────────────────────
        for _ in range(ac.MAX_FALSOS_POSITIVOS):
            est = ac.registrar_resultado(ab["id"], fue_util=False)
        print(f"\n8) TRAS {ac.MAX_FALSOS_POSITIVOS} FALSOS POSITIVOS:")
        print(f"   estado={est['estado']}  motivo={est.get('motivo_retiro')}")
        check("se retira solo y deja de vetar",
              est["estado"] == "retirado"
              and ac.evaluar("editar_archivo", args_malos, ctx_ciego) is None)

        print("\n" + ("TODOS LOS CHECKS PASAN" if not FALLOS
                      else f"FALLARON {len(FALLOS)}: {FALLOS}"))
        return 1 if FALLOS else 0
    finally:
        shutil.rmtree(taller, ignore_errors=True)
        shutil.rmtree(almacen, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
