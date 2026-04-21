import sqlite3
conn = sqlite3.connect('cognia_memory.db')
c = conn.execute("SELECT id, label, observation FROM episodic_memory WHERE label LIKE '%volleyball%' OR label LIKE '%realsports%'")
for row in c.fetchall():
    print(row[0], row[1], row[2][:50])
conn.execute("DELETE FROM episodic_memory WHERE label LIKE '%volleyball%' OR label LIKE '%realsports%'")
conn.commit()
print('Listo')
conn.close()