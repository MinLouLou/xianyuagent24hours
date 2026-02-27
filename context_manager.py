"""
对话上下文管理器

使用 SQLite 持久化存储对话历史、商品信息、议价计数。
按会话 ID（chat_id）隔离不同买家的对话，支持多账号并发使用。
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# 数据库连接辅助
# ---------------------------------------------------------------------------

@contextmanager
def _db_conn(path: str):
    """数据库连接上下文管理器，自动提交或回滚"""
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"数据库操作失败: {e}")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ChatContextManager
# ---------------------------------------------------------------------------

class ChatContextManager:
    """
    聊天上下文管理器

    职责：
        - 存储 / 检索对话消息（按 chat_id 隔离）
        - 缓存商品信息（按 item_id）
        - 统计议价轮次（按 chat_id）
    """

    # SQL 建表语句
    _DDL = [
        """
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   TEXT    NOT NULL,
            user_id   TEXT    NOT NULL,
            item_id   TEXT    NOT NULL,
            role      TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages (chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_msg_time ON messages (created_at)",
        """
        CREATE TABLE IF NOT EXISTS bargain_counts (
            chat_id    TEXT PRIMARY KEY,
            count      INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS items (
            item_id    TEXT PRIMARY KEY,
            data       TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]

    def __init__(self, max_history: int = 100, db_path: str = "data/chat_history.db"):
        self.max_history = max_history
        self.db_path = db_path
        self._ensure_db()

    # ------------------------------------------------------------------ #
    #  初始化
    # ------------------------------------------------------------------ #

    def _ensure_db(self):
        """确保数据库目录和表结构存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        with _db_conn(self.db_path) as conn:
            cursor = conn.cursor()
            for ddl in self._DDL:
                cursor.execute(ddl)
            self._migrate(cursor)

        logger.info(f"数据库初始化完成: {self.db_path}")

    @staticmethod
    def _migrate(cursor: sqlite3.Cursor):
        """向下兼容旧版数据库字段变更"""
        cursor.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in cursor.fetchall()}
        if "chat_id" not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN chat_id TEXT")
            logger.info("messages 表已添加 chat_id 字段（兼容旧数据库）")

    # ------------------------------------------------------------------ #
    #  商品信息
    # ------------------------------------------------------------------ #

    def save_item_info(self, item_id: str, item_data: dict):
        with _db_conn(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO items (item_id, data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
                """,
                (item_id, json.dumps(item_data, ensure_ascii=False), datetime.now().isoformat()),
            )
        logger.debug(f"商品信息已保存: {item_id}")

    def get_item_info(self, item_id: str) -> Optional[dict]:
        with _db_conn(self.db_path) as conn:
            row = conn.execute("SELECT data FROM items WHERE item_id = ?", (item_id,)).fetchone()
        return json.loads(row[0]) if row else None

    # ------------------------------------------------------------------ #
    #  消息历史
    # ------------------------------------------------------------------ #

    def add_message_by_chat(self, chat_id: str, user_id: str, item_id: str, role: str, content: str):
        """追加一条消息，并自动清理超出上限的旧消息"""
        now = datetime.now().isoformat()
        with _db_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (chat_id, user_id, item_id, role, content, created_at) VALUES (?,?,?,?,?,?)",
                (chat_id, user_id, item_id, role, content, now),
            )
            # 删除超出 max_history 的最旧消息
            row = conn.execute(
                "SELECT id FROM messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT 1 OFFSET ?",
                (chat_id, self.max_history),
            ).fetchone()
            if row:
                conn.execute("DELETE FROM messages WHERE chat_id = ? AND id <= ?", (chat_id, row[0]))

    def get_context_by_chat(self, chat_id: str) -> List[Dict]:
        """获取指定会话的对话历史，并附加议价次数系统消息"""
        with _db_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY created_at ASC LIMIT ?",
                (chat_id, self.max_history),
            ).fetchall()

        messages = [{"role": role, "content": content} for role, content in rows]

        count = self.get_bargain_count_by_chat(chat_id)
        if count > 0:
            messages.append({"role": "system", "content": f"议价次数：{count}"})

        return messages

    # ------------------------------------------------------------------ #
    #  议价计数
    # ------------------------------------------------------------------ #

    def increment_bargain_count_by_chat(self, chat_id: str):
        now = datetime.now().isoformat()
        with _db_conn(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO bargain_counts (chat_id, count, updated_at) VALUES (?, 1, ?)
                ON CONFLICT(chat_id) DO UPDATE SET count = count + 1, updated_at = excluded.updated_at
                """,
                (chat_id, now),
            )

    def get_bargain_count_by_chat(self, chat_id: str) -> int:
        with _db_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT count FROM bargain_counts WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return row[0] if row else 0
