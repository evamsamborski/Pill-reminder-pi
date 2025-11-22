import os
import sqlite3

DB_PATH = 'pilllog.db'

#Delete db file file if it exists
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print(f"Deleted {DB_PATH}, starting fresh!")
else:
    print(f"No existing {DB_PATH}, starting fresh!")

#Reinstantiate DB files if it exists
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            frequencyPerDay INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pill_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            med_id INTEGER,
            taken_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(med_id) REFERENCES medications(id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS alarms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    print("New database initialized with all tables.")

#Run init_db function
init_db()
