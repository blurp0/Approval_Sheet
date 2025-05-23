import sqlite3

DB_FILE = "pdfs.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS pdf_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_file TEXT,
        pdf_file TEXT,
        repo_name TEXT,
        commit_hash TEXT,
        created_at TEXT
    )
    ''')
    conn.commit()
    conn.close()
    print("✅ Table 'pdf_files' initialized.")