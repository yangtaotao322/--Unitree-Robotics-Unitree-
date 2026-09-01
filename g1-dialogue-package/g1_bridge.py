#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
import sys
import subprocess
import time
import re
import random
import csv
import json
import shutil
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from qwen_client import QwenClient
from knowledge_base import KnowledgeBase

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
UNITREE_SDK_ROOT = os.getenv("UNITREE_SDK_ROOT", "/home/zzl/unitree_sdk2")
IFACE = os.getenv("G1_IFACE", "enp11s0f1")
HEAR_LOG = os.getenv("G1_HEAR_LOG", "/tmp/hear5.log")
G1_VOICE = os.getenv("G1_VOICE_BIN", os.path.join(UNITREE_SDK_ROOT, "build/bin/g1_voice"))
G1_PLAY_WAV = os.getenv("G1_PLAY_WAV_BIN", os.path.join(UNITREE_SDK_ROOT, "build/bin/g1_play_wav"))
ARM_ACTION = os.getenv("G1_ARM_ACTION_BIN", os.path.join(UNITREE_SDK_ROOT, "build/bin/g1_arm_action_example"))
EDGE_TTS = os.getenv("EDGE_TTS_BIN") or shutil.which("edge-tts") or "/home/zzl/.local/bin/edge-tts"
POLL_INTERVAL = 0.5

WOKE_TEXT = "你好，我在，请问有什么可以帮您"
WOKE_PATTERNS = ["你好，帅哥", "你好帅哥", "你好", "小宇", "小宇同学", "宇树", "好话", "您好", "你好啊", "哈喽", "在吗", "嗨"]
MIN_QUERY_LEN = 2
SILENT_AFTER_TALK = 2.0
STOP_PATTERNS = ["停止", "闭嘴", "别说了", "别讲了", "安静", "停一下", "不要说了", "打住"]
RESUME_PATTERNS = ["继续", "接着聊", "再说吧", "好了", "小宇"]
LISTEN_TIMEOUT = 120.0
# 握手(27)/击掌(18)/头上挥手(26)/拥抱(19)
GESTURES = [27, 18, 26, 19]

METRICS_DIR = os.path.join(os.path.dirname(__file__), "logs")
METRICS_CSV = os.path.join(METRICS_DIR, "performance_metrics.csv")
METRICS_JSONL = os.path.join(METRICS_DIR, "performance_metrics.jsonl")
ASR_END_MARKER = "/tmp/g1_asr_end_ms"
METRIC_FIELDS = [
    "round_id", "timestamp", "turn_index", "state", "question",
    "asr_received_epoch_ms", "manual_asr_ms", "kb_ms", "llm_ms",
    "tts_synth_ms", "audio_convert_ms", "audio_first_chunk_ms",
    "audio_play_ms", "first_response_ms", "round_total_ms",
    "answer_chars", "success", "error_stage", "error_type",
]

kb = KnowledgeBase(os.path.join(os.path.dirname(__file__), "knowledge"))
client = QwenClient()

state = "idle"  # idle=等待唤醒词, listening=连续对话
last_input_time = 0.0
turn_index = 0


def now_ms():
    return time.time_ns() // 1_000_000


def read_manual_asr_ms(asr_received_epoch_ms):
    try:
        with open(ASR_END_MARKER, "r", encoding="utf-8") as marker:
            speech_end_ms = int(marker.read().strip())
        os.remove(ASR_END_MARKER)
        delta = asr_received_epoch_ms - speech_end_ms
        return delta if 0 <= delta <= 15000 else ""
    except (FileNotFoundError, ValueError, OSError):
        return ""


def write_metric(metric):
    os.makedirs(METRICS_DIR, exist_ok=True)
    metric = {key: metric.get(key, "") for key in METRIC_FIELDS}
    new_file = not os.path.exists(METRICS_CSV)
    with open(METRICS_CSV, "a", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=METRIC_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(metric)
    with open(METRICS_JSONL, "a", encoding="utf-8") as output:
        output.write(json.dumps(metric, ensure_ascii=False) + "\n")
    print("PERF_METRIC:" + json.dumps(metric, ensure_ascii=False), flush=True)


def say(text):
    # 中文内置 TTS 在当前固件上静音：改用 Edge TTS 合成 WAV，再经宇树 PlayStream 播放。
    spoken = re.sub(r"https?://\S+", "", text)
    spoken = re.sub(r"[*#_~\[\]{}<>|]", "", spoken)
    spoken = re.sub(r"[\U00010000-\U0010ffff]", "", spoken)
    spoken = re.sub(r"\s+", " ", spoken).strip()
    if len(spoken) > 120:
        cut = max(spoken.rfind(mark, 0, 120) for mark in "。！？；")
        spoken = spoken[:cut + 1] if cut >= 30 else spoken[:120] + "。"
    if not spoken:
        spoken = "抱歉，我暂时没有生成可播报的回答。"

    audio_dir = os.path.join(os.path.dirname(__file__), "runtime_audio")
    os.makedirs(audio_dir, exist_ok=True)
    token = "%d_%d" % (os.getpid(), int(time.time() * 1000))
    mp3_path = os.path.join(audio_dir, token + ".mp3")
    wav_path = os.path.join(audio_dir, token + ".wav")
    timing = {
        "success": False,
        "error_stage": "",
        "error_type": "",
        "tts_synth_ms": "",
        "audio_convert_ms": "",
        "audio_first_chunk_ms": "",
        "audio_play_ms": "",
        "first_chunk_epoch_ms": "",
    }
    try:
        synth_started = now_ms()
        synth = subprocess.run(
            [
                EDGE_TTS,
                "--voice", "zh-CN-XiaoxiaoNeural",
                "--rate", "+15%",
                "--text", spoken,
                "--write-media", mp3_path,
            ],
            capture_output=True, text=True, timeout=35,
        )
        timing["tts_synth_ms"] = now_ms() - synth_started
        if synth.returncode != 0:
            print("EDGE_TTS_ERR: " + synth.stderr.strip(), flush=True)
            timing["error_stage"] = "tts_synth"
            timing["error_type"] = "EdgeTTSReturnCode%d" % synth.returncode
            return timing

        convert_started = now_ms()
        convert = subprocess.run(
            [
                "gst-launch-1.0", "-q",
                "filesrc", "location=" + mp3_path,
                "!", "decodebin",
                "!", "audioconvert",
                "!", "audioresample",
                "!", "audio/x-raw,format=S16LE,rate=16000,channels=1",
                "!", "wavenc",
                "!", "filesink", "location=" + wav_path,
            ],
            capture_output=True, text=True, timeout=20,
        )
        timing["audio_convert_ms"] = now_ms() - convert_started
        if convert.returncode != 0:
            print("AUDIO_CONVERT_ERR: " + convert.stderr.strip(), flush=True)
            timing["error_stage"] = "audio_convert"
            timing["error_type"] = "GStreamerReturnCode%d" % convert.returncode
            return timing

        play_started = now_ms()
        play = subprocess.Popen(
            [G1_PLAY_WAV, IFACE, wav_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        stdout_lines = []
        first_chunk_epoch_ms = None
        try:
            for line in iter(play.stdout.readline, ""):
                stdout_lines.append(line)
                if first_chunk_epoch_ms is None and "PLAY_CHUNK" in line:
                    first_chunk_epoch_ms = now_ms()
            stderr_text = play.stderr.read()
            play.wait(timeout=45)
        except subprocess.TimeoutExpired:
            play.kill()
            play.wait()
            timing["error_stage"] = "audio_play"
            timing["error_type"] = "TimeoutExpired"
            return timing
        play_finished = now_ms()
        timing["audio_play_ms"] = play_finished - play_started
        if first_chunk_epoch_ms is not None:
            timing["first_chunk_epoch_ms"] = first_chunk_epoch_ms
            timing["audio_first_chunk_ms"] = first_chunk_epoch_ms - play_started
        stdout_text = "".join(stdout_lines).strip()
        print(
            "TTS_PCM: ret=%d text=%s out=%s err=%s"
            % (play.returncode, spoken, stdout_text, stderr_text.strip()),
            flush=True,
        )
        timing["success"] = play.returncode == 0 and first_chunk_epoch_ms is not None
        if not timing["success"]:
            timing["error_stage"] = "audio_play"
            timing["error_type"] = "PlayReturnCode%d" % play.returncode
        return timing
    except Exception as exc:
        print("TTS_PCM_ERR: %s: %s" % (type(exc).__name__, exc), flush=True)
        timing["error_stage"] = timing["error_stage"] or "tts_pipeline"
        timing["error_type"] = type(exc).__name__
        return timing
    finally:
        for audio_path in (mp3_path, wav_path):
            try:
                os.remove(audio_path)
            except FileNotFoundError:
                pass


def trigger_gesture():
    gid = random.choice(GESTURES)
    try:
        r = subprocess.run(
            [ARM_ACTION, "--network", IFACE, "--id", str(gid)],
            capture_output=True, timeout=30,
        )
        print("GESTURE: id=%d ret=%d" % (gid, r.returncode), flush=True)
        if r.stdout:
            print("GESTURE_OUT:" + r.stdout.decode("utf-8", "replace")[:200], flush=True)
    except Exception as e:
        print("GESTURE_ERR:" + type(e).__name__, flush=True)


def is_wake(text):
    t = re.sub(r"[\s，。,.！!？?、]", "", text)
    for w in WOKE_PATTERNS:
        if w in t:
            return True
    return False


def clean_query(text):
    query = text
    for word in sorted(WOKE_PATTERNS, key=len, reverse=True):
        query = query.replace(word, "")
    return query.strip(" \t，。,.！!？?、")


def is_valid_query(text):
    normalized = re.sub(r"[\s，。,.！!？?、]", "", text)
    if len(normalized) < MIN_QUERY_LEN:
        return False
    if normalized in {"嗯嗯", "啊啊", "哦哦", "好的", "嗯", "啊", "哦"}:
        return False
    return True


HISTORY = []
MAX_HISTORY_ROUNDS = 3


def process_query(text, asr_received_epoch_ms, query_state):
    global HISTORY, turn_index
    turn_index += 1
    round_started = now_ms()
    metric = {
        "round_id": "%d-%03d" % (asr_received_epoch_ms, turn_index),
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "turn_index": turn_index,
        "state": query_state,
        "question": text,
        "asr_received_epoch_ms": asr_received_epoch_ms,
        "manual_asr_ms": read_manual_asr_ms(asr_received_epoch_ms),
        "success": False,
        "error_stage": "",
        "error_type": "",
    }
    try:
        print("QUERY:", text, flush=True)
        kb_started = now_ms()
        results = kb.search(text, top_k=2)
        metric["kb_ms"] = now_ms() - kb_started
        context = "\n".join(r.get("answer", "") for r in results)

        llm_started = now_ms()
        answer = client.ask(text, context, HISTORY)
        metric["llm_ms"] = now_ms() - llm_started
        metric["answer_chars"] = len(answer or "")
        print("ANSWER:", answer, flush=True)
        llm_failed = "大脑暂时没响应" in (answer or "")
        if llm_failed:
            metric["error_stage"] = "llm"
            metric["error_type"] = "QwenClientErrorFallback"

        HISTORY.append({"role": "user", "content": text})
        HISTORY.append({"role": "assistant", "content": answer})
        if len(HISTORY) > MAX_HISTORY_ROUNDS * 2:
            del HISTORY[: len(HISTORY) - MAX_HISTORY_ROUNDS * 2]

        audio = say(answer)
        for key in (
            "tts_synth_ms", "audio_convert_ms", "audio_first_chunk_ms",
            "audio_play_ms",
        ):
            metric[key] = audio.get(key, "")
        if audio.get("first_chunk_epoch_ms"):
            metric["first_response_ms"] = (
                audio["first_chunk_epoch_ms"] - asr_received_epoch_ms
            )
        if not audio.get("success") and not metric["error_stage"]:
            metric["error_stage"] = audio.get("error_stage", "audio")
            metric["error_type"] = audio.get("error_type", "UnknownAudioError")
        metric["success"] = bool(audio.get("success") and not llm_failed)
    except Exception as exc:
        metric["error_stage"] = metric["error_stage"] or "bridge"
        metric["error_type"] = type(exc).__name__
        print("PERF_ROUND_ERR:%s:%s" % (type(exc).__name__, exc), flush=True)
    finally:
        metric["round_total_ms"] = now_ms() - round_started
        write_metric(metric)


def main():
    global state, last_input_time
    print("BRIDGE_WAKE_START", flush=True)
    last_say_time = 0.0
    try:
        with open(HEAR_LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(POLL_INTERVAL)
                    if state == "listening" and (time.time() - last_input_time) > LISTEN_TIMEOUT:
                        state = "idle"
                        print("STATE=TIMEOUT->IDLE", flush=True)
                    continue
                m = re.search(r"ASR_TEXT:(.*)$", line)
                if not m:
                    continue
                text = m.group(1).strip().replace("\\n", "").strip()
                if not text:
                    continue
                asr_received_epoch_ms = now_ms()
                last_input_time = time.time()
                now = time.time()
                t_norm = re.sub(r"[\s，。,.！!？?、]", "", text)
                if any(w in t_norm for w in STOP_PATTERNS):
                    say("好的，我先安静了")
                    last_say_time = time.time()
                    state = "paused"
                    print("STATE=PAUSED:", text, flush=True)
                    continue
                if state == "paused":
                    if any(w in t_norm for w in RESUME_PATTERNS) or is_wake(text):
                        say("好的，我回来了")
                        last_say_time = time.time()
                        state = "listening"
                        print("STATE=RESUMED:", text, flush=True)
                    else:
                        print("PAUSED(ignored):", text, flush=True)
                    continue
                if now - last_say_time < SILENT_AFTER_TALK:
                    print("SILENT:", text, flush=True)
                    continue
                if state == "idle":
                    if not is_wake(text):
                        print("IDLE(ignored):", text, flush=True)
                        continue
                    query = clean_query(text)
                    state = "listening"
                    print("STATE=LISTENING:", text, flush=True)
                    # 先回答，避免机器人动作接口阻塞语音。
                    if query and is_valid_query(query):
                        process_query(query, asr_received_epoch_ms, "wake_query")
                    else:
                        say(WOKE_TEXT)
                    last_say_time = time.time()
                elif state == "listening":
                    if not is_valid_query(text):
                        print("LISTENING(ignored):", text, flush=True)
                        continue
                    print("STATE=HEARD:", text, flush=True)
                    process_query(text, asr_received_epoch_ms, "continuous")
                    last_say_time = time.time()
                    print("STATE=LISTENING", flush=True)
    except KeyboardInterrupt:
        print("BRIDGE_STOP", flush=True)


if __name__ == "__main__":
    main()
