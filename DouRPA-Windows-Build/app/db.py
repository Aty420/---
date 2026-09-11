import json
import sqlite3
from pathlib import Path
from typing import Iterable


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _columns(self, conn, table: str) -> set[str]:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    def _ensure_column(self, conn, table: str, definition: str):
        name = definition.split()[0]
        if name not in self._columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def _init_schema(self):
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS stores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    profile_dir TEXT NOT NULL UNIQUE,
                    status TEXT DEFAULT '未登录',
                    last_login DATETIME
                );

                CREATE TABLE IF NOT EXISTS source_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    store_id INTEGER,
                    search_mode TEXT DEFAULT '商品ID/关键词',
                    source_keyword TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_code TEXT UNIQUE NOT NULL,
                    template_name TEXT NOT NULL,
                    new_title TEXT NOT NULL,
                    sku_name TEXT NOT NULL,
                    cover_image TEXT NOT NULL,
                    status TEXT DEFAULT '待执行',
                    progress INTEGER DEFAULT 0,
                    current_step TEXT DEFAULT '等待',
                    attempts INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    result_text TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT,
                    message TEXT,
                    product_code TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            conn.execute(
                """CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_code TEXT UNIQUE,
                    title TEXT NOT NULL,
                    template_name TEXT,
                    category TEXT,
                    brand TEXT,
                    spec TEXT,
                    price REAL DEFAULT 0,
                    stock INTEGER DEFAULT 0,
                    image_dir TEXT,
                    status TEXT DEFAULT '待执行',
                    progress INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
            )

    # ---------- Tasks ----------
    def upsert_tasks(self, rows: Iterable[dict]):
        with self.connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO tasks(task_code,template_name,new_title,sku_name,cover_image)
                    VALUES(:task_code,:template_name,:new_title,:sku_name,:cover_image)
                    ON CONFLICT(task_code) DO UPDATE SET
                        template_name=excluded.template_name,
                        new_title=excluded.new_title,
                        sku_name=excluded.sku_name,
                        cover_image=excluded.cover_image,
                        status='待执行', progress=0, current_step='等待',
                        last_error='', result_text='', updated_at=CURRENT_TIMESTAMP
                    """,
                    row,
                )

    def tasks(self, statuses: tuple[str, ...] | None = None):
        with self.connect() as conn:
            if statuses:
                marks = ",".join("?" for _ in statuses)
                return list(conn.execute(f"SELECT * FROM tasks WHERE status IN ({marks}) ORDER BY id ASC", statuses))
            return list(conn.execute("SELECT * FROM tasks ORDER BY id DESC"))

    def task(self, task_id: int):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    def update_task(self, task_id: int, *, status=None, progress=None, step=None, error=None, result=None, inc_attempt=False):
        parts = ["updated_at=CURRENT_TIMESTAMP"]
        args = []
        if status is not None:
            parts.append("status=?"); args.append(status)
        if progress is not None:
            parts.append("progress=?"); args.append(int(progress))
        if step is not None:
            parts.append("current_step=?"); args.append(step)
        if error is not None:
            parts.append("last_error=?"); args.append(error)
        if result is not None:
            parts.append("result_text=?"); args.append(result)
        if inc_attempt:
            parts.append("attempts=attempts+1")
        args.append(task_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(parts)} WHERE id=?", args)

    def reset_failed(self):
        with self.connect() as conn:
            conn.execute("UPDATE tasks SET status='待执行',progress=0,current_step='等待',last_error='' WHERE status='失败'")

    # ---------- Stores ----------
    def add_store(self, name: str, profile_dir: str):
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO stores(name, profile_dir) VALUES(?,?)", (name, profile_dir))

    def stores(self):
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM stores ORDER BY id ASC"))

    def store(self, store_id: int):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()

    def update_store_status(self, store_id: int, status: str):
        with self.connect() as conn:
            conn.execute("UPDATE stores SET status=?,last_login=CURRENT_TIMESTAMP WHERE id=?", (status, store_id))

    def delete_store(self, store_id: int):
        """Delete only the DouRPA store record.

        Source templates are safely unbound first. Browser profile files are deliberately
        kept on disk so deleting a row cannot unexpectedly destroy login/session data.
        """
        with self.connect() as conn:
            conn.execute("UPDATE source_templates SET store_id=NULL WHERE store_id=?", (store_id,))
            conn.execute("DELETE FROM stores WHERE id=?", (store_id,))

    # ---------- Source templates ----------
    def save_template(self, name: str, store_id: int | None, search_mode: str, source_keyword: str, note: str = ""):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_templates(name,store_id,search_mode,source_keyword,note)
                VALUES(?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                  store_id=excluded.store_id, search_mode=excluded.search_mode,
                  source_keyword=excluded.source_keyword, note=excluded.note,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (name, store_id, search_mode, source_keyword, note),
            )

    def templates(self):
        with self.connect() as conn:
            return list(conn.execute(
                """SELECT t.*, s.name AS store_name
                   FROM source_templates t LEFT JOIN stores s ON s.id=t.store_id
                   ORDER BY t.id DESC"""
            ))

    def template(self, name: str):
        with self.connect() as conn:
            return conn.execute(
                """SELECT t.*, s.name AS store_name, s.profile_dir
                   FROM source_templates t LEFT JOIN stores s ON s.id=t.store_id
                   WHERE t.name=?""",
                (name,),
            ).fetchone()

    def delete_template(self, template_id: int):
        with self.connect() as conn:
            conn.execute("DELETE FROM source_templates WHERE id=?", (template_id,))

    # ---------- Logs / stats ----------
    def add_log(self, level: str, message: str, product_code: str = ""):
        with self.connect() as conn:
            conn.execute("INSERT INTO logs(level,message,product_code) VALUES(?,?,?)", (level, message, product_code))

    def logs(self, limit=500):
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)))

    def stats(self):
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='成功'").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='失败'").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('待执行','待确认','排队中')").fetchone()[0]
            running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('执行中','排队中')").fetchone()[0]
        return {"total": total, "success": success, "failed": failed, "pending": pending, "running": running}
