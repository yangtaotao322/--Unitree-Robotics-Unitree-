#!/bin/bash
# 宇树 G1 + 千问知识库语音对话
# 启动：bash ~/g1_qwen_rag/start_voice.sh
# 停止：终端输入 q/quit/关闭，或按 Ctrl+C

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITREE_SDK_ROOT="${UNITREE_SDK_ROOT:-/home/zzl/unitree_sdk2}"
G1_IFACE="${G1_IFACE:-enp11s0f1}"
G1_HEAR_LOG="${G1_HEAR_LOG:-/tmp/hear5.log}"
G1_VOICE_BIN="${G1_VOICE_BIN:-$UNITREE_SDK_ROOT/build/bin/g1_voice}"

VOICE_PID=""
BRIDGE_PID=""

cleanup() {
    trap - INT TERM EXIT
    echo ""
    echo "正在关闭语音监听和对话服务..."
    [ -n "$BRIDGE_PID" ] && kill "$BRIDGE_PID" 2>/dev/null || true
    [ -n "$VOICE_PID" ] && kill "$VOICE_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" 2>/dev/null || true
    wait "$VOICE_PID" 2>/dev/null || true
    echo "已关闭，机器人不再监听。"
}
trap cleanup INT TERM EXIT

pkill -x g1_voice 2>/dev/null || true
pkill -f '[g]1_bridge(_benchmark)?.py' 2>/dev/null || true
pkill -f '[i]mport g1_bridge' 2>/dev/null || true
sleep 1

echo "[1/3] 启动机器人语音识别..."
: > "$G1_HEAR_LOG"
"$G1_VOICE_BIN" "$G1_IFACE" hear > "$G1_HEAR_LOG" 2>&1 &
VOICE_PID=$!

echo "[2/3] 启动知识库和千问对话..."
cd "$PROJECT_ROOT"
: > /tmp/bridge.log
env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    UNITREE_SDK_ROOT="$UNITREE_SDK_ROOT" G1_IFACE="$G1_IFACE" G1_HEAR_LOG="$G1_HEAR_LOG" \
    .venv/bin/python g1_bridge.py >> /tmp/bridge.log 2>&1 &
BRIDGE_PID=$!

sleep 4
echo "[3/3] 状态检查:"
kill -0 "$VOICE_PID" 2>/dev/null && echo "  语音识别 OK" || { echo "  语音识别启动失败"; exit 1; }
kill -0 "$BRIDGE_PID" 2>/dev/null && echo "  对话服务 OK" || { echo "  对话服务启动失败"; exit 1; }

echo ""
echo "已开始监听。先说「你好」或「小宇」，之后可以连续追问。"
echo "要彻底停止监听：在本终端输入 q/quit/关闭 后回车，或按 Ctrl+C。"

while kill -0 "$VOICE_PID" 2>/dev/null && kill -0 "$BRIDGE_PID" 2>/dev/null; do
    if read -r -t 1 command; then
        case "$command" in
            q|quit|exit|关闭|停止) break ;;
            *) echo "输入 q、quit 或 关闭 可停止监听。" ;;
        esac
    fi
done
