import subprocess, os

os.environ['PGPASSWORD'] = 'postgres'

r = subprocess.run(
    ["psql", "-U", "postgres", "-h", "localhost", "-tc", 
     "SELECT 1 FROM pg_database WHERE datname='trello_like';"],
    capture_output=True, text=True, timeout=10
)
exists = r.stdout.strip() == '1'
if not exists:
    r2 = subprocess.run(
        ["psql", "-U", "postgres", "-h", "localhost", "-c", "CREATE DATABASE trello_like;"],
        capture_output=True, text=True, timeout=10
    )
    print("create db:", r2.stdout.strip(), r2.stderr.strip())
else:
    print("db exists")

r3 = subprocess.run(
    ["psql", "-U", "postgres", "-h", "localhost", "-d", "trello_like", "-f", "setup.sql"],
    capture_output=True, text=True, timeout=10
)
print("schema:", r3.stdout.strip() or r3.stderr.strip())
