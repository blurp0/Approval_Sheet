import sqlite3

conn = sqlite3.connect("pdfs.db")
c = conn.cursor()

# Create table if it doesn't exist
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
