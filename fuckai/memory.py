# -*- coding: utf-8 -*-
"""会话记忆 —— 对应本程序的 memory 模块。

本程序 把每轮 PromptRequest/Response 写进 SQLite，供多轮攻击、事后分析、
报告导出使用。这里每次攻击一行，v2 新增 payload 列（记录所用的越狱模板）。
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attacks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    converter   TEXT NOT NULL,
    objective   TEXT NOT NULL,
    payload     TEXT,
    prompt      TEXT NOT NULL,
    response    TEXT NOT NULL,
    success     INTEGER NOT NULL,
    reason      TEXT
);
"""


class Memory:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(_SCHEMA)
        # 兼容 v1 老库：补 payload 列
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(attacks)")}
        if "payload" not in cols:
            self.conn.execute("ALTER TABLE attacks ADD COLUMN payload TEXT")
            self.conn.commit()

    def save(self, record: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO attacks (ts, converter, objective, payload, prompt, response, success, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.get("ts") or datetime.now().isoformat(timespec="seconds"),
                record["converter"],
                record["objective"],
                record.get("payload", ""),
                record["prompt"],
                record["response"],
                int(record["success"]),
                record.get("reason", ""),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def recent(self, limit: int = 20) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, ts, converter, payload, objective, success, reason FROM attacks "
            "ORDER BY id DESC LIMIT ?", (limit,),
        )
        return [dict(zip(("id", "ts", "converter", "payload", "objective", "success", "reason"), row))
                for row in cur.fetchall()]

    def all(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, ts, converter, payload, objective, prompt, response, success, reason "
            "FROM attacks ORDER BY id"
        )
        keys = ("id", "ts", "converter", "payload", "objective", "prompt", "response", "success", "reason")
        return [dict(zip(keys, row)) for row in cur.fetchall()]

    def export_json(self, path: str) -> int:
        records = self.all()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return len(records)

    def export_csv(self, path: str) -> int:
        import csv
        records = self.all()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(("id", "ts", "converter", "payload", "objective", "success",
                             "reason", "prompt", "response"))
            for r in records:
                writer.writerow((r["id"], r["ts"], r["converter"], r["payload"], r["objective"],
                                 r["success"], r["reason"], r["prompt"], r["response"]))
        return len(records)

    def close(self):
        self.conn.close()
