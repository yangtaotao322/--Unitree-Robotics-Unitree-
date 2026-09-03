#!/usr/bin/env python3
"""Ten-round software-only smoke test for the UBTECH migration path."""

import json
import sys
from pathlib import Path
from statistics import mean
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.dialogue_core import DialogueCore
from ubtech.mock_adapter import MockUbtechAdapter


QUESTIONS = [
    "你好",
    "介绍一下你自己",
    "你能做什么",
    "公司在哪里",
    "今天星期几",
    "讲一句欢迎词",
    "怎么联系工作人员",
    "请简短回答",
    "继续介绍",
    "再见",
]


class FakeKnowledgeBase:
    def search(self, question, top_k=2):
        return [{"answer": "这是本地模拟知识。", "score": 1.0}][:top_k]


class FakeLlmClient:
    def ask(self, question, context="", history=None):
        return "已收到问题：%s" % question


def percentile95(values):
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


def main() -> int:
    core = DialogueCore(FakeKnowledgeBase(), FakeLlmClient())
    adapter = MockUbtechAdapter(request_delay=0.001, playback_delay=0.002)
    rounds = []
    for index, question in enumerate(QUESTIONS, 1):
        started = perf_counter()
        reply = core.ask(question)
        result = adapter.speak(reply.answer, wait=True)
        rounds.append(
            {
                "round": index,
                "question": question,
                "success": result.success,
                "kb_ms": round(reply.kb_ms, 3),
                "llm_ms": round(reply.llm_ms, 3),
                "request_ms": round(result.request_ms, 3),
                "playback_ms": round(result.playback_ms or 0, 3),
                "round_total_ms": round((perf_counter() - started) * 1000, 3),
            }
        )
    totals = [item["round_total_ms"] for item in rounds]
    report = {
        "mode": "MOCK_NOT_HARDWARE",
        "rounds": len(rounds),
        "successes": sum(1 for item in rounds if item["success"]),
        "failures": sum(1 for item in rounds if not item["success"]),
        "average_round_ms": round(mean(totals), 3),
        "p95_round_ms": round(percentile95(totals), 3),
        "details": rounds,
    }
    output = PROJECT_ROOT / "logs" / "ubtech_mock_smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("报告：" + str(output))
    return 0 if report["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

