"""
limpiar_memoria.py — Cognia: Limpieza selectiva de memoria
===========================================================
Elimina ruido de Wikipedia de episodic_memory y semantic_memory
SIN tocar conocimiento real de Cognia.

Ejecutar desde el directorio de cognia_v2:
    python limpiar_memoria.py

Hace backup automático antes de cualquier cambio.
Muestra resumen ANTES de borrar y pide confirmación.
"""

import sqlite3
import shutil
import os
from datetime import datetime

DB_PATH = "cognia_memory.db"
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
BAK_PATH = f"cognia_memory.db.bak_{TS}"

# ══════════════════════════════════════════════════════════════════════
# LABELS EPISÓDICOS A ELIMINAR
# Palabras genéricas / fragmentos de Wikipedia que no aportan
# ══════════════════════════════════════════════════════════════════════

LABELS_RUIDO_EPISODIC = {
    # Palabras genéricas en inglés (Wikipedia scraping)
    "american", "beyond", "creating", "people", "places", "congress",
    "bellevue", "history", "series", "world", "church", "character",
    "characters", "literature", "career", "company", "works", "officers",
    "usually", "often", "january", "march", "august", "october",
    "november", "december", "sunday", "western", "known", "english",
    "french", "dutch", "danish", "swedish", "japanese", "latin",
    "greek", "ancient", "located", "derived", "formal", "informal",
    "common", "physical", "therefore", "anything", "something",
    "creator", "individual", "words", "logic", "usage", "concept",
    "approximately", "regularity", "unlike", "connotations", "these",
    "others", "desde", "hacia", "durante", "entre", "aunque",
    "algunas", "algunos", "muchas", "muchos", "todos", "estas",
    "estos", "tiene", "sistema", "antes", "mientras", "incluso",
    "generalmente", "normalmente", "usualmente", "esencialmente",
    "aproximadamente", "conforme", "dicho", "debido", "permite",
    "todas", "describir", "determinar", "encontrar", "donde", "ellos",
    "trata", "utiliza", "constituye", "adopta", "dichas", "ciudad",
    "guerra", "primera", "capital", "estado", "federal", "norte",
    "origen", "bases", "datos", "existen", "tipos", "canal", "cuenta",
    "orden", "dentro", "reino", "europe", "world", "international",
    "america", "north_america", "united_states", "washington",
    "california", "indiana", "alaska", "florida", "virginia",
    "england", "london", "oxford", "cambridge", "harvard", "stanford",
    # Fragmentos de nombres propios sin contexto
    "creating", "flickering", "precursors", "subgenres", "shoot",
    "shooter", "commissioned", "graduate", "usually", "ranked",
    # Etiquetas de una sola palabra vacía de significado
    "artificial", "beyond", "unlike", "connotations", "from_ancient",
    "these_nights", "regularity",
}

# ══════════════════════════════════════════════════════════════════════
# CONCEPTOS SEMÁNTICOS A ELIMINAR
# Palabras sueltas / ruido que se colaron como conceptos
# ══════════════════════════════════════════════════════════════════════

CONCEPTOS_RUIDO_SEMANTIC = {
    # Palabras sueltas en inglés sin valor semántico
    "artificial", "beyond", "unlike", "connotations", "creating",
    "these", "others", "approximately", "regularity", "from_ancient",
    "american", "people", "places", "series", "world", "church",
    "character", "characters", "literature", "career", "company",
    "works", "officers", "usually", "often", "western", "known",
    "english", "french", "dutch", "danish", "swedish", "japanese",
    "latin", "greek", "located", "derived", "formal", "informal",
    "common", "physical", "therefore", "anything", "something",
    "creator", "individual", "words", "logic", "usage", "concept",
    # Palabras sueltas en español
    "estas", "estos", "tiene", "sistema", "antes", "mientras",
    "incluso", "algunas", "algunos", "muchas", "muchos", "todos",
    "desde", "hacia", "durante", "entre", "aunque", "generalmente",
    "normalmente", "usualmente", "esencialmente", "aproximadamente",
    "conforme", "dicho", "debido", "permite", "todas", "describir",
    "determinar", "encontrar", "donde", "ellos", "trata", "utiliza",
    "constituye", "adopta", "dichas", "primera", "estado", "norte",
    "origen", "bases", "datos", "existen", "tipos", "cuenta", "orden",
    "dentro", "reino", "ciudad", "guerra", "capital", "federal",
    # Nombres de lugares genéricos sin contexto cognitivo
    "bellevue", "california", "indiana", "alaska", "florida",
    "virginia", "washington", "america", "north_america", "london",
    "oxford", "cambridge", "europe", "northern_europe",
    "southeast_europe", "greek", "attic_greek", "koine_greek",
    "hellenistic", "aeolic", "ancient_greek",
    # Fragmentos de nombres propios sueltos
    "hoshino", "hoshino\ncreate", "flickering", "precursors",
    "subgenres", "shoot", "shooter", "commissioned",
    "these_nights", "regularity", "from_ancient",
    # Conceptos duplicados o fragmentados
    "inteligencia_artificial_e",  # truncado
    "razonamiento_hipotetico_d",  # truncado
    "epistemologia_conocimient",  # truncado
    "historia_de_la_computacio",  # truncado
    "partido_nacionalsocialist",  # truncado
    "bundesrepublik_deutschlan",  # truncado
    "constitucionales\nrecurso",  # con salto de línea
    "naruto\nmaestro",            # con salto de línea
    # Conceptos de baja utilidad para Cognia
    "perro",          # solo 1 de soporte, no aprendido en profundidad
    "flask",          # framework, no conocimiento cognitivo
    "networkx",       # librería, idem
    "windows",        # OS, idem
    "microsoft_windows",
    "plantas_contra_zombis",
    "hola",           # saludo capturado como concepto
    "reich",
    "medievo",
    "marco_tulio",
    "glaschu",
    "alejandro",
    "flavel",
    "jack_flavell",
    "principales_wikiquote",
    "wikiquotes",
    "aprendizaje_ofrece",   # fragmento
    "aprendizaje_es",       # fragmento
    "modelo_y",             # fragmento
    "modelo_de",            # fragmento
    "modelo_basado",        # fragmento
    "modelo_permite",       # fragmento
    "modelo_acerca",        # fragmento
    "modelo_busca",         # fragmento
    "aprendizaje_y",        # fragmento
}

# ══════════════════════════════════════════════════════════════════════
# CONDICIONES ADICIONALES para episodic_memory
# Eliminar episodios donde la observación parece Wikipedia puro:
# - Empieza con nombre propio + "(año film)" o "(año series)"
# - Contiene fragmentos típicos de Wikipedia
# ══════════════════════════════════════════════════════════════════════

WIKIPEDIA_MARKERS = [
    "is a 20",          # "is a 2015 American..."
    "is an American",
    "is a Swedish",
    "is a Canadian",
    "is a Danish",
    "is a British",
    "is a Norwegian",
    "is a Finnish",
    "(film),",
    "(series),",
    "(TV series)",
    "a neighborhood in",
    "a proposed i",     # "a proposed infrastructure..."
    "web-based community",
    "research library in",
    "Green political party",
    "Incorporated place",
    "populated area with",
    "municipal corporation",
]


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str
    return conn


def analizar_antes():
    """Muestra qué se va a eliminar antes de hacerlo."""
    conn = conectar()
    c = conn.cursor()

    print("\n" + "=" * 60)
    print("  ANÁLISIS — qué se va a eliminar")
    print("=" * 60)

    # Episodios por label de ruido
    placeholders = ",".join("?" * len(LABELS_RUIDO_EPISODIC))
    c.execute(
        f"SELECT COUNT(*) FROM episodic_memory WHERE label IN ({placeholders})",
        list(LABELS_RUIDO_EPISODIC)
    )
    n_label = c.fetchone()[0]
    print(f"\nEpisodios con labels de ruido:        {n_label:>6}")

    # Episodios con marcadores de Wikipedia
    n_wiki = 0
    for marker in WIKIPEDIA_MARKERS:
        c.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE observation LIKE ?",
            (f"%{marker}%",)
        )
        n_wiki += c.fetchone()[0]
    print(f"Episodios con texto de Wikipedia:     {n_wiki:>6} (aprox, puede haber solapamiento)")

    # Total episodios
    c.execute("SELECT COUNT(*) FROM episodic_memory")
    total_ep = c.fetchone()[0]
    print(f"Total episodios actuales:             {total_ep:>6}")

    # Conceptos semánticos de ruido
    placeholders2 = ",".join("?" * len(CONCEPTOS_RUIDO_SEMANTIC))
    c.execute(
        f"SELECT COUNT(*) FROM semantic_memory WHERE concept IN ({placeholders2})",
        list(CONCEPTOS_RUIDO_SEMANTIC)
    )
    n_sem = c.fetchone()[0]
    print(f"\nConceptos semánticos de ruido:        {n_sem:>6}")

    # Total semánticos
    c.execute("SELECT COUNT(*) FROM semantic_memory")
    total_sem = c.fetchone()[0]
    print(f"Total conceptos semánticos actuales:  {total_sem:>6}")

    print(f"\nQuedarán episodios (estimado):        {total_ep - n_label:>6}")
    print(f"Quedarán conceptos (estimado):        {total_sem - n_sem:>6}")

    conn.close()
    return n_label, n_wiki, n_sem, total_ep, total_sem


def limpiar_episodic(conn):
    c = conn.cursor()
    eliminados = 0

    # 1. Por label de ruido
    placeholders = ",".join("?" * len(LABELS_RUIDO_EPISODIC))
    c.execute(
        f"DELETE FROM episodic_memory WHERE label IN ({placeholders})",
        list(LABELS_RUIDO_EPISODIC)
    )
    eliminados += c.rowcount
    print(f"  Episodios eliminados por label:      {c.rowcount:>6}")

    # 2. Por marcadores de Wikipedia en el texto
    wiki_total = 0
    for marker in WIKIPEDIA_MARKERS:
        c.execute(
            "DELETE FROM episodic_memory WHERE observation LIKE ?",
            (f"%{marker}%",)
        )
        wiki_total += c.rowcount
    eliminados += wiki_total
    print(f"  Episodios eliminados por Wikipedia:  {wiki_total:>6}")

    # 3. Episodios con confidence=0.6 exacto + importance entre 1.35-1.38
    #    (patrón típico de los episodios de CuriosidadPasiva de Wikipedia)
    c.execute("""
        DELETE FROM episodic_memory
        WHERE confidence = 0.6
          AND importance BETWEEN 1.35 AND 1.40
          AND forgotten = 0
          AND label NOT IN (
            'inteligencia_artificial', 'machine_learning', 'deep_learning',
            'python', 'sqlite', 'neuroplasticidad', 'jacobo_grinberg',
            'hormona_de_crecimiento_humano', 'dna_replication',
            'protein_synthesis', 'crispr_gene_editing', 'stem_cells',
            'epigenetics', 'mitochondria', 'telomere_aging',
            'neuroplasticity', 'consciousness_neuroscience', 'quantum_mind',
            'quantum_mechanics', 'quantum_entanglement', 'black_hole',
            'dark_matter', 'string_theory', 'large_language_models',
            'reinforcement_learning', 'quantum_computing',
            'neural_networks_deep_learning', 'game_theory',
            'information_theory_entropy', 'artificial_intelligence',
            'roblox', 'the_legend_of_zelda', 'atari', 'nintendo',
            'super_mario', 'minecraft', 'sonic_the_hedgehog'
          )
    """)
    eliminados += c.rowcount
    print(f"  Episodios Wikipedia por patrón conf: {c.rowcount:>6}")

    return eliminados


def limpiar_semantic(conn):
    c = conn.cursor()

    placeholders = ",".join("?" * len(CONCEPTOS_RUIDO_SEMANTIC))
    c.execute(
        f"DELETE FROM semantic_memory WHERE concept IN ({placeholders})",
        list(CONCEPTOS_RUIDO_SEMANTIC)
    )
    eliminados = c.rowcount
    print(f"  Conceptos semánticos eliminados:     {eliminados:>6}")
    return eliminados


def limpiar_response_cache(conn):
    """Limpiar el caché de respuestas — se regenera solo."""
    c = conn.cursor()
    c.execute("DELETE FROM response_cache")
    eliminados = c.rowcount
    print(f"  Entradas de response_cache limpiadas:{eliminados:>6}")
    return eliminados


def main():
    print("=" * 60)
    print("  COGNIA — Limpieza Selectiva de Memoria")
    print("=" * 60)

    if not os.path.exists(DB_PATH):
        print(f"\n[ERROR] No se encuentra {DB_PATH}")
        print("Ejecutar desde el directorio de cognia_v2.")
        return

    # Análisis previo
    n_label, n_wiki, n_sem, total_ep, total_sem = analizar_antes()

    print("\n" + "-" * 60)
    print("Se hará backup automático antes de modificar.")
    respuesta = input("¿Continuar con la limpieza? (s/n): ").strip().lower()

    if respuesta != "s":
        print("Limpieza cancelada.")
        return

    # Backup
    shutil.copy2(DB_PATH, BAK_PATH)
    print(f"\n[OK] Backup creado: {BAK_PATH}")

    # Limpiar
    print("\n--- Limpiando episodic_memory ---")
    conn = conectar()

    ep_eliminados = limpiar_episodic(conn)

    print("\n--- Limpiando semantic_memory ---")
    sem_eliminados = limpiar_semantic(conn)

    print("\n--- Limpiando response_cache ---")
    cache_eliminados = limpiar_response_cache(conn)

    conn.commit()

    # Verificar resultado
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM episodic_memory")
    ep_final = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM semantic_memory")
    sem_final = c.fetchone()[0]
    conn.close()

    # VACUUM para compactar la DB
    print("\n--- Compactando base de datos (VACUUM) ---")
    conn2 = sqlite3.connect(DB_PATH)
    conn2.execute("VACUUM")
    conn2.close()
    print("  [OK] VACUUM completado")

    print("\n" + "=" * 60)
    print("  RESUMEN")
    print("=" * 60)
    print(f"  Episodios eliminados:    {ep_eliminados:>6}")
    print(f"  Episodios restantes:     {ep_final:>6}")
    print(f"  Conceptos eliminados:    {sem_eliminados:>6}")
    print(f"  Conceptos restantes:     {sem_final:>6}")
    print(f"  Cache limpiado:          {cache_eliminados:>6} entradas")
    print(f"\n  Backup disponible en:   {BAK_PATH}")
    print("\n[OK] Limpieza completada. Reinicia web_app.py para aplicar.")


if __name__ == "__main__":
    main()
