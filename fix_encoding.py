import sqlite3

conn = sqlite3.connect('cognia_memory.db')

# Ver episodios corruptos
c = conn.execute("SELECT id, label, observation FROM episodic_memory WHERE label='voleibol'")
rows = c.fetchall()
print(f"Episodios con label=voleibol: {len(rows)}")
for r in rows:
    print(f"  ID {r[0]}: {r[2][:80]}")

# Borrar los corruptos
conn.execute("DELETE FROM episodic_memory WHERE label='voleibol'")
conn.commit()
print("Borrados. Ahora vuelve a preguntar 'que es el voleibol' en el chat.")
print("El investigador lo buscara de nuevo y lo guardara correctamente.")
conn.close()
