import sqlite3
conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()

print('=== TABLAS ===')
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print(c.fetchall())

print('\n=== CONTEOS ===')
for tabla in ['episodic_memory', 'semantic_memory', 'response_cache']:
    try:
        c.execute('SELECT COUNT(*) FROM ' + tabla)
        print(tabla + ': ' + str(c.fetchone()[0]) + ' filas')
    except Exception as e:
        print(tabla + ': ERROR - ' + str(e))

print('\n=== MUESTRA EPISODIC (top 10 por importancia) ===')
c.execute('SELECT label, observation, confidence, importance, forgotten FROM episodic_memory ORDER BY importance DESC LIMIT 10')
for r in c.fetchall():
    print(str(r[0]) + ' | ' + str(r[1])[:80] + ' | conf=' + str(r[2]) + ' imp=' + str(r[3]) + ' forg=' + str(r[4]))

print('\n=== SEMANTIC MEMORY (todos) ===')
c.execute('SELECT concept, confidence, support FROM semantic_memory ORDER BY confidence DESC')
for r in c.fetchall():
    print(r)

conn.close()
