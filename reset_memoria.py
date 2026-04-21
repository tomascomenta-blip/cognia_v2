import sqlite3

conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()

antes_ep = c.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
antes_sem = c.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]

c.execute("DELETE FROM episodic_memory")
c.execute("DELETE FROM semantic_memory")
c.execute("DELETE FROM knowledge_graph")
c.execute("DELETE FROM temporal_sequences")
c.execute("DELETE FROM goal_system")
c.execute("DELETE FROM contradictions")
c.execute("DELETE FROM sleep_log")
c.execute("DELETE FROM inference_rules")

conn.commit()
conn.close()

print(f'Limpieza completa.')
print(f'Episodios borrados: {antes_ep}')
print(f'Conceptos borrados: {antes_sem}')
print('Cognia lista para empezar desde cero.')
