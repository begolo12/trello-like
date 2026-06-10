import subprocess, sys, os

env = os.environ.copy()
env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'

deps = ['fastapi', 'uvicorn', 'pg8000']
for dep in deps:
    r = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet', dep],
        capture_output=True, text=True, timeout=120, env=env
    )
    ok = 'Successfully installed' in r.stdout or 'already satisfied' in r.stdout
    print(f'{dep}: {"OK" if ok else "FAIL"}')
