"""FastAPI Backend for Trello-like — Vercel serverless."""

import os
import asyncpg
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel

DB_DSN = (
    os.environ.get("POSTGRES_URL_NON_POOLING")
    or os.environ.get("DATABASE_URL")
    or os.environ.get("POSTGRES_URL")
    or "postgresql://postgres:***@localhost:5432/trello_like"
)

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


# ── DB helpers ────────────────────────────────────────────────────

async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=3)
    return pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, db_ready
    try:
        pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=3)
        if pool:
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
    """Seed demo board if none exist."""
    async with pool.acquire() as conn:
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
                """SELECT id, column_id, title, description, position,
                          due_date::text AS due_date, created_at, updated_at
                   FROM cards WHERE column_id = $1
                   ORDER BY position, id""",
                r["id"],
            )
            result.append({**dict(r), "cards": [dict(c) for c in cards]})
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
            """SELECT id, column_id, title, description, position,
                      due_date::text AS due_date, created_at, updated_at
               FROM cards WHERE column_id = $1 ORDER BY position, id""",
            column_id,
        )
        return [dict(r) for r in rows]


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
            """SELECT id, column_id, title, description, position,
                      due_date::text AS due_date, created_at, updated_at
               FROM cards WHERE id=$1""",
            cid,
        )
        return dict(row)


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
            """SELECT id, column_id, title, description, position,
                      due_date::text AS due_date, created_at, updated_at
               FROM cards WHERE id=$1""",
            card_id,
        )
        if not row:
            raise HTTPException(404, "Card not found")
        return dict(row)


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
            """SELECT id, column_id, title, description, position,
                      due_date::text AS due_date, created_at, updated_at
               FROM cards WHERE id=$1""",
            card_id,
        )
        return dict(row)


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


# ── Health check ──────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "db": db_ready, "db_source": "DATABASE_URL" if os.environ.get("DATABASE_URL") else ("POSTGRES_URL" if os.environ.get("POSTGRES_URL") else "not set")}


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
