import sqlite3

conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()

try:
    c.execute("ALTER TABLE semantic_memory ADD COLUMN associations TEXT DEFAULT '{}'")
    conn.commit()
    print('+ associations OK')
except Exception as e:
    print('Error:', e)

conn.close()
