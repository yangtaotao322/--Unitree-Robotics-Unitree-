#!/usr/bin/env python3
"""Run the shared dialogue core through an UBTECH robot adapter."""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ubtech import MockUbtechAdapter, UbtechRos2Adapter


METRIC_FIELDS = [
    "timestamp",
    "question",
    "answer",
    "kb_ms",
    "llm_ms",
    "play_request_ms",
    "playback_first_event_ms",
    "text_input_to_first_event_ms",
    "playback_complete_ms",
    "round_total_ms",
    "accepted",
    "completed",
    "success",
    "request_id",
    "error_type",
]


def _safe_health(health: Dict[str, Any]) -> Dict[str, Any]:
    """Only print operational state; never print auth responses or credentials."""

    return {
        "authorized": bool(health.get("authorized", False)),
        "ready": bool(health.get("ready", False)),
        "current_mode": health.get("current_mode", ""),
        "simulated": bool(health.get("simulated", False)),
    }


def write_metric(metric: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    row = {field: metric.get(field, "") for field in METRIC_FIELDS}
    with path.open("a", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=METRIC_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def run_turn(
    core: Any,
    adapter: Any,
    question: str,
    action: str,
    metric_path: Path,
) -> bool:
    turn_started = perf_counter()
    metric: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "question": question,
        "success": False,
    }
    try:
        reply = core.ask(question)
        core_elapsed_ms = (perf_counter() - turn_started) * 1000
        playback = adapter.speak(reply.answer, action=action, wait=True)
        metric.update(
            {
                "answer": reply.answer,
                "kb_ms": round(reply.kb_ms, 3),
                "llm_ms": round(reply.llm_ms, 3),
                "play_request_ms": round(playback.request_ms, 3),
                "playback_first_event_ms": (
                    round(playback.first_event_ms, 3)
                    if playback.first_event_ms is not None
                    else ""
                ),
                "text_input_to_first_event_ms": (
                    round(core_elapsed_ms + playback.first_event_ms, 3)
                    if playback.first_event_ms is not None
                    else ""
                ),
                "playback_complete_ms": (
                    round(playback.playback_ms, 3)
                    if playback.playback_ms is not None
                    else ""
                ),
                "accepted": playback.accepted,
                "completed": playback.completed,
                "success": playback.success,
                "request_id": playback.request_id,
                "error_type": "" if playback.success else playback.message,
            }
        )
        print("问题：" + reply.question)
        print("回答：" + reply.answer)
        print(
            "播报：accepted=%s completed=%s success=%s request_id=%s"
            % (
                playback.accepted,
                playback.completed,
                playback.success,
                playback.request_id,
            )
        )
        return playback.success
    except Exception as exc:
        metric["error_type"] = type(exc).__name__
        print("本轮失败：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return False
    finally:
        metric["round_total_ms"] = round((perf_counter() - turn_started) * 1000, 3)
        write_metric(metric, metric_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UBTECH 智慧对话迁移程序")
    parser.add_argument("--mock", action="store_true", help="使用本地模拟机器人")
    parser.add_argument("--authorize", action="store_true", help="使用环境变量执行鉴权")
    parser.add_argument("--check", action="store_true", help="只检查鉴权和 ready 状态")
    parser.add_argument("--ask", help="执行一轮知识库问答并让机器人播报")
    parser.add_argument("--say", help="跳过知识库和大模型，直接测试机器人播报")
    parser.add_argument("--play-action", help="直接测试动作编号，例如 A029")
    parser.add_argument("--list-actions", action="store_true", help="读取可用动作列表")
    parser.add_argument("--interactive", action="store_true", help="进入连续文字问答")
    parser.add_argument("--action", default="", help="播报时伴随的可选动作编号")
    parser.add_argument(
        "--metrics",
        default=str(PROJECT_ROOT / "logs" / "ubtech_performance_metrics.csv"),
        help="CSV 指标输出路径",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.ubtech")
    adapter = MockUbtechAdapter() if args.mock else UbtechRos2Adapter()
    try:
        if args.authorize and not args.mock:
            adapter.authorize_from_env()
        health = _safe_health(adapter.health_check())
        print("机器人状态：" + json.dumps(health, ensure_ascii=False))
        if not health["authorized"] or not health["ready"]:
            print("机器人未完成鉴权或未处于 ready 状态。", file=sys.stderr)
            return 2
        if args.check and not any(
            (args.ask, args.say, args.play_action, args.list_actions, args.interactive)
        ):
            return 0
        if args.list_actions:
            print(json.dumps(adapter.get_motion_info_list(), ensure_ascii=False, indent=2))
            return 0
        if args.say:
            result = adapter.speak(args.say, action=args.action, wait=True)
            print(json.dumps(result.__dict__, ensure_ascii=False, default=str, indent=2))
            return 0 if result.success else 3
        if args.play_action:
            result = adapter.play_action(args.play_action, wait=True)
            print(json.dumps(result.__dict__, ensure_ascii=False, default=str, indent=2))
            return 0 if result.success else 3

        from src.dialogue_core import DialogueCore
        from src.knowledge_base import KnowledgeBase
        from src.qwen_client import QwenClient

        core = DialogueCore(
            KnowledgeBase(str(PROJECT_ROOT / "knowledge")),
            QwenClient(system_identity="优必选机器人上的智能语音助手"),
            top_k=2,
            max_history_rounds=3,
        )
        metric_path = Path(args.metrics)
        if args.ask:
            return 0 if run_turn(core, adapter, args.ask, args.action, metric_path) else 4

        if not args.interactive:
            args.interactive = True
        print("连续文字问答已启动；输入 q、quit 或 退出 可结束。")
        while True:
            try:
                question = input("你：").strip()
            except EOFError:
                break
            if question.lower() in {"q", "quit", "exit"} or question == "退出":
                break
            if question:
                run_turn(core, adapter, question, args.action, metric_path)
        return 0
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
