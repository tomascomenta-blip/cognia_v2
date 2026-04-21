import sqlite3
conn = sqlite3.connect('cognia_memory.db')
c = conn.cursor()
c.execute('INSERT INTO episodic_memory (timestamp,observation,label,vector,confidence,last_access,importance,emotion_score,emotion_label,surprise,review_count,next_review,context_tags) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)', ('2026-01-01','test obs','test_label','[]',0.5,'2026-01-01',1.0,0.0,'neutral',0.0,'2026-02-01','[]'))
conn.commit()
count = c.execute('SELECT COUNT(*) FROM episodic_memory').fetchone()[0]
print('Filas:', count)
conn.close()
