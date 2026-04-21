import sqlite3

conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()

fixes = [
    ('semantic_memory', 'emotion_avg',  'REAL DEFAULT 0.0'),
    ('semantic_memory', 'support',      'INTEGER DEFAULT 1'),
    ('semantic_memory', 'confidence',   'REAL DEFAULT 0.5'),
    ('semantic_memory', 'concept',      'TEXT'),
    ('episodic_memory', 'review_count', 'INTEGER DEFAULT 0'),
    ('episodic_memory', 'access_count', 'INTEGER DEFAULT 0'),
    ('episodic_memory', 'last_access',  'TEXT'),
    ('episodic_memory', 'importance',   'REAL DEFAULT 0.5'),
    ('episodic_memory', 'confidence',   'REAL DEFAULT 0.5'),
    ('episodic_memory', 'next_review',  'TEXT'),
    ('episodic_memory', 'emotion_score','REAL DEFAULT 0.0'),
    ('episodic_memory', 'emotion_label','TEXT DEFAULT neutral'),
    ('episodic_memory', 'surprise',     'REAL DEFAULT 0.0'),
    ('episodic_memory', 'forgotten',    'INTEGER DEFAULT 0'),
]

for tabla, col, tipo in fixes:
    try:
        c.execute(f'ALTER TABLE {tabla} ADD COLUMN {col} {tipo}')
        print(f'+ {tabla}.{col}')
    except:
        print(f'  ok {tabla}.{col}')

conn.commit()
conn.close()
print('\nTodo listo. Ahora corre python web_app.py y NO lo reinicies hasta enviar todos los mensajes.')
