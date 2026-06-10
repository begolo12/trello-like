import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HOST = os.environ.get('HOST', '127.0.0.1')
PORT = int(os.environ.get('PORT', '8000'))
DBNAME = os.environ.get('DBNAME', 'trello_like')
DBUSER = os.environ.get('DBUSER', 'postgres')
DBHOST = os.environ.get('DBHOST', 'localhost')
DBPASS = os.environ.get('DBPASS', 'postgres')

ENV = os.environ.copy()
ENV['PGPASSWORD'] = DBPASS


def psql(sql):
    r = subprocess.run(
        ['psql', '-U', DBUSER, '-h', DBHOST, '-d', DBNAME, '-At', '-F', '\t', '-c', sql],
        capture_output=True, text=True, env=ENV, timeout=20
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def query_json(sql):
    out = psql(sql).strip()
    if not out:
        return []
    lines = [line.split('\t') for line in out.splitlines()]
    return lines


def seed():
    cnt = psql("SELECT count(*) FROM boards;").strip().splitlines()[-1].strip()
    if cnt == '0':
        out = psql("INSERT INTO boards(title) VALUES ('Sprint Board') RETURNING id;").strip()
        bid = out.splitlines()[-1].strip()
        psql(f"INSERT INTO columns(board_id,title,position) VALUES ({bid},'Backlog',1),({bid},'Doing',2),({bid},'Done',3);")
        cols = psql(f"SELECT id FROM columns WHERE board_id={bid} ORDER BY position;").strip().splitlines()
        cid0 = cols[-1].strip() if len(cols) == 1 else cols[0].strip()
        psql(f"INSERT INTO cards(column_id,title,description,position) VALUES ({cid0},'Set up project','Base app local-first',1),({cid0},'Design schema','Boards, columns, cards',2);")


HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Trello Like</title><style>
body{font-family:Inter,system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0}
header{padding:16px 20px;background:#111827;position:sticky;top:0;border-bottom:1px solid #334155}
.container{padding:20px;overflow-x:auto}
.board{display:flex;gap:14px;min-height:calc(100vh - 80px)}
.column{background:#1e293b;border-radius:14px;width:320px;flex:0 0 320px;padding:12px;box-shadow:0 10px 30px rgba(0,0,0,.2)}
.column h2{font-size:16px;margin:4px 0 12px}
.card{background:#334155;border-radius:12px;padding:12px;margin-bottom:10px;cursor:grab}
small{color:#94a3b8}
input,textarea,button{width:100%;box-sizing:border-box;border:1px solid #475569;background:#0f172a;color:#e2e8f0;border-radius:10px;padding:10px;margin:6px 0}
button{background:#2563eb;border:none;font-weight:700;cursor:pointer}
.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.modal{margin-top:12px;border-top:1px solid #334155;padding-top:10px}
</style></head><body><header><strong>Trello Like</strong> <small>local PostgreSQL scheduling board</small></header><div class="container"><div id="app">Loading...</div></div><script>
async function api(url, opts={}){ const r=await fetch(url, {headers:{'Content-Type':'application/json'}, ...opts}); return r.json(); }
function cardHTML(c){ return `<div class='card'><b>${escapeHtml(c.title)}</b><div><small>${escapeHtml(c.description||'')}</small></div><div><small>#${c.id}${c.due_date?(' • due '+c.due_date):''}</small></div></div>`; }
function escapeHtml(s){ return String(s||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
async function load(){ const data=await api('/api/board'); const app=document.getElementById('app'); app.innerHTML=''; data.forEach(col=>{ const el=document.createElement('div'); el.className='column'; el.innerHTML=`<h2>${escapeHtml(col.title)}</h2><small>${col.cards.length} cards</small><div>${col.cards.map(cardHTML).join('')}</div><div class='modal'><input id='t${col.id}' placeholder='Card title'><textarea id='d${col.id}' placeholder='Description'></textarea><button onclick='addCard(${col.id})'>Add card</button></div>`; app.appendChild(el); }); }
async function addCard(cid){ const title=document.getElementById('t'+cid).value; const description=document.getElementById('d'+cid).value; await api('/api/cards',{method:'POST',body:JSON.stringify({column_id:cid,title,description})}); load(); }
load();
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ct='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ct)
        self.end_headers()
        if isinstance(body, str): body = body.encode()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/':
            self._send(200, HTML, 'text/html; charset=utf-8')
        elif parsed.path == '/api/board':
            rows = query_json("""
                SELECT c.id, c.title,
                  COALESCE((SELECT json_agg(json_build_object('id',ca.id,'title',ca.title,'description',ca.description,'position',ca.position,'due_date',ca.due_date) ORDER BY ca.position, ca.id)
                           FROM cards ca WHERE ca.column_id = c.id), '[]'::json)
                FROM columns c
                ORDER BY c.position, c.id;
            """)
            data = []
            for rid, title, cards in rows:
                data.append({'id': int(rid), 'title': title, 'cards': json.loads(cards) if cards else []})
            self._send(200, json.dumps(data))
        else:
            self._send(404, json.dumps({'error': 'not found'}))

    def do_POST(self):
        n = int(self.headers.get('Content-Length', '0'))
        body = json.loads(self.rfile.read(n) or b'{}')
        if self.path == '/api/cards':
            title = body['title'].replace("'", "''")
            description = body.get('description', '').replace("'", "''")
            column_id = int(body['column_id'])
            psql(f"INSERT INTO cards(column_id,title,description,position) VALUES ({column_id},'{title}','{description}', COALESCE((SELECT max(position)+1 FROM cards WHERE column_id={column_id}),1));")
            self._send(200, json.dumps({'ok': True}))
        else:
            self._send(404, json.dumps({'error': 'not found'}))


def main():
    seed()
    print(f'Starting on http://{HOST}:{PORT}')
    HTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == '__main__':
    main()
