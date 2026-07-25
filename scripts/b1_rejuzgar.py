"""
b1_rejuzgar.py — vuelve a juzgar el HTML YA generado por b1_router_oraculo.py.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_rejuzgar.py

POR QUE EXISTE: el juez se corrigio tres veces el 2026-07-25 (umbral de
'contenido' calibrado para dashboards, semantica de esperado/min, y lectura de
visibilidad antes de que terminaran las animaciones CSS). Cada correccion
cambia veredictos sin cambiar productos. Re-juzgar el HTML guardado —en vez de
regenerar— aisla el efecto del JUEZ del efecto del MODELO: son exactamente los
mismos bytes.

No llama a ningun LLM. No toca la flota.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b1_oraculo")
POOL = {
    "construir":      "qwen2.5-coder-14b",
    "construir-ui":   "UIGEN-X-8B",
    "pensar":         "gpt-oss-20b",
    "pensar-en-lazo": "OpenReasoning-Nemotron-14B",
}


def main() -> int:
    from cognia.program_creator import juez_ejecutable

    tareas = json.loads(
        (RAIZ / "scripts" / "b1_tareas.json").read_text(encoding="utf-8"))["tareas"]
    previo = json.loads((SALIDA / "resultados.json").read_text(encoding="utf-8"))
    res: dict = {t["id"]: {} for t in tareas}

    for t in tareas:
        for combo in POOL:
            html = SALIDA / f"{t['id']}__{combo}" / "index.html"
            if not html.is_file():
                res[t["id"]][combo] = {"aprobado": False,
                                       "motivo": "el modelo no devolvio HTML"}
                continue
            v = juez_ejecutable.juzgar_web(html, t["contrato"])
            res[t["id"]][combo] = {
                "aprobado": v.aprobado, "motivo": v.motivo[:120],
                "checks_ok": sum(1 for c in v.checks if c.ok),
                "checks": len(v.checks)}
            print(f"  {t['id']:<14} {POOL[combo]:<28} "
                  f"{'APROBADO' if v.aprobado else 'FALLIDO '}", flush=True)

    print(f"\n{'=' * 96}")
    print("B1 (RE-JUZGADO con el juez corregido) — TECHO DEL POOL")
    print("=" * 96)
    print(f"{'TAREA':<16}" + "".join(f"{POOL[m][:14]:>16}" for m in POOL)
          + f"{'ORACULO':>10}")
    print("-" * 96)
    techo = 0
    for t in tareas:
        fila = f"{t['id']:<16}"
        alguno = False
        for m in POOL:
            ok = res[t["id"]][m].get("aprobado")
            fila += f"{('OK' if ok else 'falla'):>16}"
            alguno = alguno or bool(ok)
        techo += alguno
        print(fila + f"{('RESUELTA' if alguno else 'NADIE'):>10}")
    print("-" * 96)
    n = len(tareas)
    individuales = {m: sum(1 for t in tareas if res[t["id"]][m].get("aprobado"))
                    for m in POOL}
    print(f"\nTECHO DEL POOL (ruteo perfecto): {techo}/{n}")
    for m, c in individuales.items():
        print(f"  {POOL[m]:<30} solo: {c}/{n}")
    mejor = max(individuales.values())
    ganador = [POOL[m] for m, c in individuales.items() if c == mejor]
    print(f"\n  Mejor modelo INDIVIDUAL: {mejor}/{n}  ({', '.join(ganador)})")
    print(f"  GANANCIA DEL RUTEO PERFECTO SOBRE EL MEJOR SOLO: +{techo - mejor}")
    if techo == mejor:
        print("\n  Con este set, un oraculo que SIEMPRE elige bien entre los 4 "
              "modelos no consigue\n  ni una tarea mas que correr SOLO el mejor. "
              "El ruteo no tiene margen: no\n  hay nada que ganar eligiendo, "
              "porque un unico modelo ya cubre todo lo cubrible.")

    # cuanto de esto lo cambio el JUEZ, no los modelos
    print(f"\n{'-' * 96}\nCAMBIOS RESPECTO DE LA CORRIDA ANTERIOR (mismos bytes, "
          f"juez distinto):")
    cambios = 0
    for t in tareas:
        for m in POOL:
            antes = previo["resultados"].get(t["id"], {}).get(m, {}).get("aprobado")
            ahora = res[t["id"]][m].get("aprobado")
            if antes != ahora:
                cambios += 1
                print(f"  {t['id']:<14} {POOL[m]:<28} "
                      f"{'OK' if antes else 'falla'} -> "
                      f"{'OK' if ahora else 'falla'}")
    print(f"  total de veredictos que cambio el JUEZ: {cambios}/"
          f"{len(tareas) * len(POOL)}")

    (SALIDA / "resultados_rejuzgado.json").write_text(
        json.dumps({"resultados": res, "techo": techo,
                    "individuales": individuales, "mejor": mejor,
                    "n_tareas": n, "swaps": previo.get("swaps", [])},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {SALIDA / 'resultados_rejuzgado.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
