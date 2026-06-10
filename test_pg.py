import subprocess, os

os.environ['PGPASSWORD'] = 'postgres'

# Create database
r = subprocess.run(
    ["psql", "-U", "postgres", "-h", "localhost", "-c", 
     "SELECT 1 FROM pg_database WHERE datname='trello_like';"],
    capture_output=True, text=True, timeout=10
)
if '1 row' not in r.stdout:
    r2 = subprocess.run(
        ["psql", "-U", "postgres", "-h", "localhost", "-c", "CREATE DATABASE trello_like;"],
        capture_output=True, text=True, timeout=10
    )
    print("create db:", r2.stdout, r2.stderr)
else:
    print("db already exists")

# Create schema
schema = """
CREATE TABLE IF NOT EXISTS boards (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL DEFAULT 'Untitled Board',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS columns (
    id SERIAL PRIMARY KEY,
    board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    column_id INTEGER REFERENCES columns(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    description TEXT DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    due_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_columns_board ON columns(board_id);
CREATE INDEX IF NOT EXISTS idx_cards_column ON cards(column_id);
CREATE INDEX IF NOT EXISTS idx_cards_position ON cards(position);
"""

r3 = subprocess.run(
    ["psql", "-U", "postgres", "-h", "localhost", "-d", "trello_like", "-c", schema],
    capture_output=True, text=True, timeout=10
)
print("schema:", r3.stdout, r3.stderr)
