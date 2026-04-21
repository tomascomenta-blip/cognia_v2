"""
investigador.py — Módulo de investigación autónoma para Cognia v3
=================================================================
Cuando Cognia no sabe algo:
  1. Busca en Wikipedia (sin API key)
  2. Extrae conceptos y hechos clave
  3. Los guarda en su memoria y grafo
  4. Genera hipotesis relacionando lo nuevo con lo que ya sabe
  5. Devuelve el contexto enriquecido para que Llama responda bien

USO:
  from investigador import investigar_si_necesario
  contexto = investigar_si_necesario(ai, pregunta, contexto_actual)
"""

import urllib.request
import urllib.parse
import json
import re
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ── Wikipedia ─────────────────────────────────────────────────────────

def buscar_wikipedia(query, idioma="es"):
    """Busca en Wikipedia y devuelve el resumen del artículo más relevante."""
    try:
        # Primero buscar el titulo exacto
        params = urllib.parse.urlencode({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 5,
            "format": "json",
            "utf8": 1
        })
        url = f"https://{idioma}.wikipedia.org/w/api.php?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Cognia/3.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        resultados = data.get("query", {}).get("search", [])
        if not resultados:
            if idioma == "es":
                return buscar_wikipedia(query, idioma="en")
            return None

        # Elegir el resultado más relevante: preferir titulos cortos y directos
        # evitar titulos que contengan palabras como "videojuego", "película", "película"
        palabras_evitar = ["videojuego", "película", "pelicula", "serie", "canción", "cancion", "album", "álbum"]
        titulo = None
        for r in resultados:
            t = r["title"].lower()
            if not any(p in t for p in palabras_evitar):
                titulo = r["title"]
                break
        if not titulo:
            titulo = resultados[0]["title"]

        # Obtener el resumen del artículo
        params2 = urllib.parse.urlencode({
            "action": "query",
            "titles": titulo,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "exsentences": 8,
            "format": "json",
            "utf8": 1
        })
        url2 = f"https://{idioma}.wikipedia.org/w/api.php?{params2}"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "Cognia/3.0"})
        with urllib.request.urlopen(req2, timeout=10) as r2:
            data2 = json.loads(r2.read())

        pages = data2.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        extracto = page.get("extract", "").strip()

        if not extracto:
            return None

        return {
            "titulo": titulo,
            "extracto": extracto[:1500],  # Máximo 1500 chars
            "url": f"https://{idioma}.wikipedia.org/wiki/{urllib.parse.quote(titulo)}",
            "idioma": idioma
        }

    except Exception as e:
        return None



def buscar_duckduckgo(query):
    """
    Busca en DuckDuckGo Instant Answer API (sin API key, gratis).
    Úsalo como fallback cuando Wikipedia no encuentra nada.
    """
    try:
        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1"
        })
        url = f"https://api.duckduckgo.com/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Cognia/3.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        # Intentar Abstract (respuesta directa)
        abstract = data.get("AbstractText", "").strip()
        titulo = data.get("Heading", query)
        url_fuente = data.get("AbstractURL", "")

        if abstract and len(abstract) > 50:
            return {
                "titulo": titulo,
                "extracto": abstract[:1500],
                "url": url_fuente,
                "idioma": "en",
                "fuente": "duckduckgo"
            }

        # Intentar RelatedTopics si no hay Abstract
        topics = data.get("RelatedTopics", [])
        snippets = []
        for t in topics[:3]:
            if isinstance(t, dict) and t.get("Text"):
                snippets.append(t["Text"])
        
        if snippets:
            return {
                "titulo": titulo or query,
                "extracto": " ".join(snippets)[:1500],
                "url": url_fuente or f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
                "idioma": "en",
                "fuente": "duckduckgo_topics"
            }

    except Exception:
        pass
    return None


# ── Extractor de hechos ────────────────────────────────────────────────

def extraer_hechos_simples(titulo, extracto):
    """
    Extrae hechos basicos del texto para guardar en el grafo.
    Sin NLP pesado — usa patrones simples.
    """
    hechos = []
    titulo_limpio = titulo.lower().replace(" ", "_")

    # Hecho 1: is_a — primera oración suele definir qué es
    primera = extracto.split(".")[0].strip()
    if primera:
        hechos.append({
            "subject": titulo_limpio,
            "predicate": "is_a",
            "object": "concepto_investigado"
        })

    # Hecho 2: has_description
    hechos.append({
        "subject": titulo_limpio,
        "predicate": "has_description",
        "object": primera[:80].lower().replace(" ", "_") if primera else "desconocido"
    })

    # Hecho 3: Detectar categorias comunes
    texto_lower = extracto.lower()
    categorias = {
        "deporte": ["juego", "deporte", "atleta", "equipo", "competencia", "jugador", "pelota"],
        "ciencia": ["científico", "investigación", "teoría", "experimento", "física", "química"],
        "tecnologia": ["software", "programa", "computadora", "algoritmo", "sistema", "digital"],
        "historia": ["siglo", "guerra", "rey", "imperio", "civilización", "antiguo"],
        "arte": ["música", "pintura", "artista", "obra", "cultural", "literatura"],
        "persona": ["nació", "nacido", "escritor", "científico", "político", "presidente"],
        "lugar": ["ciudad", "país", "región", "territorio", "capital", "ubicado"],
    }
    for categoria, palabras in categorias.items():
        if any(p in texto_lower for p in palabras):
            hechos.append({
                "subject": titulo_limpio,
                "predicate": "related_to",
                "object": categoria
            })
            break

    return hechos


# ── Generador de hipotesis ─────────────────────────────────────────────

def generar_hipotesis(ai, titulo, extracto):
    """
    Conecta el nuevo conocimiento con lo que Cognia ya sabe
    y genera hipotesis relacionales.
    """
    hipotesis = []
    titulo_limpio = titulo.lower().replace(" ", "_")
    texto_lower = extracto.lower()

    try:
        # Ver qué conceptos ya conoce Cognia
        conceptos_conocidos = []
        cursor = ai.db.execute("SELECT concept FROM semantic_memory LIMIT 50")
        for row in cursor.fetchall():
            conceptos_conocidos.append(row[0])

        # Si algún concepto conocido aparece en el texto nuevo → hipotesis de relacion
        for concepto in conceptos_conocidos:
            if concepto.lower() in texto_lower and concepto.lower() != titulo_limpio:
                hipotesis.append(
                    f"{titulo} podría estar relacionado con {concepto} "
                    f"basándome en que ambos aparecen en el mismo contexto."
                )

        # Hipótesis temporal: si menciona fechas/anios
        anios = re.findall(r'\b(1[0-9]{3}|20[0-2][0-9])\b', extracto)
        if anios:
            hipotesis.append(
                f"{titulo} tiene relevancia histórica — mencionado en el contexto de {', '.join(set(anios[:3]))}."
            )

    except Exception:
        pass

    return hipotesis[:3]  # Máximo 3 hipotesis


# ── Guardado en memoria ────────────────────────────────────────────────

def guardar_en_cognia(ai, titulo, extracto, hechos, pregunta_original):
    """
    Guarda lo investigado en la memoria episodica y el grafo de Cognia.
    Si el concepto ya existe, lo enriquece en lugar de duplicarlo.
    """
    guardado = {"episodios": 0, "hechos_grafo": 0, "actualizado": False}

    try:
        from cognia_v3 import text_to_vector, analyze_emotion
        import sqlite3

        # Usar el título completo como label (sin truncar)
        titulo_label = titulo.lower().replace(" ", "_").replace("(", "").replace(")", "").strip("_")
        # Limpiar chars problemáticos pero mantener longitud completa
        titulo_label = re.sub(r"[^a-z0-9áéíóúüñ_]", "_", titulo_label)
        titulo_label = re.sub(r"_+", "_", titulo_label).strip("_")

        resumen = f"{titulo}: {extracto[:300]}"
        vec = text_to_vector(resumen)
        emotion = analyze_emotion(resumen)

        # Verificar si ya existe un episodio similar para ESTE concepto
        db_path = getattr(ai.episodic, 'db', 'cognia_memory.db')
        conn = sqlite3.connect(db_path)
        conn.text_factory = str
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM episodic_memory
            WHERE label = ? AND forgotten = 0
        """, (titulo_label,))
        ya_existe = c.fetchone()[0]
        conn.close()

        if ya_existe > 0:
            # El concepto ya existe — enriquecer la memoria semántica pero
            # no duplicar episodios. Solo agregar si el extracto es diferente.
            guardado["actualizado"] = True
            try:
                ai.semantic.update_concept(
                    titulo_label, vec,
                    description=resumen[:200],
                    confidence_delta=0.05  # refuerzo leve
                )
            except Exception:
                pass
        else:
            # Concepto nuevo — guardar episodio completo
            ai.episodic.store(
                observation=resumen,
                label=titulo_label,
                vector=vec,
                confidence=0.75,
                importance=0.8,
                emotion=emotion,
                surprise=0.6,
                context_tags=["investigado", "wikipedia"]
            )
            guardado["episodios"] += 1

            try:
                ai.semantic.update_concept(
                    titulo_label, vec,
                    description=resumen[:200],
                    confidence_delta=0.1
                )
            except Exception:
                pass

        # Guardar hechos en el grafo (siempre, nuevos refuerzan peso)
        for hecho in hechos:
            try:
                ai.kg.add_triple(
                    hecho["subject"],
                    hecho["predicate"],
                    hecho["object"]
                )
                guardado["hechos_grafo"] += 1
            except Exception:
                pass

    except Exception:
        pass

    return guardado


# ── Función principal ──────────────────────────────────────────────────

def necesita_investigar(contexto_actual, umbral_episodios=1):
    """
    Decide si Cognia necesita investigar.
    Investiga si no hay episodios con información real (etiqueta real y similitud > 0.3).
    
    Mejoras v3.1:
    - Ignora episodios con etiqueta 'ninguna', None, o vacía
    - Ignora episodios que son preguntas guardadas (label=None)
    - Ignora contexto de baja similitud (<30%)
    - Cuenta solo episodios con contenido sustancial y etiqueta real
    """
    if not contexto_actual:
        return True

    lineas = contexto_actual.split("\n")
    episodios_utiles = 0
    
    # Palabras que indican que el episodio ES una pregunta, no conocimiento
    es_pregunta = ["que es", "que son", "como", "cual", "dime", "explica",
                   "qué es", "qué son", "cómo", "cuál", "quién", "quien",
                   "dónde", "donde", "cuándo", "cuando", "háblame", "hablame",
                   "cuéntame", "cuentame", "qué sabes", "que sabes"]
    
    # Etiquetas o contenidos que no aportan conocimiento real
    etiquetas_vacias = ["ninguna", "none", "null", "", "investigado"]

    for linea in lineas:
        linea_strip = linea.strip()
        if not linea_strip.startswith("- '"):
            continue
        
        # Extraer similitud: buscar "sim: XX%"
        sim_match = re.search(r'sim: ([\d.]+)%', linea_strip)
        if sim_match:
            sim_val = float(sim_match.group(1))
            if sim_val < 30:  # Ignorar episodios de baja similitud
                continue
        
        # Extraer etiqueta
        etiqueta_match = re.search(r'etiqueta: ([^,)]+)', linea_strip)
        if etiqueta_match:
            etiqueta = etiqueta_match.group(1).strip().lower()
            if any(e == etiqueta for e in etiquetas_vacias):
                continue
        else:
            continue  # Sin etiqueta = sin conocimiento real
        
        # Extraer contenido del episodio
        contenido_match = re.match(r"- '(.+?)'", linea_strip)
        if not contenido_match:
            continue
        contenido = contenido_match.group(1).lower().strip()
        
        # Ignorar si el contenido ES una pregunta
        if any(contenido.startswith(p) for p in es_pregunta):
            continue
        
        # Debe tener longitud mínima de contenido informativo
        if len(contenido) < 30:
            continue
        
        episodios_utiles += 1

    return episodios_utiles < umbral_episodios


def investigar_si_necesario(ai, pregunta, contexto_actual):
    """
    Función principal. Llámala desde respuestas_articuladas.py.
    Si el contexto es pobre, investiga en Wikipedia, guarda en memoria
    y devuelve un contexto enriquecido.

    Retorna: (contexto_nuevo, fue_investigado, info_investigacion)
    """
    if not necesita_investigar(contexto_actual):
        return contexto_actual, False, None

    # Extraer término de busqueda de la pregunta
    termino = limpiar_pregunta(pregunta)
    if not termino:
        return contexto_actual, False, None

    # Buscar primero en Wikipedia, luego DuckDuckGo como fallback
    resultado = buscar_wikipedia(termino)
    if not resultado:
        resultado = buscar_duckduckgo(termino)
    if not resultado:
        return contexto_actual, False, None

    titulo = resultado["titulo"]
    extracto = resultado["extracto"]

    # Extraer hechos y generar hipotesis
    hechos = extraer_hechos_simples(titulo, extracto)
    hipotesis = generar_hipotesis(ai, titulo, extracto)

    # Guardar en la memoria de Cognia
    guardado = guardar_en_cognia(ai, titulo, extracto, hechos, pregunta)

    # Construir bloque de contexto con lo investigado
    bloque_investigacion = f"""INVESTIGACIÓN AUTÓNOMA (Wikipedia):
Encontré información sobre: {titulo}
{extracto[:600]}"""

    if hipotesis:
        bloque_investigacion += "\n\nHIPÓTESIS GENERADAS:\n" + "\n".join(f"- {h}" for h in hipotesis)

    bloque_investigacion += f"\n\n[Guardé {guardado['episodios']} episodio(s) y {guardado['hechos_grafo']} hecho(s) en mi memoria]"

    # Combinar con contexto previo si había algo
    if contexto_actual:
        contexto_nuevo = contexto_actual + "\n\n" + bloque_investigacion
    else:
        contexto_nuevo = bloque_investigacion

    info = {
        "titulo": titulo,
        "url": resultado["url"],
        "idioma": resultado["idioma"],
        "hechos_guardados": guardado["hechos_grafo"],
        "hipotesis": hipotesis
    }

    return contexto_nuevo, True, info


def limpiar_pregunta(pregunta):
    """Extrae el término principal de busqueda de una pregunta."""
    pregunta = pregunta.strip()

    # Eliminar prefijos de pregunta
    prefijos = [
        r"^(qué|que|cuál|cual|cómo|como|quién|quien|dónde|donde|cuándo|cuando)\s+(es|son|fue|era|significa|hay)\s+",
        r"^(háblame|hablame|cuéntame|cuentame|explícame|explicame)\s+(de|sobre|acerca de)\s+",
        r"^(qué|que)\s+sabes\s+(de|sobre|acerca de)\s+",
        r"^(información|informacion|info)\s+(de|sobre|acerca de)\s+",
        r"^(dime\s+)?(qué|que)\s+es\s+(el|la|los|las|un|una)?\s*",
        r"^(dime\s+)?(qué|que)\s+son\s+(los|las)?\s*",
    ]

    texto = pregunta.lower()
    for patron in prefijos:
        texto = re.sub(patron, "", texto, flags=re.IGNORECASE).strip()

    # Quitar signos de puntuación al final
    texto = re.sub(r'[¿?¡!.,;:]+$', '', texto).strip()
    texto = re.sub(r'^[¿?¡!]+', '', texto).strip()

    return texto if len(texto) > 2 else pregunta.strip()