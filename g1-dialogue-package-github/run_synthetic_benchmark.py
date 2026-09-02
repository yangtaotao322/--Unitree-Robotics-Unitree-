#!/usr/bin/env python3
import csv
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
HEAR_LOG = os.getenv("G1_HEAR_LOG", "/tmp/hear5.log")
METRICS = os.path.join(ROOT, "logs", "performance_metrics.csv")
RUN_LOG = os.path.join(ROOT, "logs", "synthetic_run.log")

QUESTIONS = [
    "小宇，请用一句话介绍你自己。",
    "你现在使用的是什么大模型？",
    "宇树G1适合哪些应用场景？",
    "机器人二次开发需要掌握哪些技术？",
    "请用通俗的话解释ROS2。",
    "使用人形机器人时要注意哪些安全事项？",
    "你刚才介绍了哪些技术？",
    "请再补充一个实际项目例子。",
    "把刚才的例子压缩成一句话。",
    "请总结我们这十轮对话。",
]


def row_count():
    if not os.path.exists(METRICS):
        return 0
    with open(METRICS, "r", encoding="utf-8-sig", newline="") as source:
        return sum(1 for _ in csv.DictReader(source))


os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
with open(RUN_LOG, "a", encoding="utf-8") as run_log:
    run_log.write("\nRUN_START %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    for index, question in enumerate(QUESTIONS, 1):
        before = row_count()
        with open(HEAR_LOG, "a", encoding="utf-8") as hear_log:
            hear_log.write("ASR_TEXT:" + question + "\n")
        print("ROUND_%02d_SENT:%s" % (index, question), flush=True)
        deadline = time.time() + 70
        while time.time() < deadline and row_count() <= before:
            time.sleep(0.5)
        success = row_count() > before
        status = "DONE" if success else "TIMEOUT"
        line = "ROUND_%02d_%s" % (index, status)
        print(line, flush=True)
        run_log.write(line + "\n")
        run_log.flush()
        if not success:
            break
        time.sleep(3)
    run_log.write("RUN_END %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
print("SYNTHETIC_BENCHMARK_FINISHED", flush=True)
