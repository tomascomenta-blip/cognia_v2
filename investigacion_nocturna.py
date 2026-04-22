"""
investigacion_nocturna.py — Investigacion encadenada toda la noche
==================================================================
Cognia investiga de forma autonoma encadenando conceptos:
  - Si encuentra un termino desconocido, lo agrega a la cola
  - Duerme cada N articulos para consolidar
  - Se detiene automaticamente a las 10am del dia siguiente

USO:
  python investigacion_nocturna.py "inteligencia artificial"
  python investigacion_nocturna.py "machine learning" --lang en --max 200
  python investigacion_nocturna.py "redes neuronales" --hasta 08:00
"""

import sys, os, time, re, json, random, argparse, urllib.request, urllib.parse

# FIX: rate limiting para evitar spam a Wikipedia
_LAST_REQUEST_TIME = 0.0
_MIN_REQUEST_INTERVAL = 1.5  # segundos entre requests (Wikipedia policy: max 1 req/s)

def _rate_limited_urlopen(req, timeout=10):
    """Wrapper que respeta el rate limit de Wikipedia (máx 1 req/s)."""
    global _LAST_REQUEST_TIME
    elapsed = time.time() - _LAST_REQUEST_TIME
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _LAST_REQUEST_TIME = time.time()
    return urllib.request.urlopen(req, timeout=timeout)
from datetime import datetime, timedelta
from collections import deque

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

# ── Colores para terminal ──────────────────────────────────────────────
def _c(t, n): return f"\033[{n}m{t}\033[0m"
def verde(t):    return _c(t, 92)
def amarillo(t): return _c(t, 93)
def cyan(t):     return _c(t, 96)
def gris(t):     return _c(t, 90)
def rojo(t):     return _c(t, 91)
def magenta(t):  return _c(t, 95)
def sep(titulo=""):
    if titulo:
        r = max(0, (56 - len(titulo)) // 2)
        print(cyan("─" * r + f" {titulo} " + "─" * r))
    else:
        print(gris("─" * 60))


# ── Wikipedia ──────────────────────────────────────────────────────────

def buscar_titulos_wikipedia(query: str, lang: str = "es", n: int = 3) -> list:
    """Busca titulos de articulos relacionados con el query."""
    try:
        params = urllib.parse.urlencode({
            "action": "query", "list": "search",
            "srsearch": query, "srlimit": n,
            "format": "json", "utf8": 1
        })
        req = urllib.request.Request(
            f"https://{lang}.wikipedia.org/w/api.php?{params}",
            headers={"User-Agent": "Cognia/3.0"}
        )
        with _rate_limited_urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return [item["title"] for item in data.get("query", {}).get("search", [])]
    except Exception:
        return []


def obtener_articulo(titulo: str, lang: str = "es", max_chars: int = 2000) -> str:
    """Obtiene el texto completo de un articulo de Wikipedia."""
    try:
        params = urllib.parse.urlencode({
            "action": "query", "titles": titulo,
            "prop": "extracts", "explaintext": True,
            "exsentences": 20, "format": "json", "utf8": 1
        })
        req = urllib.request.Request(
            f"https://{lang}.wikipedia.org/w/api.php?{params}",
            headers={"User-Agent": "Cognia/3.0"}
        )
        with _rate_limited_urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid != "-1":
                return page.get("extract", "").strip()[:max_chars]
    except Exception:
        pass
    return ""


def extraer_conceptos_del_texto(texto: str, conceptos_conocidos: set,
                                 max_nuevos: int = 5) -> list:
    """
    Extrae terminos que aparecen en el texto pero que Cognia no conoce bien.
    Estos se agregan a la cola de investigacion.
    """
    # Patron: palabras de 4+ chars que aparecen como nombres propios o tecnicos
    candidatos = re.findall(r'\b([A-Z][a-z]{3,}(?:\s[A-Z][a-z]{2,})?)\b', texto)
    candidatos += re.findall(
        r'\b(aprendizaje\s+\w+|red\s+neuronal|machine\s+learning|deep\s+learning|'
        r'inteligencia\s+artificial|algoritmo\s+\w+|modelo\s+\w+)\b',
        texto.lower()
    )

    # Filtrar: no repetir conocidos, no muy cortos, no numeros
    nuevos = []
    vistos = set()
    for c in candidatos:
        c_clean = c.strip().lower()
        if (len(c_clean) > 4
                and c_clean not in conceptos_conocidos
                and c_clean not in vistos
                and not c_clean[0].isdigit()):
            nuevos.append(c_clean)
            vistos.add(c_clean)
        if len(nuevos) >= max_nuevos:
            break
    return nuevos


def extraer_parrafos(texto: str, min_chars: int = 80) -> list:
    """Extrae parrafos utiles del texto."""
    parrafos = []
    for linea in texto.split("\n"):
        linea = linea.strip()
        if re.match(r"^=+.+=+$", linea):
            continue
        if len(linea) >= min_chars:
            parrafos.append(linea)
    return parrafos


# ── Hora de parada ─────────────────────────────────────────────────────

def calcular_hora_parada(hora_str: str) -> datetime:
    """
    Calcula el datetime de parada.
    Si la hora ya paso hoy, calcula para manana.
    """
    h, m = map(int, hora_str.split(":"))
    ahora = datetime.now()
    parada = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    if parada <= ahora:
        parada += timedelta(days=1)
    return parada


def tiempo_restante(parada: datetime) -> str:
    delta = parada - datetime.now()
    if delta.total_seconds() <= 0:
        return "0m"
    horas = int(delta.total_seconds() // 3600)
    minutos = int((delta.total_seconds() % 3600) // 60)
    return f"{horas}h {minutos}m"


# ── Motor principal ────────────────────────────────────────────────────

def investigacion_nocturna(
    tema_inicial: str,
    lang: str = "es",
    max_articulos: int = 500,
    dormir_cada: int = 5,
    hora_parada: str = "10:00",
    pausa_entre: float = 2.0,
    profundidad_cadena: int = 3
):
    """
    Motor de investigacion encadenada:
    1. Empieza con el tema inicial
    2. Por cada articulo, extrae conceptos nuevos y los encola
    3. Duerme cada N articulos
    4. Para a la hora indicada
    """

    parada_dt = calcular_hora_parada(hora_parada)

    sep("INVESTIGACION NOCTURNA ENCADENADA")
    print(f"  Tema inicial   : {cyan(tema_inicial)}")
    print(f"  Idioma         : {lang}")
    print(f"  Max articulos  : {max_articulos}")
    print(f"  Dormir cada    : {dormir_cada} articulos")
    print(f"  Parada         : {hora_parada} ({parada_dt.strftime('%d/%m/%Y')})")
    print(f"  Tiempo total   : {tiempo_restante(parada_dt)}")
    print(f"  Profundidad    : {profundidad_cadena} conceptos nuevos por articulo")
    sep()

    # Iniciar Cognia
    print("Iniciando Cognia...", end=" ", flush=True)
    from cognia import Cognia
    from cognia import Cognia
    from cognia.vectors import text_to_vector, analyze_emotion
    print(verde("lista"))

    # Cola de investigacion: deque con prioridad implicita (FIFO)
    # Formato: (termino, profundidad_origen)
    cola = deque()
    cola.append((tema_inicial, 0))

    # Conjunto de ya investigados (evita loops)
    investigados = set()
    # Conceptos que Cognia ya conoce bien (no reinvestigar)
    conocidos = set()

    # Cargar conceptos ya en memoria semantica
    try:
        import sqlite3
        conn = sqlite3.connect(ai.episodic.db)
        rows = conn.execute("SELECT concept FROM semantic_memory").fetchall()
        conocidos = {r[0].lower() for r in rows}
        conn.close()
        print(gris(f"  Conceptos previos en memoria: {len(conocidos)}"))
    except Exception:
        pass

    # Estadisticas
    stats = {
        "articulos_leidos": 0,
        "episodios_guardados": 0,
        "hechos_grafo": 0,
        "conceptos_encolados": 0,
        "ciclos_sueno": 0,
        "errores": 0,
        "inicio": datetime.now().isoformat()
    }

    print()
    sep("INICIANDO CADENA DE INVESTIGACION")
    print(gris(f"  Para ver progreso en tiempo real mira esta ventana."))
    print(gris(f"  Presiona Ctrl+C para detener limpiamente."))
    sep()
    print()

    articulo_num = 0

    try:
        while cola and articulo_num < max_articulos:

            # Verificar hora de parada
            if datetime.now() >= parada_dt:
                print()
                print(amarillo(f"⏰ Hora de parada alcanzada ({hora_parada}). Deteniendo..."))
                break

            # Tomar siguiente termino de la cola
            termino, profundidad = cola.popleft()
            termino_limpio = termino.strip().lower().replace("_", " ")

            # Evitar duplicados
            if termino_limpio in investigados:
                continue

            # Tiempo restante
            tr = tiempo_restante(parada_dt)
            print(f"\n[{articulo_num+1}] {cyan(termino)} "
                  f"| cola: {len(cola)} | tiempo: {amarillo(tr)}")

            # Buscar articulos en Wikipedia
            titulos = buscar_titulos_wikipedia(termino_limpio, lang=lang, n=2)

            if not titulos:
                # Fallback a ingles si falla en espanol
                if lang == "es":
                    titulos = buscar_titulos_wikipedia(termino_limpio, lang="en", n=2)
                if not titulos:
                    print(gris(f"  Sin resultados para '{termino_limpio}'"))
                    stats["errores"] += 1
                    investigados.add(termino_limpio)
                    continue

            # Procesar cada titulo encontrado
            for titulo in titulos[:2]:
                if datetime.now() >= parada_dt:
                    break

                titulo_key = titulo.lower()
                if titulo_key in investigados:
                    continue

                print(gris(f"  📖 {titulo}"))

                # Obtener texto del articulo
                texto = obtener_articulo(titulo, lang=lang)
                if not texto or len(texto) < 100:
                    # Intentar en ingles si esta en espanol
                    if lang == "es":
                        texto = obtener_articulo(titulo, lang="en")
                    if not texto or len(texto) < 100:
                        print(gris(f"     Articulo vacio, saltando"))
                        investigados.add(titulo_key)
                        continue

                # Extraer parrafos
                parrafos = extraer_parrafos(texto)
                if not parrafos:
                    investigados.add(titulo_key)
                    continue

                # Label para este articulo
                label = termino_limpio.replace(" ", "_")[:25]

                # Guardar parrafos en Cognia
                ep_guardados = 0
                for parrafo in parrafos[:15]:  # Max 15 parrafos por articulo
                    try:
                        ai.learn(parrafo, label)
                        ep_guardados += 1
                    except Exception:
                        stats["errores"] += 1

                stats["episodios_guardados"] += ep_guardados
                articulo_num += 1
                investigados.add(titulo_key)

                # Extraer hechos para el grafo
                try:
                    from investigador import extraer_hechos_simples
                    hechos = extraer_hechos_simples(titulo, texto)
                    for h in hechos:
                        try:
                            ai.kg.add_triple(h["subject"], h["predicate"], h["object"],
                                             weight=0.8, source="nocturna")
                            stats["hechos_grafo"] += 1
                        except Exception:
                            pass
                    # Triples automaticos del texto
                    triples = ai.kg.extract_triples_from_text(texto[:1000], label)
                    for subj, pred, obj in triples:
                        try:
                            if ai.kg.add_triple(subj, pred, obj, weight=0.7, source="nocturna"):
                                stats["hechos_grafo"] += 1
                        except Exception:
                            pass
                except Exception:
                    pass

                print(verde(f"     ✅ {ep_guardados} episodios | +{stats['hechos_grafo']} hechos totales"))

                # ── ENCADENAMIENTO: extraer conceptos nuevos del texto ──
                nuevos = extraer_conceptos_del_texto(
                    texto,
                    conocidos | investigados,
                    max_nuevos=profundidad_cadena
                )
                for nuevo in nuevos:
                    if nuevo not in investigados and nuevo not in {t for t, _ in cola}:
                        cola.append((nuevo, profundidad + 1))
                        conocidos.add(nuevo)
                        stats["conceptos_encolados"] += 1

                if nuevos:
                    print(magenta(f"     🔗 Nuevos en cola: {', '.join(nuevos[:3])}"
                                  f"{'...' if len(nuevos) > 3 else ''}"))

                # Pausa para no saturar Wikipedia
                time.sleep(pausa_entre)

            stats["articulos_leidos"] = articulo_num

            # ── CICLO DE SUEÑO cada N articulos ──
            if articulo_num > 0 and articulo_num % dormir_cada == 0:
                print()
                sep("SUEÑO")
                print(f"😴 Consolidando despues de {articulo_num} articulos...")
                try:
                    resultado_sueno = ai.sleep()
                    stats["ciclos_sueno"] += 1
                    for linea in resultado_sueno.split("\n"):
                        if linea.strip():
                            print(gris(f"   {linea}"))
                except Exception as e:
                    print(amarillo(f"   (sleep error: {e})"))

                # Mostrar estado cognitivo rapido
                try:
                    estado = ai.metacog.introspect()
                    print(gris(
                        f"   Estado: {estado['active_memories']} memorias | "
                        f"{estado['concepts']} conceptos | "
                        f"{estado['kg_edges']} aristas"
                    ))
                except Exception:
                    pass

                print(gris(f"   Cola pendiente: {len(cola)} terminos"))
                sep()
                print()

    except KeyboardInterrupt:
        print()
        print(amarillo("\n⚠️  Interrumpido por el usuario."))

    # ── SUEÑO FINAL ────────────────────────────────────────────────────
    print()
    sep("SUEÑO FINAL")
    print("😴 Consolidando todo el conocimiento adquirido...")
    try:
        resultado_final = ai.sleep()
        stats["ciclos_sueno"] += 1
        for linea in resultado_final.split("\n"):
            if linea.strip():
                print(gris(f"   {linea}"))
    except Exception as e:
        print(amarillo(f"   (sleep error: {e})"))

    # ── RESUMEN ────────────────────────────────────────────────────────
    duracion = (datetime.now() - datetime.fromisoformat(stats["inicio"]))
    horas_dur = duracion.total_seconds() / 3600

    print()
    sep("RESUMEN FINAL")
    print(verde(f"  ✅ Articulos leidos      : {stats['articulos_leidos']}"))
    print(verde(f"  💾 Episodios guardados   : {stats['episodios_guardados']}"))
    print(verde(f"  🕸️  Hechos en grafo       : {stats['hechos_grafo']}"))
    print(verde(f"  🔗 Conceptos encadenados : {stats['conceptos_encolados']}"))
    print(verde(f"  😴 Ciclos de sueño       : {stats['ciclos_sueno']}"))
    print(verde(f"  ⏱️  Duracion              : {horas_dur:.1f}h"))
    print(verde(f"  ❌ Errores               : {stats['errores']}"))

    try:
        estado_final = ai.metacog.introspect()
        print()
        print(cyan("  Estado cognitivo final:"))
        print(f"    Memorias activas  : {estado_final['active_memories']}")
        print(f"    Conceptos         : {estado_final['concepts']}")
        print(f"    Aristas en grafo  : {estado_final['kg_edges']}")
        print(f"    Seq. temporales   : {estado_final['temporal_sequences']}")
    except Exception:
        pass

    sep()
    print(f"\n  Cognia ahora sabe mucho mas sobre {cyan(tema_inicial)} 🧠\n")
    print(f"  Prueba en la web:")
    print(cyan(f"    grafo {tema_inicial.lower().replace(' ', '_')[:20]}"))
    print(cyan(f"    inferir {tema_inicial.lower().replace(' ', '_')[:20]}"))
    print()

    return stats


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cognia — Investigacion nocturna encadenada",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python investigacion_nocturna.py "inteligencia artificial"
  python investigacion_nocturna.py "machine learning" --lang en
  python investigacion_nocturna.py "redes neuronales" --hasta 08:00 --max 300
  python investigacion_nocturna.py "python" --dormir-cada 3 --cadena 5
        """
    )
    parser.add_argument("tema",
                        help='Tema inicial (ej: "inteligencia artificial")')
    parser.add_argument("--lang", default="es", choices=["es", "en"],
                        help="Idioma de Wikipedia (default: es)")
    parser.add_argument("--max", type=int, default=500, dest="max_articulos",
                        help="Maximo de articulos a leer (default: 500)")
    parser.add_argument("--dormir-cada", type=int, default=5, dest="dormir_cada",
                        help="Ciclo de sueno cada N articulos (default: 5)")
    parser.add_argument("--hasta", default="10:00", dest="hora_parada",
                        help="Hora de parada HH:MM (default: 10:00)")
    parser.add_argument("--cadena", type=int, default=3, dest="profundidad",
                        help="Conceptos nuevos a encolar por articulo (default: 3)")
    parser.add_argument("--pausa", type=float, default=2.0,
                        help="Pausa entre articulos en segundos (default: 2.0)")

    args = parser.parse_args()

    investigacion_nocturna(
        tema_inicial      = args.tema,
        lang              = args.lang,
        max_articulos     = args.max_articulos,
        dormir_cada       = args.dormir_cada,
        hora_parada       = args.hora_parada,
        pausa_entre       = args.pausa,
        profundidad_cadena = args.profundidad
    )
