# -*- coding: utf-8 -*-
"""会话记忆 —— 对应本程序的 memory 模块。

本程序 把每轮 PromptRequest/Response 写进 SQLite，供多轮攻击、事后分析、
报告导出使用。这里每次攻击一行，v2 新增 payload 列（记录所用的越狱模板）。
"""
import json
import sqlite3
import threading
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
    reason      TEXT,
    attack_model TEXT,
    attack_url   TEXT,
    target_model TEXT,
    target_url   TEXT
);
"""


class Memory:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        # Web 层会把每次请求丢到线程池执行，同一个连接可能被不同线程用到，
        # 所以关掉 sqlite3 的线程亲和检查，并用自己的锁保证串行访问。
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(_SCHEMA)
            # 兼容 v1 老库：补 payload 列
            cols = {row[1] for row in self.conn.execute("PRAGMA table_info(attacks)")}
            if "payload" not in cols:
                self.conn.execute("ALTER TABLE attacks ADD COLUMN payload TEXT")
            # 兼容老库：补模型信息列（攻击者 / 被攻击模型）
            for col in ("attack_model", "attack_url", "target_model", "target_url"):
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE attacks ADD COLUMN {col} TEXT")
            self.conn.commit()

    def save(self, record: dict) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO attacks (ts, converter, objective, payload, prompt, response, success, reason, "
                "attack_model, attack_url, target_model, target_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.get("ts") or datetime.now().isoformat(timespec="seconds"),
                    record["converter"],
                    record["objective"],
                    record.get("payload", ""),
                    record["prompt"],
                    record["response"],
                    int(record["success"]),
                    record.get("reason", ""),
                    record.get("attack_model", ""),
                    record.get("attack_url", ""),
                    record.get("target_model", ""),
                    record.get("target_url", ""),
                ),
            )
            self.conn.commit()
            return cur.lastrowid

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, ts, converter, payload, objective, success, reason, "
                "attack_model, attack_url, target_model, target_url FROM attacks "
                "ORDER BY id DESC LIMIT ?", (limit,),
            )
            return [dict(zip(("id", "ts", "converter", "payload", "objective", "success", "reason",
                              "attack_model", "attack_url", "target_model", "target_url"), row))
                    for row in cur.fetchall()]

    def all(self) -> list[dict]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, ts, converter, payload, objective, prompt, response, success, reason, "
                "attack_model, attack_url, target_model, target_url "
                "FROM attacks ORDER BY id"
            )
            keys = ("id", "ts", "converter", "payload", "objective", "prompt", "response", "success",
                    "reason", "attack_model", "attack_url", "target_model", "target_url")
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    def clear(self) -> int:
        """清空全部记录，返回删除行数。"""
        with self._lock:
            cur = self.conn.execute("DELETE FROM attacks")
            self.conn.commit()
            return cur.rowcount

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
                             "reason", "attack_model", "attack_url", "target_model", "target_url",
                             "prompt", "response"))
            for r in records:
                writer.writerow((r["id"], r["ts"], r["converter"], r["payload"], r["objective"],
                                 r["success"], r["reason"], r["attack_model"], r["attack_url"],
                                 r["target_model"], r["target_url"], r["prompt"], r["response"]))
        return len(records)

    def close(self):
        with self._lock:
            self.conn.close()
