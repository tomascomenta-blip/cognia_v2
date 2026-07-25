"""
a4_reprocesar_indice.py — reprocesa el indice con la regla de FASE A4.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\a4_reprocesar_indice.py
    ... --escribir      # sin esto solo INFORMA, no toca nada

LA REGLA (orden del dueno): "Cualquier score sin puntaje_real se muestra como
'sin verificar', nunca como numero. Reprocesa el indice existente con esa regla."

QUE ARREGLA, y por que hacia falta reprocesar y no solo cambiar como se imprime
(lo encontro un verificador de contexto fresco el 2026-07-25):

1. HAY DOS VERIFICADORES Y NO MIDEN LO MISMO. Los 60 sellos `.verificacion.json`
   dicen `"verificador": "cognia.autoprueba (compila/importa/arranca/sin_stubs)"`
   — eso es LIVENESS, no correccion. Un random-walk que imprime saca 9.5. El
   indice no guardaba QUIEN verifico, asi que "puntaje_real: 9.5" se leia como
   "funciona". Ahora cada entrada lleva `verificador`.

2. LOS PRODUCTOS DEL LAZO NO ESTABAN EN EL INDICE. `pulidos/` y `construidos/`
   —justo donde vive el juego de memoria que el juez ejecutable REPRUEBA— tienen
   0 entradas en index.json. El unico FALLIDO real del sistema no aparecia en
   ningun sitio de la biblioteca.

3. EL INDICE ESTABA DESINCRONIZADO DE LOS SELLOS. Productos con
   `.verificacion.json` en su carpeta y `puntaje_real: null` en el indice
   (minecraft_juego: 9.5 en el sello, null en el indice).

Anade a cada entrada: `verificador`, `veredicto_ejecutable` y
`verificado_por_ejecucion`. No borra ni pisa datos previos.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

BASE = RAIZ / "cognia" / "program_creator" / "generated_programs"
INDICE = BASE / "index.json"
SELLO = ".verificacion.json"
CONTENEDORES = ("pulidos", "construidos")
# Directorios de trabajo de los experimentos: no son productos de la biblioteca.
EXCLUIR = {"b1_oraculo", "b2_sistema_real", "c53_frontera"}


def leer(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def productos() -> list:
    fuera = []
    for d in sorted(BASE.iterdir()):
        if not d.is_dir() or d.name in EXCLUIR:
            continue
        if d.name in CONTENEDORES:
            fuera += [(x, d.name) for x in sorted(d.iterdir()) if x.is_dir()]
        else:
            fuera.append((d, ""))
    return fuera


def main(argv: list) -> int:
    from cognia.program_creator import juez_ejecutable

    escribir = "--escribir" in argv
    idx = leer(INDICE) or []
    por_dir = {e.get("directory") or e.get("id"): e for e in idx}

    nuevos, sincronizados, juzgados = [], [], []
    fallidos = []

    for d, contenedor in productos():
        entrada = por_dir.get(d.name)
        sello = leer(d / SELLO) or {}

        if entrada is None:
            entrada = {
                "id": d.name,
                "title": d.name.replace("_", " ").title(),
                "category": f"(de {contenedor}/)" if contenedor else "",
                "description": "",
                "total_score": sello.get("score_juez"),
                "created_at": sello.get("fecha", ""),
                "directory": (f"{contenedor}/{d.name}" if contenedor else d.name),
                "self_proposed": False,
                "verificado": sello.get("verificado"),
                "puntaje_real": sello.get("puntaje_real"),
                "verificado_en": sello.get("fecha", ""),
            }
            idx.append(entrada)
            nuevos.append(entrada["directory"])

        # 3. sincronizar con el sello si el indice se quedo atras
        if entrada.get("puntaje_real") is None and sello.get("puntaje_real") is not None:
            entrada["puntaje_real"] = sello["puntaje_real"]
            entrada["verificado"] = sello.get("verificado")
            entrada["verificado_en"] = sello.get("fecha", "")
            sincronizados.append(d.name)

        # 1. decir QUIEN verifico
        if entrada.get("puntaje_real") is not None:
            entrada["verificador"] = sello.get(
                "verificador", "cognia.autoprueba (estructural)")
        else:
            entrada.setdefault("verificador", None)

        # veredicto del juez EJECUTABLE (solo web; el resto queda explicito)
        html = juez_ejecutable.entrypoint_web(d)
        if html is None:
            entrada["veredicto_ejecutable"] = "NO APLICA (no es web)"
            entrada["verificado_por_ejecucion"] = False
        else:
            try:
                v = juez_ejecutable.juzgar(d)
                entrada["veredicto_ejecutable"] = v.estado
                entrada["verificado_por_ejecucion"] = bool(v.con_contrato)
                if v.con_contrato:
                    juzgados.append(d.name)
                    entrada["verificador"] = "juez_ejecutable (contrato)"
                    entrada["puntaje_real"] = v.puntaje_ejecucion
                    entrada["verificado"] = v.aprobado
                if not v.aprobado:
                    fallidos.append((d.name, v.motivo[:90]))
            except Exception as exc:
                entrada["veredicto_ejecutable"] = f"ERROR {type(exc).__name__}"
                entrada["verificado_por_ejecucion"] = False
        print(f"  {d.name[:50]:<52} {entrada['veredicto_ejecutable']}",
              flush=True)

    # ── informe ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 76}")
    print("A4 — REPROCESADO DEL INDICE")
    print("=" * 76)
    print(f"  entradas en el indice          : {len(idx)}")
    print(f"  productos ANADIDOS (pulidos/,  : {len(nuevos)}  {nuevos}")
    print(f"    construidos/ no estaban)")
    print(f"  sincronizados con su sello     : {len(sincronizados)}  "
          f"{sincronizados}")
    con_real = [e for e in idx if e.get("puntaje_real") is not None]
    por_ejec = [e for e in idx if e.get("verificado_por_ejecucion")]
    print(f"\n  con puntaje_real (de cualquier verificador): {len(con_real)}/{len(idx)}")
    print(f"  VERIFICADOS POR EJECUCION (contrato)       : {len(por_ejec)}/{len(idx)}")
    print(f"    -> todo lo demas es liveness estructural de cognia.autoprueba, "
          f"que NO dice que el producto haga lo pedido")
    if fallidos:
        print(f"\n  NO APROBADOS por el juez ejecutable ({len(fallidos)}):")
        for nombre, motivo in fallidos:
            print(f"    {nombre[:44]:<46} {motivo}")

    if escribir:
        INDICE.write_text(json.dumps(idx, indent=2, ensure_ascii=False),
                          encoding="utf-8")
        print(f"\n  ESCRITO: {INDICE}")
    else:
        print(f"\n  (solo informe — usa --escribir para guardar)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
