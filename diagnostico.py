import sqlite3

conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()

tablas = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('=== TABLAS ===')
print(tablas)

for t in tablas:
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})').fetchall()]
    count = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'\n--- {t} ({count} filas) ---')
    print('Columnas:', cols)
    if count > 0 and t in ('episodic_memory', 'semantic_memory'):
        rows = c.execute(f'SELECT * FROM {t} LIMIT 2').fetchall()
        for r in rows:
            print(' >>', r)

conn.close()
