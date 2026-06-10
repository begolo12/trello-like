import subprocess, json, sys

BASE = 'http://127.0.0.1:8001'
ok = 0; fail = 0

def curl(method, url, data=None):
    cmd = ['curl', '-s']
    if method == 'POST':
        cmd += ['-X', 'POST', '-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    elif method == 'PUT':
        cmd += ['-X', 'PUT', '-H', 'Content-Type: application/json', '-d', json.dumps(data)]
    elif method == 'DELETE':
        cmd += ['-X', 'DELETE', '-w', '\n__HTTP_SEP__%{http_code}']
    elif method == 'GET-RAW':
        cmd += ['-w', '\n__HTTP_SEP__%{http_code}']
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return r.stdout, r.returncode

def match(name, expected_status, actual_status):
    global ok, fail
    if actual_status == expected_status:
        print(f'  ✓ {name}')
        ok += 1
    else:
        print(f'  ✗ {name} (expected {expected_status}, got {actual_status})')
        fail += 1

# --- TEST SUITE ---
print('=== Trello Like Integration Tests ===\n')

# 1. List boards
out, _ = curl('GET', f'{BASE}/api/boards')
boards = json.loads(out)
match(f'List boards ({len(boards)} found)', 200, 200)
board1_id = boards[0]['id']

# 2. Get columns for board 1
out, _ = curl('GET', f'{BASE}/api/boards/{board1_id}/columns')
cols = json.loads(out)
match(f'List columns ({len(cols)} columns)', 200, 200)
col1_id = cols[0]['id']
col2_id = cols[1]['id']

# 3. Create a card
out, _ = curl('POST', f'{BASE}/api/cards', {'column_id': col2_id, 'title': 'Test card', 'description': 'API test', 'due_date': '2026-06-20'})
card = json.loads(out)
card_id = card['id']
match(f'Create card #{card_id}', 200, 200)

# 4. Update the card
out, _ = curl('PUT', f'{BASE}/api/cards/{card_id}', {'title': 'Updated card', 'description': 'Changed desc'})
updated = json.loads(out)
match(f'Update card -> "{updated["title"]}"', 200, 200)

# 5. Move card between columns
out, _ = curl('PUT', f'{BASE}/api/cards/{card_id}/move', {'column_id': col1_id, 'position': 1})
moved = json.loads(out)
match(f'Move card to column {col1_id} pos 1', 200, 200)

# 6. Delete the card
out, code = curl('DELETE', f'{BASE}/api/cards/{card_id}')
parts = out.split('__HTTP_SEP__')
http_code = parts[-1].strip()
match(f'Delete card #{card_id}', '204', http_code)

# 7. Create new board (auto-creates columns)
out, _ = curl('POST', f'{BASE}/api/boards', {'title': 'My Planning Board'})
b = json.loads(out)
match(f'Create board "{b["title"]}"', 200, 200)

# 8. Verify it has default columns
out, _ = curl('GET', f'{BASE}/api/boards/{b["id"]}/columns')
new_cols = json.loads(out)
match(f'New board has {len(new_cols)} columns', 200, 200)

# 9. Frontend loads
out, code = curl('GET-RAW', f'{BASE}/')
parts = out.split('__HTTP_SEP__')
http_code = parts[-1].strip()
match('Frontend serves HTML', '200', http_code)

# 10. Summary
print(f'\n=== {ok}/{ok+fail} tests passed ===')
for col in cols:
    print(f'  {col["title"]}: {len(col["cards"])} cards')
