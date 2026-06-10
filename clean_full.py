import subprocess, os
ENV = os.environ.copy()
ENV['PGPASSWORD'] = 'postgres'

cmds = [
    "DELETE FROM cards;",
    "DELETE FROM columns;",
    "DELETE FROM boards;",
    "ALTER SEQUENCE boards_id_seq RESTART WITH 1;",
    "ALTER SEQUENCE columns_id_seq RESTART WITH 1;",
    "ALTER SEQUENCE cards_id_seq RESTART WITH 1;",
]
for c in cmds:
    r = subprocess.run(['psql','-U','postgres','-h','localhost','-d','trello_like','-c',c], capture_output=True, text=True, env=ENV, timeout=10)
    print(r.stdout.strip() or r.stderr.strip())
