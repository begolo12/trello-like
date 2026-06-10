"""FastAPI Backend for Trello-like — Vercel serverless."""

import os
import asyncpg
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel

DB_DSN = (
    os.environ.get("POSTGRES_URL_NON_POOLING")
    or os.environ.get("DATABASE_URL")
    or os.environ.get("POSTGRES_URL")
    or "postgresql://postgres:***@localhost:5432/trello_like"
)

# asyncpg doesn't support sslmode/sslmode query params; strip them
import re
DB_DSN_CLEAN = re.sub(r"(\?.*)", "", DB_DSN)


pool: asyncpg.Pool = None
db_ready: bool = False


# ── Pydantic schemas ──────────────────────────────────────────────

class BoardCreate(BaseModel):
    title: str = "Untitled Board"

class ColumnCreate(BaseModel):
    board_id: int
    title: str
    position: int = 0

class ColumnUpdate(BaseModel):
    title: Optional[str] = None
    position: Optional[int] = None

class CardCreate(BaseModel):
    column_id: int
    title: str
    description: str = ""
    due_date: Optional[date] = None
    position: Optional[int] = None

class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None

class CardMove(BaseModel):
    column_id: int
    position: int

class CardReorder(BaseModel):
    """Reorder card within same column — position only."""
    position: int

class CardArchive(BaseModel):
    archived: bool = True

class LabelCreate(BaseModel):
    name: str
    color: str = "#3b82f6"

class LabelUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

class CardAssigneeUpdate(BaseModel):
    assignee: str


# ── DB helpers ────────────────────────────────────────────────────

async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DB_DSN_CLEAN, min_size=1, max_size=3, ssl="require")
    return pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, db_ready
    try:
        pool = await asyncpg.create_pool(DB_DSN_CLEAN, min_size=1, max_size=3, ssl="require")
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        await seed_default()
        db_ready = True
    except Exception as e:
        print(f"[DB] Cannot connect: {e}")
        print(f"[DB] DSN prefix match: {DB_DSN[:25]}...")
        db_ready = False
    yield
    if pool:
        await pool.close()
        pool = None


app = FastAPI(title="Trello Like", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def seed_default():
    """Create tables if not exist, then seed demo board."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS boards (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL DEFAULT 'Untitled Board',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS columns (
                id SERIAL PRIMARY KEY,
                board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                column_id INTEGER NOT NULL REFERENCES columns(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                description TEXT DEFAULT '',
                due_date DATE,
                position INTEGER NOT NULL DEFAULT 0,
                archived BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS labels (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                color VARCHAR(7) NOT NULL DEFAULT '#3b82f6',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS card_labels (
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
                PRIMARY KEY (card_id, label_id)
            );
            CREATE TABLE IF NOT EXISTS card_assignees (
                id SERIAL PRIMARY KEY,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                assignee VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (card_id, assignee)
            )
        """)
        cnt = await conn.fetchval("SELECT count(*) FROM boards")
        if cnt == 0:
            bid = await conn.fetchval(
                "INSERT INTO boards(title) VALUES ($1) RETURNING id",
                "Sprint Board",
            )
            cids = await conn.fetch(
                """INSERT INTO columns(board_id, title, position)
                   VALUES ($1, 'Backlog', 1), ($1, 'In Progress', 2), ($1, 'Done', 3)
                   RETURNING id""",
                bid,
            )
            await conn.execute(
                """INSERT INTO cards(column_id, title, description, position)
                   VALUES ($1, 'Set up project repo', 'Initialize git + dependencies', 1),
                          ($1, 'Design DB schema', 'Boards, columns, cards tables', 2),
                          ($2, 'Build API endpoints', 'FastAPI CRUD for all entities', 1),
                          ($2, 'Implement drag & drop', 'Move cards between columns', 2),
                          ($3, 'Deploy to staging', 'Verify everything works', 1)""",
                cids[0]["id"], cids[1]["id"], cids[2]["id"],
            )


# ── Helper: enrich card row with labels and assignees ───────────────

CARD_SELECT = """SELECT id, column_id, title, description, position,
                        archived, due_date::text AS due_date,
                        created_at, updated_at
                 FROM cards"""

async def enrich_card(conn, row: dict) -> dict:
    """Fetch labels and assignees for a card row."""
    labels = await conn.fetch(
        """SELECT l.id, l.name, l.color
           FROM labels l
           JOIN card_labels cl ON cl.label_id = l.id
           WHERE cl.card_id = $1
           ORDER BY l.name""",
        row["id"],
    )
    assignees = await conn.fetch(
        "SELECT id, assignee, created_at FROM card_assignees WHERE card_id = $1 ORDER BY id",
        row["id"],
    )
    return {
        **row,
        "labels": [dict(lb) for lb in labels],
        "assignees": [dict(a) for a in assignees],
    }


# ── Board endpoints ───────────────────────────────────────────────

@app.get("/api/boards")
async def list_boards():
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, created_at, updated_at FROM boards ORDER BY id"
        )
        return [dict(r) for r in rows]


@app.post("/api/boards", status_code=201)
async def create_board(data: BoardCreate):
    async with pool.acquire() as conn:
        bid = await conn.fetchval(
            "INSERT INTO boards(title) VALUES ($1) RETURNING id", data.title
        )
        await conn.execute(
            """INSERT INTO columns(board_id, title, position)
               VALUES ($1, 'To Do', 1), ($1, 'In Progress', 2), ($1, 'Done', 3)""",
            bid,
        )
        row = await conn.fetchrow("SELECT * FROM boards WHERE id=$1", bid)
        return dict(row)


@app.put("/api/boards/{board_id}")
async def rename_board(board_id: int, data: BoardCreate):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE boards SET title=$1, updated_at=CURRENT_TIMESTAMP WHERE id=$2 RETURNING id, title, created_at, updated_at",
            data.title, board_id,
        )
        if not row:
            raise HTTPException(404, "Board not found")
        return dict(row)


@app.delete("/api/boards/{board_id}", status_code=204)
async def delete_board(board_id: int):
    async with pool.acquire() as conn:
        r = await conn.execute("DELETE FROM boards WHERE id=$1", board_id)
        if r == "DELETE 0":
            raise HTTPException(404, "Board not found")


# ── Column endpoints ──────────────────────────────────────────────

@app.get("/api/boards/{board_id}/columns")
async def list_columns(board_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.id, c.board_id, c.title, c.position, c.created_at
               FROM columns c WHERE c.board_id = $1 ORDER BY c.position, c.id""",
            board_id,
        )
        result = []
        for r in rows:
            cards = await conn.fetch(
                f"""{CARD_SELECT}
                   WHERE column_id = $1
                   ORDER BY position, id""",
                r["id"],
            )
            enriched = [await enrich_card(conn, dict(c)) for c in cards]
            result.append({**dict(r), "cards": enriched})
        return result


@app.post("/api/columns", status_code=201)
async def create_column(data: ColumnCreate):
    async with pool.acquire() as conn:
        cid = await conn.fetchval(
            "INSERT INTO columns(board_id, title, position) VALUES ($1, $2, $3) RETURNING id",
            data.board_id, data.title, data.position,
        )
        row = await conn.fetchrow("SELECT * FROM columns WHERE id=$1", cid)
        return {**dict(row), "cards": []}


@app.put("/api/columns/{column_id}")
async def update_column(column_id: int, data: ColumnUpdate):
    async with pool.acquire() as conn:
        if data.title is not None:
            await conn.execute("UPDATE columns SET title=$1 WHERE id=$2", data.title, column_id)
        if data.position is not None:
            await conn.execute("UPDATE columns SET position=$1 WHERE id=$2", data.position, column_id)
        row = await conn.fetchrow("SELECT * FROM columns WHERE id=$1", column_id)
        if not row:
            raise HTTPException(404, "Column not found")
        return dict(row)


@app.delete("/api/columns/{column_id}", status_code=204)
async def delete_column(column_id: int):
    async with pool.acquire() as conn:
        r = await conn.execute("DELETE FROM columns WHERE id=$1", column_id)
        if r == "DELETE 0":
            raise HTTPException(404, "Column not found")


# ── Card endpoints ────────────────────────────────────────────────

@app.get("/api/columns/{column_id}/cards")
async def list_cards(column_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""{CARD_SELECT}
               WHERE column_id = $1 ORDER BY position, id""",
            column_id,
        )
        return [await enrich_card(conn, dict(r)) for r in rows]


@app.post("/api/cards", status_code=201)
async def create_card(data: CardCreate):
    async with pool.acquire() as conn:
        pos = data.position
        if pos is None:
            pos = await conn.fetchval(
                "SELECT COALESCE(max(position), 0) + 1 FROM cards WHERE column_id=$1",
                data.column_id,
            )
        cid = await conn.fetchval(
            """INSERT INTO cards(column_id, title, description, position, due_date)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            data.column_id, data.title, data.description, pos, data.due_date,
        )
        row = await conn.fetchrow(
            f"{CARD_SELECT} WHERE id=$1",
            cid,
        )
        return await enrich_card(conn, dict(row))


@app.put("/api/cards/{card_id}")
async def update_card(card_id: int, data: CardUpdate):
    async with pool.acquire() as conn:
        sets = []
        args = []
        i = 1
        if data.title is not None:
            sets.append(f"title = ${i}")
            args.append(data.title)
            i += 1
        if data.description is not None:
            sets.append(f"description = ${i}")
            args.append(data.description)
            i += 1
        if data.due_date is not None:
            sets.append(f"due_date = ${i}")
            args.append(data.due_date)
            i += 1
        if sets:
            args.append(card_id)
            await conn.execute(
                f"UPDATE cards SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ${i}",
                *args,
            )
        row = await conn.fetchrow(
            f"{CARD_SELECT} WHERE id=$1",
            card_id,
        )
        if not row:
            raise HTTPException(404, "Card not found")
        return await enrich_card(conn, dict(row))


@app.put("/api/cards/{card_id}/move")
async def move_card(card_id: int, data: CardMove):
    """Move card to a different column at a specific position."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, column_id, position FROM cards WHERE id=$1 FOR UPDATE", card_id
            )
            if not row:
                raise HTTPException(404, "Card not found")

            old_column_id = row["column_id"]
            old_pos = row["position"]
            new_column_id = data.column_id
            new_pos = data.position

            if old_column_id != new_column_id:
                await conn.execute(
                    "UPDATE cards SET position = position - 1 WHERE column_id = $1 AND position > $2",
                    old_column_id, old_pos,
                )
                await conn.execute(
                    "UPDATE cards SET position = position + 1 WHERE column_id = $1 AND position >= $2",
                    new_column_id, new_pos,
                )
            else:
                if new_pos > old_pos:
                    await conn.execute(
                        "UPDATE cards SET position = position - 1 WHERE column_id = $1 AND position > $2 AND position <= $3",
                        old_column_id, old_pos, new_pos,
                    )
                elif new_pos < old_pos:
                    await conn.execute(
                        "UPDATE cards SET position = position + 1 WHERE column_id = $1 AND position >= $2 AND position < $3",
                        old_column_id, new_pos, old_pos,
                    )

            await conn.execute(
                "UPDATE cards SET column_id = $1, position = $2, updated_at = CURRENT_TIMESTAMP WHERE id = $3",
                new_column_id, new_pos, card_id,
            )

        row = await conn.fetchrow(
            f"{CARD_SELECT} WHERE id=$1",
            card_id,
        )
        return await enrich_card(conn, dict(row))


@app.delete("/api/cards/{card_id}", status_code=204)
async def delete_card(card_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT column_id, position FROM cards WHERE id=$1", card_id)
        if not row:
            raise HTTPException(404, "Card not found")
        async with conn.transaction():
            await conn.execute("DELETE FROM cards WHERE id=$1", card_id)
            await conn.execute(
                "UPDATE cards SET position = position - 1 WHERE column_id = $1 AND position > $2",
                row["column_id"], row["position"],
            )


# ── Card archive ──────────────────────────────────────────────────

@app.put("/api/cards/{card_id}/archive")
async def archive_card(card_id: int, data: CardArchive):
    """Archive or unarchive a card."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE cards SET archived = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2 RETURNING id",
            data.archived, card_id,
        )
        if not row:
            raise HTTPException(404, "Card not found")
        row = await conn.fetchrow(f"{CARD_SELECT} WHERE id=$1", card_id)
        return await enrich_card(conn, dict(row))


# ── Card reorder within same column ───────────────────────────────

@app.put("/api/cards/{card_id}/reorder")
async def reorder_card(card_id: int, data: CardReorder):
    """Reorder card within same column by setting new position."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, column_id, position FROM cards WHERE id=$1 FOR UPDATE", card_id
            )
            if not row:
                raise HTTPException(404, "Card not found")

            column_id = row["column_id"]
            old_pos = row["position"]
            new_pos = data.position

            if new_pos == old_pos:
                row = await conn.fetchrow(f"{CARD_SELECT} WHERE id=$1", card_id)
                return await enrich_card(conn, dict(row))

            if new_pos > old_pos:
                await conn.execute(
                    "UPDATE cards SET position = position - 1 WHERE column_id = $1 AND position > $2 AND position <= $3",
                    column_id, old_pos, new_pos,
                )
            else:
                await conn.execute(
                    "UPDATE cards SET position = position + 1 WHERE column_id = $1 AND position >= $2 AND position < $3",
                    column_id, new_pos, old_pos,
                )

            await conn.execute(
                "UPDATE cards SET position = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                new_pos, card_id,
            )

        row = await conn.fetchrow(f"{CARD_SELECT} WHERE id=$1", card_id)
        return await enrich_card(conn, dict(row))


# ── Label endpoints ───────────────────────────────────────────────

@app.get("/api/labels")
async def list_labels():
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, color, created_at FROM labels ORDER BY name"
        )
        return [dict(r) for r in rows]


@app.post("/api/labels", status_code=201)
async def create_label(data: LabelCreate):
    async with pool.acquire() as conn:
        lid = await conn.fetchval(
            "INSERT INTO labels(name, color) VALUES ($1, $2) RETURNING id",
            data.name, data.color,
        )
        row = await conn.fetchrow("SELECT id, name, color, created_at FROM labels WHERE id=$1", lid)
        return dict(row)


@app.put("/api/labels/{label_id}")
async def update_label(label_id: int, data: LabelUpdate):
    async with pool.acquire() as conn:
        sets = []
        args = []
        i = 1
        if data.name is not None:
            sets.append(f"name = ${i}")
            args.append(data.name)
            i += 1
        if data.color is not None:
            sets.append(f"color = ${i}")
            args.append(data.color)
            i += 1
        if sets:
            args.append(label_id)
            await conn.execute(
                f"UPDATE labels SET {', '.join(sets)} WHERE id = ${i}",
                *args,
            )
        row = await conn.fetchrow("SELECT id, name, color, created_at FROM labels WHERE id=$1", label_id)
        if not row:
            raise HTTPException(404, "Label not found")
        return dict(row)


@app.delete("/api/labels/{label_id}", status_code=204)
async def delete_label(label_id: int):
    async with pool.acquire() as conn:
        r = await conn.execute("DELETE FROM labels WHERE id=$1", label_id)
        if r == "DELETE 0":
            raise HTTPException(404, "Label not found")


# ── Card-Label endpoints ──────────────────────────────────────────

@app.post("/api/cards/{card_id}/labels", status_code=201)
async def add_card_label(card_id: int, data: LabelCreate):
    """Add a label to a card. Creates the label first if it doesn't exist,
    or reuses an existing label with the same name."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM cards WHERE id=$1", card_id)
        if not row:
            raise HTTPException(404, "Card not found")

        existing = await conn.fetchrow("SELECT id FROM labels WHERE name=$1", data.name)
        if existing:
            label_id = existing["id"]
            if data.color:
                await conn.execute("UPDATE labels SET color=$1 WHERE id=$2", data.color, label_id)
        else:
            label_id = await conn.fetchval(
                "INSERT INTO labels(name, color) VALUES ($1, $2) RETURNING id",
                data.name, data.color,
            )

        await conn.execute(
            "INSERT INTO card_labels(card_id, label_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            card_id, label_id,
        )

        label = await conn.fetchrow(
            "SELECT id, name, color, created_at FROM labels WHERE id=$1", label_id
        )
        return dict(label)


@app.delete("/api/cards/{card_id}/labels/{label_id}", status_code=204)
async def remove_card_label(card_id: int, label_id: int):
    async with pool.acquire() as conn:
        r = await conn.execute(
            "DELETE FROM card_labels WHERE card_id=$1 AND label_id=$2",
            card_id, label_id,
        )
        if r == "DELETE 0":
            raise HTTPException(404, "Card-label association not found")


# ── Card Assignee endpoints ───────────────────────────────────────

@app.get("/api/cards/{card_id}/assignees")
async def list_card_assignees(card_id: int):
    async with pool.acquire() as conn:
        card = await conn.fetchrow("SELECT id FROM cards WHERE id=$1", card_id)
        if not card:
            raise HTTPException(404, "Card not found")
        rows = await conn.fetch(
            "SELECT id, assignee, created_at FROM card_assignees WHERE card_id = $1 ORDER BY id",
            card_id,
        )
        return [dict(r) for r in rows]


@app.post("/api/cards/{card_id}/assignees", status_code=201)
async def add_card_assignee(card_id: int, data: CardAssigneeUpdate):
    async with pool.acquire() as conn:
        card = await conn.fetchrow("SELECT id FROM cards WHERE id=$1", card_id)
        if not card:
            raise HTTPException(404, "Card not found")
        aid = await conn.fetchval(
            "INSERT INTO card_assignees(card_id, assignee) VALUES ($1, $2) ON CONFLICT (card_id, assignee) DO UPDATE SET assignee=EXCLUDED.assignee RETURNING id",
            card_id, data.assignee,
        )
        row = await conn.fetchrow(
            "SELECT id, assignee, created_at FROM card_assignees WHERE id=$1", aid
        )
        return dict(row)


@app.delete("/api/cards/{card_id}/assignees/{assignee_id}", status_code=204)
async def remove_card_assignee(card_id: int, assignee_id: int):
    async with pool.acquire() as conn:
        r = await conn.execute(
            "DELETE FROM card_assignees WHERE id=$1 AND card_id=$2",
            assignee_id, card_id,
        )
        if r == "DELETE 0":
            raise HTTPException(404, "Assignee not found")


# ── Search endpoint ───────────────────────────────────────────────

@app.get("/api/search")
async def search_cards(q: str = Query("", min_length=0)):
    """Search cards by title or description. Returns enriched cards."""
    if not q.strip():
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""{CARD_SELECT}
               WHERE title ILIKE $1 OR description ILIKE $1
               ORDER BY position, id""",
            f"%{q}%",
        )
        return [await enrich_card(conn, dict(r)) for r in rows]


# ── Health check ──────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    masked = DB_DSN.replace(DB_DSN.split(":")[2].split("@")[0], "***") if "@" in DB_DSN else DB_DSN
    used_var = "POSTGRES_URL_NON_POOLING" if os.environ.get("POSTGRES_URL_NON_POOLING") else \
               "DATABASE_URL" if os.environ.get("DATABASE_URL") else \
               "POSTGRES_URL" if os.environ.get("POSTGRES_URL") else "fallback"
    return {"status": "ok", "db": db_ready, "db_source": masked[:40] + "...", "env_var": used_var}


@app.get("/api/db-test")
async def db_test():
    """Try to connect and return detailed error."""
    import traceback
    try:
        c = await asyncpg.connect(DB_DSN_CLEAN, ssl="require")
        v = await c.fetchval("SELECT 1")
        await c.close()
        return {"ok": True, "result": v}
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()[:500]}


# ── Serve frontend ────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    html_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.exists(html_path):
        from fastapi.responses import HTMLResponse
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return {"status": "no frontend", "message": "API is running. Configure DATABASE_URL for full functionality."}


# ── Vercel handler ────────────────────────────────────────────────

handler = Mangum(app)
