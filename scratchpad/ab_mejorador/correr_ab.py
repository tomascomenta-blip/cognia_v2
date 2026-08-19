# -*- coding: utf-8 -*-
"""A/B APAREADO Y CIEGO entre los system prompts v1 y v2 del reformulador.

Es un BANCO, no producto: no toca cognia/. Solo llama a mejorar_prompt.mejorar()
por el camino real (mismo backend, mismos parametros, misma sesion).

Diseno (por que asi):
- APAREADO: las dos versiones ven EXACTAMENTE el mismo texto de entrada. Lo unico
  que cambia entre brazos es el system prompt.
- INTERCALADO: por tarea se corren 4 llamadas, v1,v2,v2,v1 en las tareas de indice
  par y v2,v1,v1,v2 en las impares. Asi el prefill frio (la primera llamada de la
  tarea, con la KV cache del system anterior invalidada) no cae siempre en el
  mismo brazo, que es como se cuela un sesgo de latencia.
- 2 REPLICAS por celda porque el muestreo tiene varianza (temperatura 0.2, no 0):
  una sola salida por brazo no distingue "el brazo es peor" de "salio mal esa vez".
- UN SOLO SLOT: estrictamente secuencial. Nada corre en paralelo.
- CIEGO: pares.json lleva la letra A/B (la asignacion brazo->letra ALTERNA por
  indice de tarea) y NO contiene la cadena v1/v2 ni ninguna otra pista. La clave
  vive aparte en clave.json.
  OJO, leccion cara de la ronda 2: la ceguera se rompe por CONTENIDO antes que
  por etiqueta. Si un brazo devuelve el texto del usuario intacto (lo que hace
  v1 en 22 de 24 llamadas), esa celda es identificable a simple vista y la fila
  deja de ser un par comparable. Por eso ahora hay dos chequeos y las filas
  donde un brazo no produjo salida salen del juicio a no_juzgables.json.
- SIN VOTOS NO HAY JUICIO: se emite plantilla_votos.json antes de destapar la
  clave. La ronda 2 dejo 12 votos que solo existian en prosa y no se podian
  recomputar desde ningun fichero.
"""
import json
import os
import statistics
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from cognia.harness import mejorar_prompt as mp  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
TIMEOUT_S = 90.0

# 12 tareas humanas cotidianas tecleadas como las teclea el dueno: cortas, vagas,
# en espanol, sin puntuacion cuidada. Las 5 primeras son las del diagnostico de la
# ronda 1 (para poder comparar contra lo ya medido); las 7 siguientes son dominios
# distintos. Los dos ejemplos de v2 hablan de "quiero ponerme en forma": el caso
# mas cercano del banco es "quiero empezar a correr", marcado abajo, y hay que
# leerlo aparte porque es el unico que se parece al material de entrenamiento.
BANCO = [
    {"id": "compras", "dominio": "vida", "texto": "hazme una lista de compras para la semana"},
    {"id": "aumento", "dominio": "trabajo", "texto": "ayudame a escribir un correo para pedir un aumento"},
    {"id": "bug_login", "dominio": "codigo", "texto": "arregla el bug del login"},
    {"id": "escritorio", "dominio": "vida", "texto": "organizame el escritorio"},
    {"id": "guitarra", "dominio": "aprender", "texto": "quiero aprender guitarra"},
    {"id": "viaje", "dominio": "vida", "texto": "planeame un viaje para las vacaciones"},
    {"id": "gastos", "dominio": "dinero", "texto": "necesito ordenar mis gastos del mes"},
    {"id": "curriculum", "dominio": "trabajo", "texto": "hazme el curriculum"},
    {"id": "mudanza", "dominio": "vida", "texto": "me mudo el mes que viene ayudame"},
    {"id": "correr", "dominio": "aprender", "texto": "quiero empezar a correr"},
    {"id": "receta", "dominio": "vida", "texto": "que cocino hoy con lo que tengo"},
    {"id": "tramite", "dominio": "tramite", "texto": "tengo que renovar el dni y no se como"},
]


def orden_llamadas(indice):
    """Secuencia de brazos de una tarea. Alterna quien come el prefill frio."""
    if indice % 2 == 0:
        return ["v1", "v2", "v2", "v1"]
    return ["v2", "v1", "v1", "v2"]


def letra_de(indice):
    """Asignacion brazo->letra para el ciego. Alterna por indice de tarea, asi
    'A' no es siempre el mismo brazo y un juez no puede aprender la posicion."""
    if indice % 2 == 0:
        return {"v1": "A", "v2": "B"}
    return {"v2": "A", "v1": "B"}


def main(argv=None):
    # --desde-crudo re-emite los artefactos derivados (pares, clave,
    # no_juzgables, resumen) a partir de crudo.json, sin volver a llamar al
    # modelo. Existe porque el bug de ceguera de la ronda 2 estaba en la
    # DERIVACION, no en las llamadas: re-medir 48 veces para arreglar un
    # filtro habria cambiado los datos que se estaban corrigiendo.
    if argv and "--desde-crudo" in argv:
        with open(os.path.join(AQUI, "crudo.json"), encoding="utf-8") as fh:
            llamadas = json.load(fh)
        print("re-emitiendo artefactos desde crudo.json ({} llamadas)".format(
            len(llamadas)))
        return emitir_artefactos(llamadas)

    destino = mp._detectar_url()
    if not destino:
        print("SIN BACKEND: " + (mp._motivo_backend() or "?"))
        return 2
    print("backend: " + destino)

    with open(os.path.join(AQUI, "banco.json"), "w", encoding="utf-8") as fh:
        json.dump(BANCO, fh, ensure_ascii=False, indent=2)

    llamadas = []
    for indice, tarea in enumerate(BANCO):
        vistos = {"v1": 0, "v2": 0}
        for pos, brazo in enumerate(orden_llamadas(indice)):
            vistos[brazo] += 1
            # generar_fn propio SOLO para poder guardar el texto BRUTO (lo que
            # devolvio el modelo antes del saneador). mejorar() no lo expone y
            # sin el no se puede decir POR QUE un guardia rechazo.
            registro = {"modelo": ""}
            real = mp._construir_generar(destino, TIMEOUT_S, registro)
            caja = {}

            def _generar(prompt, system, _caja=caja, _real=real):
                _caja["prompt"] = prompt
                salida = _real(prompt, system)
                _caja["bruto"] = salida
                return salida

            t0 = time.monotonic()
            res = mp.mejorar(tarea["texto"], timeout_s=TIMEOUT_S,
                             generar_fn=_generar, version=brazo)
            pared_ms = int((time.monotonic() - t0) * 1000)
            fila = {
                "tarea": tarea["id"], "indice": indice, "brazo": brazo,
                "replica": vistos[brazo], "posicion": pos,
                "original": tarea["texto"],
                "ok": res.ok, "motivo": res.motivo,
                "ms": res.ms, "pared_ms": pared_ms,
                "texto": res.texto, "bruto": caja.get("bruto", ""),
                "chars": len(res.texto), "aviso": res.aviso,
                "modelo": registro.get("modelo", ""),
            }
            llamadas.append(fila)
            print("[{:>10}] {} r{} pos{} ok={} {} {}ms {}c".format(
                tarea["id"], brazo, vistos[brazo], pos, res.ok, res.motivo,
                res.ms, len(res.texto)))

    with open(os.path.join(AQUI, "crudo.json"), "w", encoding="utf-8") as fh:
        json.dump(llamadas, fh, ensure_ascii=False, indent=2)

    return emitir_artefactos(llamadas)


def emitir_artefactos(llamadas):
    """Todo lo DERIVADO de las llamadas: pares ciegos, clave, no juzgables,
    plantilla de votos y resumen. Separado de main() para poder re-emitirlo sin
    volver a gastar 48 llamadas al backend."""
    # --- pares ciegos ------------------------------------------------------
    # Representante de cada celda = replica 1 (fija, no la "mejor": elegir la
    # mejor de dos seria un best-of-2 encubierto y no es lo que corre el CLI).
    #
    # FUGA DE CEGUERA ARREGLADA (revision adversarial, 2026-08-19). La version
    # anterior publicaba las 12 filas con el campo `original` al lado de A y B.
    # Como v1 devolvio el texto del usuario INTACTO en 22 de 24 llamadas, en 10
    # de las 12 filas una de las dos celdas era BYTE-IDENTICA a ese `original`:
    # cualquier juez identificaba el brazo v1 sin mirar clave.json, y de hecho
    # el resultado se repartio exactamente segun esa marca (v2 gano 10-0 en las
    # filas con marca y 1-1 en las dos sin marca). El chequeo automatico de
    # entonces solo buscaba las subcadenas "v1"/"v2"/"version"/"system" y por
    # eso imprimio OK sin ver nada.
    # Dos arreglos, no uno: (a) una fila donde un brazo no produjo salida NO es
    # comparable y sale del juicio, a un fichero aparte; (b) el chequeo pasa de
    # subcadenas a identidad de CONTENIDO.
    pares, clave, no_juzgables = [], {}, []
    for indice, tarea in enumerate(BANCO):
        mapa = letra_de(indice)
        base = tarea["texto"].strip()
        celdas, motivos_celda = {}, {}
        for brazo, letra in mapa.items():
            elegida = [c for c in llamadas
                       if c["tarea"] == tarea["id"] and c["brazo"] == brazo
                       and c["replica"] == 1][0]
            celdas[letra] = elegida["texto"]
            motivos_celda[brazo] = elegida["motivo"]
        sin_salida = [b for b, l in mapa.items()
                      if celdas[l].strip() == base]
        if sin_salida:
            # No es un par: es "un brazo escribio y el otro devolvio el texto
            # del usuario". Eso ya lo mide resumen.json (aceptadas por brazo);
            # juzgarlo como si fueran dos reformulaciones infla el marcador.
            no_juzgables.append({
                "id": tarea["id"], "original": tarea["texto"],
                "brazos_sin_salida": sorted(sin_salida),
                "motivos": motivos_celda})
            continue
        pares.append({"id": tarea["id"], "original": tarea["texto"],
                      "A": celdas["A"], "B": celdas["B"]})
        clave[tarea["id"]] = dict((letra, brazo) for brazo, letra in mapa.items())

    with open(os.path.join(AQUI, "pares.json"), "w", encoding="utf-8") as fh:
        json.dump(pares, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(AQUI, "clave.json"), "w", encoding="utf-8") as fh:
        json.dump(clave, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(AQUI, "no_juzgables.json"), "w",
              encoding="utf-8") as fh:
        json.dump(no_juzgables, fh, ensure_ascii=False, indent=2)

    # Plantilla del juicio: se emite ANTES de destapar clave.json y el juez la
    # rellena. Sin este fichero los votos solo existen en prosa y el resultado
    # no se puede recomputar desde ningun sitio (paso exactamente eso en la
    # ronda 2). "juez" se declara: si es el mismo agente que escribio uno de
    # los brazos, eso es un conflicto y tiene que estar escrito.
    plantilla = {"juez": "SIN DECLARAR (nombre + si escribio alguno de los brazos)",
                 "rubrica": "gana el lado que un humano podria ejecutar mejor "
                            "a la primera sin datos inventados",
                 "votos": [{"id": p["id"], "letra": None, "motivo": ""}
                           for p in pares]}
    ruta_votos = os.path.join(AQUI, "plantilla_votos.json")
    if not os.path.exists(ruta_votos):
        with open(ruta_votos, "w", encoding="utf-8") as fh:
            json.dump(plantilla, fh, ensure_ascii=False, indent=2)

    # Chequeo de ceguera, en dos capas.
    with open(os.path.join(AQUI, "pares.json"), encoding="utf-8") as fh:
        crudo_pares = fh.read()
    fugas = [m for m in ("v1", "v2", "version", "system") if m in crudo_pares.lower()]
    # Capa 2 (la que faltaba): ninguna celda puede coincidir con la entrada.
    # Es la etiqueta escrita en el CONTENIDO, y el chequeo por subcadenas no la
    # ve. Si aparece, la fila NO es juzgable.
    fuga_contenido = [p["id"] for p in pares
                      if p["A"].strip() == p["original"].strip()
                      or p["B"].strip() == p["original"].strip()]
    print("\nceguera de pares.json")
    print("  subcadenas: " + ("FUGA " + str(fugas) if fugas else "OK"))
    print("  contenido : " + ("FUGA " + str(fuga_contenido)
                              if fuga_contenido else "OK"))
    print("  juzgables : {} de {} ({} fuera: un brazo no produjo salida)".format(
        len(pares), len(BANCO), len(no_juzgables)))
    for nj in no_juzgables:
        print("    fuera: {:>11}  sin salida: {}".format(
            nj["id"], ",".join(nj["brazos_sin_salida"])))

    # --- resumen -----------------------------------------------------------
    resumen = {}
    for brazo in ("v1", "v2"):
        filas = [c for c in llamadas if c["brazo"] == brazo]
        motivos = {}
        for c in filas:
            if not c["ok"]:
                motivos[c["motivo"]] = motivos.get(c["motivo"], 0) + 1
        lat = sorted(c["ms"] for c in filas)
        aceptadas = [c["chars"] for c in filas if c["ok"]]
        todas = [c["chars"] for c in filas]
        resumen[brazo] = {
            "llamadas": len(filas),
            "aceptadas": len(aceptadas),
            "rechazadas": len(filas) - len(aceptadas),
            "motivos": motivos,
            "ms_mediana": int(statistics.median(lat)),
            "ms_min": lat[0], "ms_max": lat[-1],
            # chars_mediana se calculaba SOLO sobre las aceptadas y se
            # publicaba junto a la del otro brazo como si fueran la misma
            # medida: para v1 eran 2 valores y para v2, 24. El n va al lado del
            # numero, y ademas se da la mediana sobre las 24 llamadas, que es
            # lo unico comparable entre brazos.
            "chars_mediana_aceptadas": int(statistics.median(aceptadas or [0])),
            "chars_n_aceptadas": len(aceptadas),
            "chars_mediana_todas": int(statistics.median(todas or [0])),
            "chars_n_todas": len(todas),
        }
    with open(os.path.join(AQUI, "resumen.json"), "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=2)
    print("\n" + json.dumps(resumen, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
