import sqlite3

conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()

tablas = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('Tablas existentes:', tablas)

def add_col(tabla, col, tipo):
    try:
        c.execute(f'ALTER TABLE {tabla} ADD COLUMN {col} {tipo}')
        print(f'+ {tabla}.{col}')
    except Exception as e:
        print(f'  (ya existe o error) {tabla}.{col}: {e}')

add_col('episodic_memory', 'next_review', 'TEXT')
add_col('episodic_memory', 'emotion_score', 'REAL DEFAULT 0.0')
add_col('episodic_memory', 'emotion_label', 'TEXT DEFAULT neutral')
add_col('episodic_memory', 'surprise', 'REAL DEFAULT 0.0')
add_col('episodic_memory', 'forgotten', 'INTEGER DEFAULT 0')

add_col('semantic_memory', 'associations', 'TEXT DEFAULT {}')
add_col('semantic_memory', 'embedding', 'BLOB')
add_col('semantic_memory', 'frequency', 'INTEGER DEFAULT 1')
add_col('semantic_memory', 'last_updated', 'TEXT')

conn.commit()
conn.close()
print('Migracion completa OK')
