import sys, os, sqlite3, json, traceback
os.chdir(r"C:\Users\Tomanquito\Downloads\cognia\cognia_v2")
sys.path.insert(0, os.getcwd())
print("=== TEST 1: INSERT directo ===")
try:
    conn = sqlite3.connect("cognia_memory.db")
    c = conn.cursor()
    c.execute("INSERT INTO episodic_memory (timestamp,observation,label,vector,confidence,last_access,importance,emotion_score,emotion_label,surprise,review_count,next_review,context_tags) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)", ("2026-01-01","test obs","test_lbl",json.dumps([0.1]*17),0.5,"2026-01-01",1.0,0.0,"neutral",0.0,"2026-02-01","[]"))
    conn.commit()
    print("INSERT OK filas=", c.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0])
    conn.close()
except Exception as e:
    print("ERROR:", e); traceback.print_exc()
print()
print("=== TEST 2: cognia_v3 EpisodicMemory ===")
try:
    from cognia_v3 import EpisodicMemory, DB_PATH
    print("DB_PATH=", DB_PATH)
    print("existe=", os.path.exists(DB_PATH))
    em = EpisodicMemory(DB_PATH)
    eid = em.store("prueba directa","test",[0.1]*17,0.5,1.0,{"score":0.0,"label":"neutral","intensity":0.0},0.0,[])
    print("store() eid=", eid)
    conn2 = sqlite3.connect(DB_PATH)
    print("filas post-store=", conn2.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0])
    conn2.close()
except Exception as e:
    print("ERROR:", e); traceback.print_exc()
