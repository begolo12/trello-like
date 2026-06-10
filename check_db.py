import subprocess, os
ENV = os.environ.copy()
ENV['PGPASSWORD'] = 'postgres'
for q in [
    "SELECT count(*) FROM boards;",
    "SELECT * FROM boards;",
    "SELECT * FROM columns;",
    "SELECT * FROM cards;",
]:
    r = subprocess.run(['psql','-U','postgres','-h','localhost','-d','trello_like','-At','-c', q], capture_output=True, text=True, env=ENV, timeout=10)
    print(f"{q[:40]} -> {repr(r.stdout)}")
