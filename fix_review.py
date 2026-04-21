import sqlite3

conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()

cols_faltantes = [
    ('episodic_memory', 'review_count', 'INTEGER DEFAULT 0'),
    ('episodic_memory', 'access_count', 'INTEGER DEFAULT 0'),
    ('episodic_memory', 'last_access',  'TEXT'),
    ('episodic_memory', 'importance',   'REAL DEFAULT 0.5'),
    ('episodic_memory', 'confidence',   'REAL DEFAULT 0.5'),
]

for tabla, col, tipo in cols_faltantes:
    try:
        c.execute(f'ALTER TABLE {tabla} ADD COLUMN {col} {tipo}')
        print(f'+ {tabla}.{col}')
    except Exception as e:
        print(f'  (ya existe) {col}')

conn.commit()
conn.close()
print('Listo.')
