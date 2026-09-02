#!/usr/bin/env python3
import csv
import math
import os
from collections import Counter
from datetime import datetime

ROOT = os.path.dirname(__file__)
CSV_PATH = os.path.join(ROOT, "logs", "performance_metrics.csv")
REPORT_PATH = os.path.join(ROOT, "logs", "performance_summary.md")


def numbers(rows, key):
    values = []
    for row in rows:
        raw = row.get(key, "").strip()
        if raw:
            try:
                values.append(float(raw))
            except ValueError:
                pass
    return values


def percentile(values, ratio):
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1))
    return ordered[index]


def metric_row(rows, key, label):
    values = numbers(rows, key)
    if not values:
        return f"| {label} | 0 | - | - | - | - |"
    return "| %s | %d | %.0f | %.0f | %.0f | %.0f |" % (
        label, len(values), sum(values) / len(values), percentile(values, 0.5),
        percentile(values, 0.95), max(values),
    )


if not os.path.exists(CSV_PATH):
    raise SystemExit("尚无测试数据：" + CSV_PATH)

with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as source:
    rows = list(csv.DictReader(source))

total = len(rows)
successes = sum(row.get("success", "").lower() == "true" for row in rows)
failures = total - successes
errors = Counter(
    (row.get("error_stage") or "unknown") + ":" + (row.get("error_type") or "unknown")
    for row in rows if row.get("success", "").lower() != "true"
)

longest_success = current_success = 0
for row in rows:
    if row.get("success", "").lower() == "true":
        current_success += 1
        longest_success = max(longest_success, current_success)
    else:
        current_success = 0

lines = [
    "# G1 语音对话性能测试汇总",
    "",
    "生成时间：%s" % datetime.now().astimezone().isoformat(timespec="seconds"),
    "",
    "- 有效测试轮数：%d" % total,
    "- 成功轮数：%d" % successes,
    "- 失败轮数：%d" % failures,
    "- 异常率：%.2f%%" % ((failures / total * 100) if total else 0),
    "- 最长连续成功轮数：%d" % longest_success,
    "",
    "| 指标 | 样本数 | 平均值(ms) | P50(ms) | P95(ms) | 最大值(ms) |",
    "|---|---:|---:|---:|---:|---:|",
]

for key, label in [
    ("manual_asr_ms", "ASR（人工结束标记→识别结果）"),
    ("kb_ms", "知识库检索"),
    ("llm_ms", "模型响应"),
    ("tts_synth_ms", "TTS 合成"),
    ("audio_convert_ms", "音频转换"),
    ("audio_first_chunk_ms", "播放调用→首包下发"),
    ("first_response_ms", "ASR 结果→音频首包（系统首响）"),
    ("round_total_ms", "ASR 结果→整轮播放完成"),
]:
    lines.append(metric_row(rows, key, label))

lines.extend(["", "## 异常分布", ""])
if errors:
    for error, count in errors.most_common():
        lines.append("- %s：%d 次" % (error, count))
else:
    lines.append("- 未记录异常")

lines.extend([
    "",
    "> 说明：系统首响从收到 ASR 最终文本开始计时；端到端口到耳首响可用 ASR 人工标记值与系统首响相加估算。",
    "",
])

report = "\n".join(lines)
with open(REPORT_PATH, "w", encoding="utf-8") as output:
    output.write(report)
print(report)
print("\n报告文件：" + REPORT_PATH)
