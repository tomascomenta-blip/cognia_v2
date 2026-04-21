import sqlite3
conn = sqlite3.connect("cognia_memory.db")
c = conn.cursor()
try:
    c.execute("ALTER TABLE episodic_memory ADD COLUMN context_tags TEXT DEFAULT \"[]\")"
    conn.commit()
    print("+ context_tags agregada OK")
except Exception as e:
    print("Error:", e)
cols = [r[1] for r in c.execute("PRAGMA table_info(episodic_memory)").fetchall()]
print("Columnas finales:", cols)
conn.close()
