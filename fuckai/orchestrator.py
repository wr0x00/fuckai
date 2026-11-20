# -*- coding: utf-8 -*-
"""攻击编排器 —— 对应本程序的 executor / scenario 模块。

本程序 一次攻击的完整管线（v2 加入了 payload 包装层）：

    objective（来自 seed 数据集 / 手输）
        │
        ▼
    Payload.compose()             ← 可选：DAN/Crescendo 等模板包装
        │
        ▼
    PromptConverter.convert()     ← 攻击模型按本程序 模板改写（或规则编码）
        │
        ▼
    PromptTarget.send_prompt()    ← 目标模型收到最终 prompt
        │
        ▼
    Scorer.score()                ← 攻击模型兼职评分员，判定 True/False
        │
        ▼
    Memory.save()                 ← 落盘 SQLite，可导出报告
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
from datetime import datetime
from threading import Event

from fuckai.client import ChatClient
from fuckai.config import AppConfig
from fuckai.converters import PromptConverter
from fuckai.memory import Memory
from fuckai.payloads import Payload
from fuckai.scorer import TrueFalseScorer

# 批量攻击默认并发数（同时进行的 LLM 调用数）
DEFAULT_CONCURRENCY = 4


class AttackCancelled(Exception):
    """批量攻击被用户取消。"""


class Orchestrator:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        a, t, atk = cfg.attack_model, cfg.target_model, cfg.attack

        self.attack_client = ChatClient(
            a.base_url, a.api_key, a.model,
            temperature=a.temperature, timeout=atk.timeout, max_tokens=None,
        )
        self.target_client = ChatClient(
            t.base_url, t.api_key, t.model,
            temperature=t.temperature, timeout=atk.timeout, max_tokens=None,
        )
        self.converter = PromptConverter(self.attack_client, atk.variation_count)
        self.scorer = TrueFalseScorer(self.attack_client)
        self.memory = Memory(cfg.db_path)
        # 每条记录随附本次使用的攻击者 / 被攻击模型信息
        self.model_info = {
            "attack_model": a.model or "",
            "attack_url": a.base_url or "",
            "target_model": t.model or "",
            "target_url": t.base_url or "",
        }

    def run(self, objective: str, converter_id: str = "direct",
            payload: Payload | None = None, verbose: bool = True,
            meta: dict | None = None) -> dict:
        """执行一次完整攻击管线。payload 为可选的越狱/执行器模板包装。

        meta: 可选的种子元数据 {"dataset": 数据集名, "harm": harm_categories}
        """
        meta = meta or {}

        # 1) payload 包装：objective 填进 DAN/Crescendo 等模板占位符
        try:
            if payload is not None:
                prompt = payload.compose(objective)
            else:
                prompt = objective
        except Exception as e:
            return self._fail(converter_id, objective, payload, f"[模板包装失败] {e}", verbose,
                              meta=meta)

        # 2) converter 变换
        try:
            prompt = self.converter.convert(prompt, converter_id)
        except Exception as e:
            return self._fail(converter_id, objective, payload, f"[变换失败] {e}", verbose, prompt,
                              meta=meta)

        if verbose:
            print("\n  ── 攻击prompt " + "─" * 46)
            self._print_preview(prompt)

        # 3) 发送给被攻击模型
        try:
            response = self.target_client.chat([{"role": "user", "content": prompt}])
        except Exception as e:
            return self._fail(converter_id, objective, payload, f"[被攻击模型调用失败] {e}", verbose,
                              prompt, meta=meta)

        if verbose:
            print("\n  ── 被攻击模型回复 " + "─" * 42)
            self._print_preview(response)

        # 4) 评分（多维：success / severity / category / refusal_level / evidence）
        result = self.scorer.score(objective, prompt, response)
        success, reason = result.as_tuple()

        # 5) 落盘
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "converter": converter_id,
            "payload": payload.name if payload else "",
            "objective": objective,
            "prompt": prompt,
            "response": response,
            "success": success,
            "reason": reason,
            "severity": result.severity,
            "category": result.category,
            "refusal_level": result.refusal_level,
            "evidence": result.evidence,
            "dataset": meta.get("dataset", "") or (payload.dataset if payload else ""),
            "harm": meta.get("harm", "") or (payload.harm if payload else ""),
            "harm_major": meta.get("harm_major", "") or (payload.harm_major if payload else ""),
            **self.model_info,
        }
        self.memory.save(record)
        if verbose:
            tag = "成功 (True) " if success else "被拒绝 (False)"
            print(f"\n  ── 判定: [{tag}] {reason}")
            if result.severity:
                print(f"  ── 多维: 危害等级={result.severity}/5 类别={result.category} "
                      f"拒答={result.refusal_level}")
        return record

    def run_batch(self, objectives: list, converter_ids: list[str],
                  payload: Payload | None = None, verbose: bool = True,
                  cancel: Event | None = None, progress=None,
                  concurrency: int = DEFAULT_CONCURRENCY,
                  timeout: int | None = None) -> list[dict]:
        """并发执行批量攻击。

        objectives: 字符串列表，或 {"value": str, "dataset": str, "harm": str} 字典列表
                    （后者用于把数据集维度带进记录，供矩阵聚合）。
        cancel: threading.Event，置位后未开始的任务跳过执行，在途任务跑完即止。
        progress: callable(done, total, record|None)，每完成一个任务回调一次（取消跳过的任务也回调）。
        timeout: 覆盖单请求超时秒数（None=用构造时的默认值）。
        被取消时抛出 AttackCancelled。
        """
        runner = self
        if timeout is not None and timeout > 0:
            # 每个批次使用独立客户端，避免并发请求互相覆盖超时配置。
            runner = copy(self)
            runner.attack_client = copy(self.attack_client)
            runner.target_client = copy(self.target_client)
            runner.attack_client.timeout = timeout
            runner.target_client.timeout = timeout
            runner.converter = copy(self.converter)
            runner.converter.attack = runner.attack_client
            runner.scorer = copy(self.scorer)
            runner.scorer.judge = runner.attack_client
        items = []
        for o in objectives:
            if isinstance(o, dict):
                items.append((o.get("value", ""), o))
            else:
                items.append((str(o), {}))
        tasks = [(o, c) for o, _ in items for c in converter_ids]
        total = len(tasks)
        results = []
        done = 0
        workers = max(1, min(concurrency, total))

        def _one(objective, cid, meta):
            if cancel is not None and cancel.is_set():
                return None  # 已取消：跳过未开始的任务
            return runner.run(objective, cid, payload=payload, verbose=False, meta=meta)

        if verbose:
            pl = f" 提示词模板={payload.name}" if payload else ""
            print(f"\n批量攻击 {total} 项，并发={workers}{pl}")

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_one, o, c, m): (o, c, m) for (o, m) in items for c in converter_ids}
            for fut in as_completed(futures):
                done += 1
                rec = None
                try:
                    rec = fut.result()
                except Exception as e:  # 单项异常不拖垮整批
                    o, c, m = futures[fut]
                    rec = runner._fail(c, o, payload, f"[异常] {e}", verbose=False, meta=m)
                if progress is not None:
                    try:
                        progress(done, total, rec)
                    except Exception:
                        pass
                if rec is not None:
                    results.append(rec)
                if verbose:
                    print(f"[{done}/{total}] 完成")

        if cancel is not None and cancel.is_set():
            raise AttackCancelled()
        return results

    @staticmethod
    def _print_preview(text: str):
        preview = text if len(text) <= 800 else text[:800] + f" ...(共{len(text)}字符)"
        print("  " + preview.replace("\n", "\n  "))

    def _fail(self, converter_id: str, objective: str, payload: Payload | None,
              reason: str, verbose: bool, prompt: str = "",
              meta: dict | None = None) -> dict:
        meta = meta or {}
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "converter": converter_id,
            "payload": payload.name if payload else "",
            "objective": objective,
            "prompt": prompt,
            "response": "",
            "success": False,
            "reason": reason,
            "severity": 0,
            "category": "",
            "refusal_level": "",
            "evidence": "",
            "dataset": meta.get("dataset", "") or (payload.dataset if payload else ""),
            "harm": meta.get("harm", "") or (payload.harm if payload else ""),
            "harm_major": meta.get("harm_major", "") or (payload.harm_major if payload else ""),
            **self.model_info,
        }
        self.memory.save(record)
        if verbose:
            print(f"  [!] {reason}")
        return record
