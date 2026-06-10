import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Test SQL queries work
import subprocess

ENV = os.environ.copy()
ENV['PGPASSWORD'] = 'postgres'

def psql(sql):
    r = subprocess.run(
        ['psql', '-U', 'postgres', '-h', 'localhost', '-d', 'trello_like', '-At', '-F', '\t', '-c', sql],
        capture_output=True, text=True, env=ENV, timeout=20
    )
    if r.returncode != 0:
        print("ERR:", r.stderr.strip() or r.stdout.strip())
        return ''
    return r.stdout

print("seed boards:", psql("INSERT INTO boards(title) VALUES ('Sprint Board') RETURNING id;").strip())
print("seed columns:", psql("INSERT INTO columns(board_id,title,position) VALUES (1,'Backlog',1),(1,'Doing',2),(1,'Done',3);").strip())
print("seed cards:", psql("INSERT INTO cards(column_id,title,description,position) VALUES (1,'Set up project','Base app local-first',1),(1,'Design schema','Boards, columns, cards',2);").strip())

print("\nboards:")
print(psql("SELECT * FROM boards;"))
print("columns:")
print(psql("SELECT * FROM columns;"))
print("cards:")
print(psql("SELECT * FROM cards;"))
