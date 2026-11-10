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
from datetime import datetime

from fuckai.client import ChatClient
from fuckai.config import AppConfig
from fuckai.converters import PromptConverter
from fuckai.memory import Memory
from fuckai.payloads import Payload
from fuckai.scorer import TrueFalseScorer


class Orchestrator:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        a, t, atk = cfg.attack_model, cfg.target_model, cfg.attack

        self.attack_client = ChatClient(
            a.base_url, a.api_key, a.model,
            temperature=a.temperature, timeout=atk.timeout, max_tokens=atk.max_tokens,
        )
        self.target_client = ChatClient(
            t.base_url, t.api_key, t.model,
            temperature=t.temperature, timeout=atk.timeout, max_tokens=atk.max_tokens,
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
            payload: Payload | None = None, verbose: bool = True) -> dict:
        """执行一次完整攻击管线。payload 为可选的越狱/执行器模板包装。"""

        # 1) payload 包装：objective 填进 DAN/Crescendo 等模板占位符
        try:
            if payload is not None:
                prompt = payload.compose(objective)
            else:
                prompt = objective
        except Exception as e:
            return self._fail(converter_id, objective, payload, f"[模板包装失败] {e}", verbose)

        # 2) converter 变换
        try:
            prompt = self.converter.convert(prompt, converter_id)
        except Exception as e:
            return self._fail(converter_id, objective, payload, f"[变换失败] {e}", verbose, prompt)

        if verbose:
            print("\n  ── 攻击prompt " + "─" * 46)
            self._print_preview(prompt)

        # 3) 发送给被攻击模型
        try:
            response = self.target_client.chat([{"role": "user", "content": prompt}])
        except Exception as e:
            return self._fail(converter_id, objective, payload, f"[被攻击模型调用失败] {e}", verbose, prompt)

        if verbose:
            print("\n  ── 被攻击模型回复 " + "─" * 42)
            self._print_preview(response)

        # 4) 评分
        success, reason = self.scorer.score(objective, prompt, response)

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
            **self.model_info,
        }
        self.memory.save(record)
        if verbose:
            tag = "成功 (True) " if success else "被拒绝 (False)"
            print(f"\n  ── 判定: [{tag}] {reason}")
        return record

    def run_batch(self, objectives: list[str], converter_ids: list[str],
                  payload: Payload | None = None, verbose: bool = True) -> list[dict]:
        results = []
        total = len(objectives) * len(converter_ids)
        done = 0
        for objective in objectives:
            for cid in converter_ids:
                done += 1
                if verbose:
                    pl = f" 提示词模板={payload.name}" if payload else ""
                    print(f"\n[{done}/{total}] 变换器={cid}{pl}  话题={objective[:60]}")
                results.append(self.run(objective, cid, payload=payload, verbose=verbose))
        return results

    @staticmethod
    def _print_preview(text: str):
        preview = text if len(text) <= 800 else text[:800] + f" ...(共{len(text)}字符)"
        print("  " + preview.replace("\n", "\n  "))

    def _fail(self, converter_id: str, objective: str, payload: Payload | None,
              reason: str, verbose: bool, prompt: str = "") -> dict:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "converter": converter_id,
            "payload": payload.name if payload else "",
            "objective": objective,
            "prompt": prompt,
            "response": "",
            "success": False,
            "reason": reason,
            **self.model_info,
        }
        self.memory.save(record)
        if verbose:
            print(f"  [!] {reason}")
        return record
