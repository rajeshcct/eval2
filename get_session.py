import sqlite3
import glob

db_files = glob.glob('*.db') + glob.glob('db/*.db')
for f in db_files:
    print(f"--- {f} ---")
    try:
        conn = sqlite3.connect(f)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        for t in tables:
            print(f"Table: {t[0]}")
            if t[0] == 'sessions':
                print("Last session ID:")
                res = conn.execute("SELECT session_id FROM sessions ORDER BY created_at DESC LIMIT 1;").fetchone()
                print(res)
    except Exception as e:
        print(e)
