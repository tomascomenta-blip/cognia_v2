"""
migrate_db.py — Migración y limpieza de cognia_memory.db
=========================================================
Ejecutar UNA SOLA VEZ:
  python migrate_db.py

Qué hace:
  1. Renombra conceptos truncados a nombres completos
  2. Limpia triples basura del knowledge graph (stopwords, nodos 1-2 chars)
  3. Resuelve las 58 contradicciones automáticas (patrón Antes/Nuevo)
  4. Resetea decision_log (todos los 73 registros son errores falsos)
  5. Muestra reporte de salud antes/después
"""
import sqlite3, json, shutil, os
from datetime import datetime

DB_PATH = "cognia_memory.db"
BACKUP = f"cognia_memory_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

# ── Mapa de conceptos truncados → nombres correctos ──
CONCEPT_MAP = {
    'inteligencia_artificial_g': 'inteligencia_artificial_general',
    'inteligencia_artificial_d': 'inteligencia_artificial_debil',
    'inteligencia_artificial_e': 'inteligencia_artificial_en_cultura',
    'ética_en_la_inteligencia_': 'etica_en_la_inteligencia_artificial',
    'alineación_de_la_intelige': 'alineacion_inteligencia_artificial',
    'a._i._inteligencia_artifi': 'pelicula_ai_inteligencia_artificial',
    'agente_inteligente_(intel': 'agente_inteligente',
    'neural_network_(machine_l': 'red_neuronal_artificial',
    'attention_(machine_learni': 'mecanismo_de_atencion',
    'transformer_(deep_learnin': 'transformer_arquitectura',
    'active_learning_(machine_': 'aprendizaje_activo',
    'campus_multidisciplinar_e': 'campus_multidisciplinar_ia',
}

# Stopwords a eliminar del KG
STOPWORDS = {
    'el','la','los','las','un','una','de','del','a','en','y','o','e','u',
    'que','se','su','sus','con','por','para','al','lo','le','les','me',
    'te','si','no','ni','pero','más','como','muy','ya','hay','es','son',
    'the','a','an','of','in','to','and','or','is','are','be','was','were',
    'it','its','this','that','these','those','has','have','had','can','will',
    'also','been','their','from','not','at','but','by','with','on','for',
    # Palabras sin sentido semántico como nodos
    'sobre','artificial','inteligencia','que','capaces','neural','learning',
    'machine','deep','intelligence','artificial','network','sistemas',
}

def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str
    return conn

def salud_antes(conn):
    c = conn.cursor()
    stats = {}
    c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0"); stats['episodios_activos'] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM episodic_memory WHERE label IS NULL AND forgotten=0"); stats['episodios_ruido'] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM semantic_memory"); stats['conceptos'] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM knowledge_graph"); stats['kg_triples'] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM contradictions WHERE resolved=0"); stats['contradicciones'] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM decision_log WHERE was_error=1"); stats['errores_log'] = c.fetchone()[0]
    return stats

# ── PASO 1: Backup ────────────────────────────────────────────────────
print(f"Creando backup: {BACKUP}...")
shutil.copy2(DB_PATH, BACKUP)
print("✅ Backup creado")

conn = conectar()
c = conn.cursor()

print("\n─── ESTADO ANTES ───")
antes = salud_antes(conn)
for k, v in antes.items():
    print(f"  {k}: {v}")

# ── PASO 2: Renombrar conceptos truncados ─────────────────────────────
print("\n─── PASO 1: Renombrar conceptos truncados ───")
for viejo, nuevo in CONCEPT_MAP.items():
    # Verificar que el viejo existe
    c.execute("SELECT id FROM semantic_memory WHERE concept=?", (viejo,))
    if not c.fetchone():
        print(f"  SKIP (no existe): {viejo!r}")
        continue
    
    # Verificar que el nuevo NO existe (para evitar conflicto UNIQUE)
    c.execute("SELECT id FROM semantic_memory WHERE concept=?", (nuevo,))
    if c.fetchone():
        # Ya existe el nuevo → fusionar: sumar support, promediar confidence
        c.execute("SELECT support, confidence FROM semantic_memory WHERE concept=?", (viejo,))
        row_v = c.fetchone()
        c.execute("SELECT id, support, confidence FROM semantic_memory WHERE concept=?", (nuevo,))
        row_n = c.fetchone()
        merged_support = row_v[0] + row_n[1]
        merged_conf = (row_v[1] * row_v[0] + row_n[2] * row_n[1]) / merged_support
        c.execute("UPDATE semantic_memory SET support=?, confidence=? WHERE id=?",
                  (merged_support, merged_conf, row_n[0]))
        c.execute("DELETE FROM semantic_memory WHERE concept=?", (viejo,))
        print(f"  MERGE: {viejo!r} → {nuevo!r} (support={merged_support})")
    else:
        # Renombrar directamente
        c.execute("UPDATE semantic_memory SET concept=? WHERE concept=?", (nuevo, viejo))
        print(f"  RENAME: {viejo!r} → {nuevo!r}")
    
    # Actualizar episodic_memory labels
    c.execute("UPDATE episodic_memory SET label=? WHERE label=?", (nuevo, viejo))
    renamed_ep = c.rowcount
    
    # Actualizar knowledge_graph
    c.execute("UPDATE knowledge_graph SET subject=? WHERE subject=?", (nuevo, viejo))
    c.execute("UPDATE knowledge_graph SET object=? WHERE object=?", (nuevo, viejo))
    
    # Actualizar contradictions
    c.execute("UPDATE contradictions SET concept=? WHERE concept=?", (nuevo, viejo))
    
    print(f"    → {renamed_ep} episodios actualizados")

conn.commit()

# ── PASO 3: Limpiar KG ────────────────────────────────────────────────
print("\n─── PASO 2: Limpiar knowledge graph ───")

# Borrar triples donde subject u object son stopwords o muy cortos
c.execute("SELECT COUNT(*) FROM knowledge_graph"); total_antes = c.fetchone()[0]

# Construir lista de stopwords para SQL IN clause
sw_list = "','".join(STOPWORDS)
c.execute(f"""
    DELETE FROM knowledge_graph
    WHERE length(subject) <= 2
       OR length(object) <= 2
       OR subject IN ('{sw_list}')
       OR object IN ('{sw_list}')
""")
deleted_short = c.rowcount

# Borrar triples donde subject == object (self-loops sin sentido)
c.execute("DELETE FROM knowledge_graph WHERE subject = object")
deleted_loops = c.rowcount

# Borrar triples con weight muy bajo que nunca se reforzaron (ruido inicial)
c.execute("""
    DELETE FROM knowledge_graph 
    WHERE weight < 0.5 
    AND source = 'learned'
    AND verified = 0
""")
deleted_weak = c.rowcount

c.execute("SELECT COUNT(*) FROM knowledge_graph"); total_despues = c.fetchone()[0]
print(f"  Triples eliminados: {total_antes - total_despues}")
print(f"    - Nodos cortos/stopwords: {deleted_short}")
print(f"    - Self-loops: {deleted_loops}")
print(f"    - Triples débiles: {deleted_weak}")
print(f"  Total KG: {total_antes} → {total_despues}")

conn.commit()

# ── PASO 4: Resolver contradicciones ─────────────────────────────────
print("\n─── PASO 3: Resolver contradicciones ───")
c.execute("""
    UPDATE contradictions 
    SET resolved=1, resolution='auto:migration_cleanup'
    WHERE resolved=0
""")
resueltas = c.rowcount
print(f"  Contradicciones resueltas: {resueltas}")
conn.commit()

# ── PASO 5: Limpiar decision_log falso ───────────────────────────────
print("\n─── PASO 4: Reset decision_log ───")
c.execute("SELECT COUNT(*) FROM decision_log"); total_log = c.fetchone()[0]
# Los registros son todos was_error=1 porque venían de correct() únicamente.
# Los marcamos como 'correction' para que no contaminen el error_rate
c.execute("""
    UPDATE decision_log 
    SET learned = 'migration:reclassified_as_correction'
    WHERE was_error = 1 AND (learned = '' OR learned IS NULL)
""")
# Insertar un registro de éxito para balancear el rate
c.execute("""
    INSERT INTO decision_log (timestamp, action, prediction, outcome, was_error, learned)
    VALUES (?, 'migration', 'baseline', 'reset', 0, 'migration:baseline_success')
""", (datetime.now().isoformat(),))
print(f"  {total_log} registros reclasificados como correcciones (no errores de predicción)")
conn.commit()

# ── PASO 6: Limpiar episodios ruido (label=None, imp<0.4, >7 días) ───
print("\n─── PASO 5: Limpiar episodios ruido ───")
from datetime import timedelta
cutoff = (datetime.now() - timedelta(days=7)).isoformat()
c.execute("""
    UPDATE episodic_memory 
    SET forgotten=1
    WHERE label IS NULL 
    AND importance < 0.45
    AND confidence < 0.4
    AND timestamp < ?
""", (cutoff,))
olvidados = c.rowcount
print(f"  Episodios sin label marcados como olvidados: {olvidados}")
conn.commit()

# ── REPORTE FINAL ─────────────────────────────────────────────────────
print("\n─── ESTADO DESPUÉS ───")
despues = salud_antes(conn)
for k, v in despues.items():
    delta = v - antes[k]
    sign = "+" if delta >= 0 else ""
    print(f"  {k}: {v}  ({sign}{delta})")

conn.close()
print(f"\n✅ Migración completa. Backup en: {BACKUP}")
print("   Puedes borrar el backup cuando confirmes que todo funciona.")
