"""
investigacion_masiva.py — Cognia aprende sobre el mundo
========================================================
Lanza investigacion encadenada sobre decenas de temas variados.
Cognia aprende filosofia, ciencia, historia, tecnologia, arte y mas.

USO:
  python investigacion_masiva.py
  python investigacion_masiva.py --max-por-tema 10 --hasta 08:00
  python investigacion_masiva.py --categorias filosofia,ciencia,historia
  python investigacion_masiva.py --rapido   (3 articulos por tema, para probar)
"""

# FIX: rate limiting para evitar abuse de APIs externas
import time as _time_rl
_LAST_REQ_TS = 0.0
_REQ_INTERVAL = 1.5

def _rl_urlopen(req, timeout=15):
    global _LAST_REQ_TS
    wait = _REQ_INTERVAL - (_time_rl.time() - _LAST_REQ_TS)
    if wait > 0:
        _time_rl.sleep(wait)
    _LAST_REQ_TS = _time_rl.time()
    return __import__('urllib.request', fromlist=['urlopen']).urlopen(req, timeout=timeout)


import sys, os, time, argparse, random
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

# ── Colores ────────────────────────────────────────────────────────────
def _c(t, n): return f"\033[{n}m{t}\033[0m"
def verde(t):    return _c(t, 92)
def amarillo(t): return _c(t, 93)
def cyan(t):     return _c(t, 96)
def gris(t):     return _c(t, 90)
def magenta(t):  return _c(t, 95)
def rojo(t):     return _c(t, 91)
def negrita(t):  return _c(t, 1)

def sep(titulo=""):
    if titulo:
        r = max(0, (60 - len(titulo)) // 2)
        print(cyan("=" * r + f" {titulo} " + "=" * r))
    else:
        print(gris("─" * 64))

# ── TEMAS ORGANIZADOS POR CATEGORIA ───────────────────────────────────
TEMAS = {
    "filosofia": [
        "filosofia", "Socrates", "Platon", "Aristoteles",
        "Immanuel Kant", "Friedrich Nietzsche", "Rene Descartes",
        "etica", "logica", "metafisica", "epistemologia",
        "existencialismo", "estoicismo", "empirismo", "racionalismo",
        "filosofia oriental", "budismo", "taoismo",
    ],
    "ciencia": [
        "fisica cuantica", "teoria de la relatividad", "Albert Einstein",
        "Isaac Newton", "evolucion biologica", "Charles Darwin",
        "ADN", "celula", "neurociencia", "cosmologia",
        "agujero negro", "materia oscura", "termodinamica",
        "quimica organica", "tabla periodica", "Marie Curie",
        "Stephen Hawking", "teoria del big bang",
    ],
    "historia": [
        "historia de Roma", "Grecia antigua", "Egipto antiguo",
        "Revolucion Francesa", "Segunda Guerra Mundial",
        "Revolucion Industrial", "Renacimiento", "Edad Media",
        "Imperio Otomano", "civilizacion maya", "Aztecas",
        "Guerra Fria", "colonizacion de America",
        "Revolucion Rusa", "Napoleon Bonaparte",
    ],
    "tecnologia": [
        "inteligencia artificial", "machine learning", "redes neuronales",
        "computacion cuantica", "blockchain", "internet de las cosas",
        "ciberseguridad", "programacion", "algoritmo",
        "base de datos", "sistema operativo", "Linux",
        "historia de la computacion", "Alan Turing",
        "realidad virtual", "nanotecnologia", "robotica",
    ],
    "matematicas": [
        "matematicas", "algebra", "calculo diferencial",
        "geometria", "teoria de numeros", "estadistica",
        "probabilidad", "topologia", "teoria de grafos",
        "logica matematica", "Leonhard Euler", "Carl Friedrich Gauss",
        "numero pi", "numeros primos", "serie de Fibonacci",
    ],
    "arte_cultura": [
        "arte", "pintura", "Leonardo da Vinci", "Miguel Angel",
        "literatura", "William Shakespeare", "Miguel de Cervantes",
        "musica clasica", "Ludwig van Beethoven", "Wolfgang Amadeus Mozart",
        "arquitectura", "cine", "fotografia",
        "poesia", "novela", "teatro griego",
    ],
    "biologia": [
        "biologia", "ecosistema", "fotosintesis", "genetica",
        "evolucion", "clasificacion biologica", "celula eucariota",
        "virus", "bacteria", "sistema nervioso", "cerebro humano",
        "corazon", "sistema inmunologico", "proteina",
        "CRISPR", "clonacion", "biodiversidad",
    ],
    "geografia": [
        "geografia", "continentes", "oceanos", "clima",
        "cambio climatico", "Amazonia", "Sahara",
        "Himalaya", "corrientes oceanicas", "placas tectonicas",
        "volcanes", "terremotos", "rios del mundo",
        "energia renovable", "calentamiento global",
    ],
    "psicologia": [
        "psicologia", "Sigmund Freud", "Carl Jung",
        "behaviorismo", "psicologia cognitiva", "memoria",
        "emocion", "inteligencia", "personalidad",
        "inconsciente", "sueno", "motivacion",
        "aprendizaje", "percepcion", "lenguaje",
    ],
    "economia": [
        "economia", "capitalismo", "socialismo",
        "Adam Smith", "Karl Marx", "macroeconomia",
        "microeconomia", "inflacion", "mercado financiero",
        "globalizacion", "comercio internacional",
        "criptomonedas", "banco central", "PIB",
            ],
    "videojuegos": [
        "historia de los videojuegos", "Atari", "Nintendo",
        "Sega", "PlayStation", "Xbox",
        "Game Boy", "arcade", "Pong",
        "Super Mario", "The Legend of Zelda", "Sonic the Hedgehog",
        "Doom", "Minecraft", "Grand Theft Auto",
        "inteligencia artificial en videojuegos", "motor de videojuego",
        "Unity", "Unreal Engine", "pixel art",
        "desarrollo de videojuegos", "game design", "speedrunning",
        "esports", "realidad virtual videojuegos", "indie games",
    ],
}

def calcular_hora_parada(hora_str):
    h, m = map(int, hora_str.split(":"))
    ahora = datetime.now()
    parada = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    if parada <= ahora:
        parada += timedelta(days=1)
    return parada

def tiempo_restante(parada):
    delta = parada - datetime.now()
    if delta.total_seconds() <= 0:
        return "0m"
    horas = int(delta.total_seconds() // 3600)
    minutos = int((delta.total_seconds() % 3600) // 60)
    return f"{horas}h {minutos}m"

def investigar_tema(ai, tema, lang, max_art, pausa, stats_globales):
    """Investiga un tema usando investigacion_nocturna como motor."""
    from investigacion_nocturna import (
        buscar_titulos_wikipedia, obtener_articulo,
        extraer_parrafos, extraer_conceptos_del_texto
    )
    try:
        from investigador import extraer_hechos_simples
        tiene_investigador = True
    except ImportError:
        tiene_investigador = False

    titulos = buscar_titulos_wikipedia(tema, lang=lang, n=3)
    if not titulos:
        print(gris(f"    Sin resultados para '{tema}'"))
        return 0, 0

    ep_total = 0
    hechos_total = 0
    label = tema.lower().replace(" ", "_")[:25]

    for titulo in titulos[:max_art]:
        texto = obtener_articulo(titulo, lang=lang)
        if not texto or len(texto) < 100:
            if lang == "es":
                texto = obtener_articulo(titulo, lang="en")
            if not texto or len(texto) < 100:
                continue

        parrafos = extraer_parrafos(texto)
        for parrafo in parrafos[:12]:
            try:
                ai.learn(parrafo, label)
                ep_total += 1
            except Exception:
                pass

        if tiene_investigador:
            try:
                hechos = extraer_hechos_simples(titulo, texto)
                for h in hechos:
                    try:
                        ai.kg.add_triple(h["subject"], h["predicate"], h["object"],
                                         weight=0.8, source="masiva")
                        hechos_total += 1
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            triples = ai.kg.extract_triples_from_text(texto[:1000], label)
            for subj, pred, obj in triples:
                try:
                    if ai.kg.add_triple(subj, pred, obj, weight=0.7, source="masiva"):
                        hechos_total += 1
                except Exception:
                    pass
        except Exception:
            pass

        print(gris(f"      📖 {titulo}: {ep_total} eps, {hechos_total} hechos"))
        time.sleep(pausa)

    stats_globales["episodios"] += ep_total
    stats_globales["hechos"]    += hechos_total
    stats_globales["temas"]     += 1
    return ep_total, hechos_total


def investigacion_masiva(
    categorias_sel=None,
    max_por_tema=8,
    hora_parada="10:00",
    pausa=1.5,
    lang="es",
    aleatorio=True,
):
    parada_dt = calcular_hora_parada(hora_parada)

    sep("COGNIA — INVESTIGACION MASIVA")
    print(f"  Parada programada : {hora_parada} ({tiempo_restante(parada_dt)} restantes)")
    print(f"  Articulos/tema    : {max_por_tema}")
    print(f"  Idioma            : {lang}")
    print(f"  Orden             : {'aleatorio' if aleatorio else 'secuencial'}")
    sep()

    # Seleccionar categorias
    if categorias_sel:
        cats = {k: v for k, v in TEMAS.items() if k in categorias_sel}
    else:
        cats = TEMAS

    # Armar lista de temas
    todos = []
    for cat, temas in cats.items():
        for t in temas:
            todos.append((cat, t))

    if aleatorio:
        random.shuffle(todos)

    total_temas = len(todos)
    print(f"  Total de temas    : {total_temas} en {len(cats)} categorias")
    sep()

    # Iniciar Cognia
    print(f"\nIniciando Cognia...", end=" ", flush=True)
    from cognia import Cognia
    ai = Cognia()
    print(verde("lista\n"))

    stats = {
        "episodios": 0, "hechos": 0, "temas": 0,
        "ciclos_sueno": 0, "inicio": datetime.now().isoformat()
    }

    try:
        for i, (categoria, tema) in enumerate(todos, 1):
            # Verificar hora de parada
            if datetime.now() >= parada_dt:
                print(amarillo(f"\n⏰ Hora de parada alcanzada ({hora_parada})"))
                break

            tiempo_left = tiempo_restante(parada_dt)
            print(negrita(f"\n[{i}/{total_temas}] {categoria.upper()} → {cyan(tema)} ({tiempo_left} restantes)"))

            ep, hec = investigar_tema(ai, tema, lang, max_por_tema, pausa, stats)
            print(verde(f"    ✅ {ep} episodios | {hec} hechos nuevos | "
                       f"Total acumulado: {stats['episodios']} eps"))

            # Consolidar cada 10 temas
            if stats["temas"] % 10 == 0 and stats["temas"] > 0:
                sep("CONSOLIDACION")
                print("😴 Consolidando conocimiento...")
                try:
                    resultado = ai.sleep()
                    stats["ciclos_sueno"] += 1
                    for linea in resultado.split("\n")[:5]:
                        if linea.strip():
                            print(gris(f"   {linea}"))
                except Exception as e:
                    print(amarillo(f"   (sleep error: {e})"))
                sep()

    except KeyboardInterrupt:
        print(amarillo("\n\n⚠️  Interrumpido. Consolidando lo aprendido..."))

    # Consolidacion final
    sep("CONSOLIDACION FINAL")
    print("😴 Consolidando todo el conocimiento adquirido...")
    try:
        ai.sleep()
        stats["ciclos_sueno"] += 1
    except Exception as e:
        print(amarillo(f"   (sleep error: {e})"))

    # Resumen
    duracion = datetime.now() - datetime.fromisoformat(stats["inicio"])
    sep("RESUMEN")
    print(verde(f"  Temas investigados  : {stats['temas']} / {total_temas}"))
    print(verde(f"  Episodios guardados : {stats['episodios']}"))
    print(verde(f"  Hechos en grafo     : {stats['hechos']}"))
    print(verde(f"  Ciclos de sueno     : {stats['ciclos_sueno']}"))
    print(verde(f"  Duracion total      : {duracion.total_seconds()/60:.0f} minutos"))

    try:
        estado = ai.metacog.introspect()
        print()
        print(cyan("  Estado cognitivo:"))
        print(f"    Memorias activas : {estado['active_memories']}")
        print(f"    Conceptos        : {estado['concepts']}")
        print(f"    Aristas en grafo : {estado['kg_edges']}")
    except Exception:
        pass

    sep()
    print(f"\n  Cognia ahora tiene conocimiento enciclopedico. Prueba:\n")
    print(cyan("    python -m cognia"))
    print(cyan("    > que es la filosofia"))
    print(cyan("    > inferir inteligencia_artificial"))
    print(cyan("    > grafo evolucion"))
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cognia — Investigacion masiva sobre el mundo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python investigacion_masiva.py
  python investigacion_masiva.py --rapido
  python investigacion_masiva.py --hasta 08:00 --max-por-tema 15
  python investigacion_masiva.py --categorias filosofia,ciencia,historia
  python investigacion_masiva.py --categorias tecnologia --lang en
        """
    )
    parser.add_argument("--max-por-tema", type=int, default=8,
                        help="Articulos de Wikipedia por tema (default: 8)")
    parser.add_argument("--hasta", default="10:00", dest="hora_parada",
                        help="Hora de parada HH:MM (default: 10:00)")
    parser.add_argument("--categorias", default=None,
                        help="Categorias separadas por coma: filosofia,ciencia,historia,tecnologia,matematicas,arte_cultura,biologia,geografia,psicologia,economia")
    parser.add_argument("--lang", default="es", choices=["es", "en"],
                        help="Idioma de Wikipedia (default: es)")
    parser.add_argument("--pausa", type=float, default=1.5,
                        help="Pausa entre articulos en segundos (default: 1.5)")
    parser.add_argument("--rapido", action="store_true",
                        help="Modo rapido: 3 articulos por tema (para probar)")
    parser.add_argument("--secuencial", action="store_true",
                        help="Orden secuencial en vez de aleatorio")

    args = parser.parse_args()

    cats = None
    if args.categorias:
        cats = [c.strip() for c in args.categorias.split(",")]

    max_art = 3 if args.rapido else args.max_por_tema

    investigacion_masiva(
        categorias_sel=cats,
        max_por_tema=max_art,
        hora_parada=args.hora_parada,
        pausa=args.pausa,
        lang=args.lang,
        aleatorio=not args.secuencial,
    )
