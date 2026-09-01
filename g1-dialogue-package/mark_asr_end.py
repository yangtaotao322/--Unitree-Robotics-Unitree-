#!/usr/bin/env python3
import time

print("请开始说测试问题；说完最后一个字时立即按回车。", flush=True)
input()
ended_ms = time.time_ns() // 1_000_000
with open("/tmp/g1_asr_end_ms", "w", encoding="utf-8") as marker:
    marker.write(str(ended_ms))
print("已标记语音结束时间：%d ms" % ended_ms, flush=True)
