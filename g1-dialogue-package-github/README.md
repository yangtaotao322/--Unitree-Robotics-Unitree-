# 宇树 G1 智慧语音对话系统：从零部署指南

本项目是在宇树 G1 上实际跑通的智慧语音对话链路，包含机器人语音识别、唤醒与连续对话、本地知识库检索、千问大模型、中文语音合成、机器人扬声器播放、性能埋点和固定问题测试。

本文面向第一次部署该项目的人。按照顺序执行，可从一台 Ubuntu 开发电脑和一台具备语音服务的宇树 G1 开始，最终实现：

```text
用户对机器人说“你好，小宇……”
→ G1 输出 ASR 最终文本
→ 本地知识库检索
→ 千问生成简短回答
→ Edge TTS 生成中文语音
→ 转换成 G1 支持的 PCM WAV
→ Unitree PlayStream 播放
→ 机器人说出回答
```

> 重要限制：并非所有 G1、固件或出厂配置都会发布 ASR 和麦克风数据。部署前必须先完成第 8 节的分层验证。看到 `LISTENING` 或进程存活，不代表 ASR 功能真的可用。

## 1. 已验证范围

本项目实际验证环境：

- 开发电脑：Ubuntu 22.04。
- 开发电脑用户示例：`zzl`。
- 机器人有线接口：`enp11s0f1`。
- 开发电脑机器人网卡：`192.168.123.18/24`。
- 开发电脑 WiFi：负责互联网、千问和 Edge TTS。
- 宇树 SDK：`unitree_sdk2`。
- G1 ASR Topic：`rt/audio_msg`。
- 知识库模型：`BAAI/bge-small-zh-v1.5`，CPU 推理。
- 大模型：`qwen-turbo`。
- TTS：`edge-tts`，`zh-CN-XiaoxiaoNeural`，语速 `+15%`。
- 播放格式：16 kHz、单声道、16 bit PCM WAV。

实际固定 10 轮测试结果：

| 指标 | 优化前 | 优化后 | 改善 |
|---|---:|---:|---:|
| 模型平均响应 | 1151.2 ms | 523.9 ms | 54.5% |
| TTS 平均合成 | 2011.8 ms | 1813.8 ms | 9.8% |
| 系统平均首响 | 3517.2 ms | 2682.8 ms | 23.7% |
| 平均整轮完成 | 14626.8 ms | 8787.6 ms | 39.9% |
| 平均回答长度 | 47.4 字 | 22.6 字 | 减少 52.3% |
| 成功率 | 10/10 | 10/10 | 保持 100% |

现场真人语音补充测试完成 2 轮，识别、回答和播放均成功。由于当时没有准确记录用户说完的时刻，ASR 耗时未填写，也没有编造该数据。

## 2. 系统架构

```text
┌──────────────────────────────────────────────────────────────┐
│                         宇树 G1                              │
│  麦克风/固件 ASR → DDS Topic rt/audio_msg                   │
│  扬声器 ← AudioClient.PlayStream                            │
└───────────────────────┬───────────────────▲──────────────────┘
                        │                   │
                  ASR 最终文本          PCM 音频流
                        │                   │
┌───────────────────────▼───────────────────┴──────────────────┐
│                    Ubuntu 开发电脑                           │
│  g1_voice → /tmp/hear5.log                                  │
│       ↓                                                     │
│  g1_bridge.py                                               │
│       ├─ 唤醒/暂停/连续会话状态机                           │
│       ├─ BGE 本地知识库检索                                 │
│       ├─ 千问 qwen-turbo                                    │
│       ├─ Edge TTS                                           │
│       ├─ GStreamer MP3 → PCM WAV                            │
│       ├─ g1_play_wav → PlayStream                           │
│       └─ CSV/JSONL 性能日志                                 │
└──────────────────────────────────────────────────────────────┘
```

机器人内网和互联网必须分开：

- 有线网卡只负责 G1 DDS 内网。
- WiFi 负责访问千问和 Edge TTS。
- 有线网卡不要配置默认网关。
- 系统默认路由必须走 WiFi。

## 3. 项目目录

```text
g1-dialogue-package/
├── README.md
├── requirements.txt
├── start_voice.sh
├── g1_bridge.py
├── run_synthetic_benchmark.py
├── benchmark_report.py
├── mark_asr_end.py
├── src/
│   ├── knowledge_base.py
│   └── qwen_client.py
├── knowledge/
│   ├── knowledge.json
│   ├── new_knowledge.json
│   ├── extra_knowledge.json
│   └── extra100_knowledge.json
├── voice/
│   ├── g1_voice.cpp
│   ├── g1_play_wav.cpp
│   └── CMakeLists.snippet.txt
├── systemd/
│   ├── g1-dialogue.env.example
│   ├── g1-voice.service
│   └── g1-dialogue.service
└── docs/
    ├── optimization-results.md
    └── 2026-09-01-development-log.md
```

主要文件职责：

- `g1_voice.cpp`：订阅 `rt/audio_msg`，提取并输出 `ASR_TEXT:`。
- `g1_play_wav.cpp`：读取 16 kHz 单声道 PCM WAV，以 32000 字节分块发送给 G1。
- `g1_bridge.py`：完整对话状态机、RAG、千问、TTS、播放和性能统计。
- `knowledge_base.py`：加载 `knowledge/*.json` 并生成 BGE 向量。
- `qwen_client.py`：通过阿里云百炼 OpenAI 兼容接口调用千问。
- `start_voice.sh`：停止旧进程并启动 ASR 监听和对话桥。
- `run_synthetic_benchmark.py`：向 ASR 日志注入固定 10 个问题，测试 ASR 之后的完整链路。
- `benchmark_report.py`：计算平均值、P50、P95、最大值和异常率。

## 4. 准备条件

### 4.1 硬件

- 一台宇树 G1。
- 一台 Ubuntu x86_64 或 ARM64 开发电脑。
- 一根连接 G1 内部交换机/网口的网线。
- 可访问互联网的 WiFi。
- 机器人和电脑电源稳定，现场急停可用。

### 4.2 软件和账号

- Ubuntu 20.04 或 22.04。
- Python 3 和 `venv`。
- CMake、G++、Make。
- Git。
- GStreamer。
- 阿里云百炼 API Key。
- 已能使用的 G1 音频服务。

宇树官方 `unitree_sdk2` 当前说明的预编译参考环境是 Ubuntu 20.04、GCC 9.4、CMake 3.10 以上，同时支持 AArch64 和 x86_64。Ubuntu 22.04 是本项目的现场成功环境，但换机器时仍应先单独编译 SDK 示例确认兼容性。

官方 SDK：<https://github.com/unitreerobotics/unitree_sdk2>

### 4.3 部署前必须确认

先回答以下问题：

1. 机器人有线网卡是否 `UP`、`LOWER_UP`？
2. 开发电脑是否能发现 `192.168.123.161` 和 `192.168.123.164`？
3. `g1_audio_client_example` 能否读取音量？
4. `rt/audio_msg` 是否真的产生 ASR 文本？
5. 机器人扬声器能否播放 PCM WAV？
6. WiFi 能否访问阿里云百炼和 Edge TTS？

如果第 4 项失败，不要继续调试知识库或大模型。该问题位于机器人麦克风、ASR 服务或固件配置，不在 Python 对话程序。

## 5. 下载项目

项目代码位于：

<https://github.com/yangtaotao322/--Unitree-Robotics-Unitree-/tree/main/g1-dialogue-package>

建议克隆时指定一个简单目录名：

```bash
cd "$HOME"
git clone https://github.com/yangtaotao322/--Unitree-Robotics-Unitree-.git g1-dialogue-source
mkdir -p "$HOME/g1_qwen_rag"
cp -a "$HOME/g1-dialogue-source/g1-dialogue-package/." "$HOME/g1_qwen_rag/"
cd "$HOME/g1_qwen_rag"
```

如果通过 ZIP 下载，将 `g1-dialogue-package` 中的全部文件复制到：

```text
$HOME/g1_qwen_rag
```

确认：

```bash
cd "$HOME/g1_qwen_rag"
find . -maxdepth 2 -type f | sort
```

不要把 `__pycache__`、运行日志、生成音频、`.env` 或真实 API Key 提交到 GitHub。

## 6. 配置双网卡网络

以下为本项目实际使用的示例：

```text
有线网卡 enp11s0f1 → 192.168.123.18/24 → 只连接机器人
WiFi      wlp0s20f3  → DHCP              → 访问互联网
```

### 6.1 使用图形界面配置

在 Ubuntu 网络设置中打开机器人有线连接，将 IPv4 设置为手动：

```text
地址：192.168.123.18
子网掩码：255.255.255.0
网关：留空
DNS：留空
```

### 6.2 使用 NetworkManager 配置

先查看连接名称：

```bash
nmcli connection show
ip -br address
```

将 `<wired-connection-name>` 替换为实际有线连接名称：

```bash
sudo nmcli connection modify "<wired-connection-name>" \
  ipv4.method manual \
  ipv4.addresses 192.168.123.18/24 \
  ipv4.gateway "" \
  ipv4.dns "" \
  ipv4.never-default yes

sudo nmcli connection up "<wired-connection-name>"
```

### 6.3 检查路由

```bash
ip -br address
ip route
```

预期：

- `192.168.123.0/24` 走机器人有线网卡。
- `default via ...` 走 WiFi。
- 机器人有线连接没有默认路由。

检查常见 G1 内部节点：

```bash
ping -c 3 192.168.123.161
ping -c 3 192.168.123.164
ip neigh show dev enp11s0f1
```

地址可能随机器人版本变化；能否收到 DDS 数据比固定 IP 更重要。

## 7. 安装系统依赖和 Unitree SDK2

### 7.1 安装依赖

```bash
sudo apt update
sudo apt install -y \
  git cmake g++ build-essential \
  libyaml-cpp-dev libeigen3-dev libboost-all-dev libspdlog-dev libfmt-dev \
  python3 python3-venv python3-pip \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly
```

### 7.2 下载 SDK

```bash
cd "$HOME"
git clone https://github.com/unitreerobotics/unitree_sdk2.git
export UNITREE_SDK_ROOT="$HOME/unitree_sdk2"
```

如果现场使用的是厂家指定版本，应检出对应 Tag 或 Commit，不要在验证期间随意升级：

```bash
cd "$UNITREE_SDK_ROOT"
git status
git log -1 --oneline
```

### 7.3 添加本项目的语音辅助程序

```bash
mkdir -p "$UNITREE_SDK_ROOT/example/g1/voice"
cp "$HOME/g1_qwen_rag/voice/g1_voice.cpp" \
  "$UNITREE_SDK_ROOT/example/g1/voice/g1_voice.cpp"
cp "$HOME/g1_qwen_rag/voice/g1_play_wav.cpp" \
  "$UNITREE_SDK_ROOT/example/g1/voice/g1_play_wav.cpp"
```

确认 SDK 中存在 WAV 读取头文件：

```bash
test -f "$UNITREE_SDK_ROOT/example/g1/audio/wav.hpp" && echo WAV_HEADER_OK
```

`g1_play_wav.cpp` 通过相对路径引用该文件。如果不存在，说明现场 SDK 目录结构不同，需要根据实际版本调整 include 路径。

打开：

```text
$UNITREE_SDK_ROOT/example/g1/CMakeLists.txt
```

在文件末尾添加一次：

```cmake
add_executable(g1_voice voice/g1_voice.cpp)
target_link_libraries(g1_voice unitree_sdk2)

add_executable(g1_play_wav voice/g1_play_wav.cpp)
target_link_libraries(g1_play_wav unitree_sdk2)
```

检查是否重复：

```bash
grep -n "add_executable(g1_voice\|add_executable(g1_play_wav" \
  "$UNITREE_SDK_ROOT/example/g1/CMakeLists.txt"
```

每个目标只能出现一次。

### 7.4 编译 SDK 和辅助程序

```bash
cd "$UNITREE_SDK_ROOT"
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

确认输出：

```bash
ls -lh \
  "$UNITREE_SDK_ROOT/build/bin/g1_voice" \
  "$UNITREE_SDK_ROOT/build/bin/g1_play_wav"
```

如果还要使用动作示例，确认：

```bash
ls -lh "$UNITREE_SDK_ROOT/build/bin/g1_arm_action_example"
```

当前 `g1_bridge.py` 中保留了动作辅助函数，但主对话流程没有主动调用它；默认部署只执行语音，不会自动触发肢体动作。

## 8. 先验证机器人音频层

这是部署中最重要的一步。不要跳过。

### 8.1 验证 ASR Topic

```bash
export G1_IFACE=enp11s0f1
export UNITREE_SDK_ROOT="$HOME/unitree_sdk2"

"$UNITREE_SDK_ROOT/build/bin/g1_voice" "$G1_IFACE" hear
```

程序会先输出类似：

```text
VOLUME:100
LISTENING
```

此时面对机器人清晰说一句话。真正成功必须继续看到：

```text
ASR_TEXT:你好，小宇
```

判断标准：

- 只有 `LISTENING`：仅说明订阅进程已启动，不能证明机器人发布了 ASR。
- 有 `ASR_RAW:`：收到了消息，但格式与解析规则可能不一致。
- 有 `ASR_TEXT:`：可以继续部署对话系统。
- 说话后完全无新增输出：检查机器人语音服务、固件、麦克风和 `rt/audio_msg`。

我们在另一台新 G1 上遇到过以下真实现象：音量能读取、TTS 返回成功、扬声器能播放，但监听 5 秒麦克风流得到 0 包、0 字节，`rt/audio_msg` 也没有文本。该问题不能通过重启 Python 桥接程序解决。

按 `Ctrl+C` 结束监听。

### 8.2 验证内置 TTS，仅用于诊断

```bash
"$UNITREE_SDK_ROOT/build/bin/g1_voice" "$G1_IFACE" say "语音接口测试"
```

如果输出：

```text
TTS_RET:0
```

只代表请求被音频服务接受，不保证现场一定有声音。实际成功环境中，部分固件的内置中文 TTS 返回 0 但没有声音，所以正式链路使用 Edge TTS 和 PCM WAV。

## 9. 安装 Python 环境

```bash
cd "$HOME/g1_qwen_rag"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

验证：

```bash
python -c "import openai, numpy, sentence_transformers, edge_tts; print('PYTHON_DEPS_OK')"
```

### 9.1 首次联网缓存 BGE 模型

`start_voice.sh` 为稳定运行强制启用 Hugging Face 离线模式。因此第一次正式启动前必须在有互联网时缓存模型：

```bash
cd "$HOME/g1_qwen_rag"
source .venv/bin/activate
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5'); print('BGE_CACHE_OK')"
```

如果这里下载失败，后续启动会在知识库加载阶段退出。

查看缓存：

```bash
du -sh "$HOME/.cache/huggingface" 2>/dev/null || true
```

## 10. 配置千问密钥

在项目根目录创建 `.env`：

```bash
cd "$HOME/g1_qwen_rag"
nano .env
```

内容：

```dotenv
DASHSCOPE_API_KEY=替换为自己的阿里云百炼APIKey
QWEN_MODEL=qwen-turbo
```

保存后限制权限：

```bash
chmod 600 .env
```

检查变量是否被加载，但不要打印完整密钥：

```bash
source .venv/bin/activate
python -c "from dotenv import load_dotenv; import os; load_dotenv('.env'); k=os.getenv('DASHSCOPE_API_KEY',''); print('API_KEY_CONFIGURED', bool(k), 'LENGTH', len(k))"
```

说明：

- `.env` 只负责千问密钥和模型名。
- `G1_IFACE`、`UNITREE_SDK_ROOT` 等机器人参数应在启动 Shell 中导出，或写入 systemd 环境文件。
- 不要把 `.env` 上传到 GitHub。
- 如果密钥曾出现在公开仓库或聊天截图中，应立即去服务商控制台轮换。

建议 `.gitignore` 至少包含：

```gitignore
.env
.venv/
__pycache__/
*.pyc
logs/
runtime_audio/
```

## 11. 配置知识库

`knowledge/` 目录中的每个 `.json` 文件都应为数组：

```json
[
  {
    "question": "宇树G1适合什么场景？",
    "answer": "宇树G1适合科研教学、具身智能、工业验证和服务机器人开发。"
  }
]
```

启动时会读取该目录内全部 JSON 文件，将问题和答案拼接后生成向量。

检查 JSON：

```bash
cd "$HOME/g1_qwen_rag"
source .venv/bin/activate
python -m json.tool knowledge/knowledge.json >/dev/null && echo KNOWLEDGE_JSON_OK
```

单独测试知识库：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -c "from src.knowledge_base import KnowledgeBase; kb=KnowledgeBase('knowledge'); print(kb.search('宇树G1适合什么场景', top_k=2))"
```

预期会输出：

```text
知识库加载完成：... 条
```

本项目实际数据为 133 条。JSON 文件变化后，启动时会重新计算全部向量；当前版本还没有向量持久化缓存。

## 12. 分层验证软件链路

只有每一层都成功，才启动完整服务。

### 12.1 验证千问

```bash
cd "$HOME/g1_qwen_rag"
source .venv/bin/activate
python -c "from src.qwen_client import QwenClient; print(QwenClient().ask('请用一句话介绍宇树G1'))"
```

如果输出包含“我的大脑暂时没响应”，检查：

- `.env` 是否在当前目录。
- API Key 是否有效。
- WiFi 是否能访问互联网。
- 系统时间是否正确。
- 模型名是否可用。

### 12.2 验证 Edge TTS

```bash
cd "$HOME/g1_qwen_rag"
source .venv/bin/activate
edge-tts \
  --voice zh-CN-XiaoxiaoNeural \
  --rate +15% \
  --text "你好，我是宇树机器人" \
  --write-media /tmp/g1_test.mp3

test -s /tmp/g1_test.mp3 && echo EDGE_TTS_OK
```

### 12.3 验证音频转换

```bash
gst-launch-1.0 -q \
  filesrc location=/tmp/g1_test.mp3 \
  ! decodebin \
  ! audioconvert \
  ! audioresample \
  ! audio/x-raw,format=S16LE,rate=16000,channels=1 \
  ! wavenc \
  ! filesink location=/tmp/g1_test.wav

test -s /tmp/g1_test.wav && echo WAV_CONVERT_OK
```

### 12.4 验证机器人 PCM 播放

```bash
"$UNITREE_SDK_ROOT/build/bin/g1_play_wav" \
  "$G1_IFACE" /tmp/g1_test.wav
```

预期看到多条：

```text
PLAY_CHUNK ret=0 ...
```

最后看到：

```text
PLAY_STOP ret=0
```

同时现场应听到机器人播报测试文本。

返回码：

| 退出码 | 含义 |
|---:|---|
| 0 | 播放成功 |
| 2 | 命令参数错误 |
| 3 | WAV 不是 16 kHz/单声道或读取失败 |
| 4 | `PlayStream` 分块发送失败 |
| 5 | `PlayStop` 失败 |

## 13. 启动完整智慧对话

设置现场参数：

```bash
cd "$HOME/g1_qwen_rag"
export UNITREE_SDK_ROOT="$HOME/unitree_sdk2"
export G1_IFACE=enp11s0f1
export G1_HEAR_LOG=/tmp/hear5.log
export EDGE_TTS_BIN="$HOME/g1_qwen_rag/.venv/bin/edge-tts"
chmod +x start_voice.sh
bash start_voice.sh
```

启动成功会显示：

```text
[1/3] 启动机器人语音识别...
[2/3] 启动知识库和千问对话...
[3/3] 状态检查:
  语音识别 OK
  对话服务 OK
```

再次强调：这里的 `OK` 只检查进程存活。首次部署还必须在另一个终端确认 `/tmp/hear5.log` 出现实际 `ASR_TEXT:`。

面对机器人说：

```text
你好，小宇，请介绍一下你自己。
```

进入连续会话后，可直接追问。默认连续会话超时为 120 秒。

暂停：

```text
停止
闭嘴
安静
```

恢复：

```text
继续
小宇
```

彻底停止服务：

- 在启动终端输入 `q`、`quit`、`关闭` 或 `停止` 后回车。
- 或按 `Ctrl+C`。

## 14. 查看运行状态和日志

另开终端：

```bash
pgrep -af 'g1_voice|g1_bridge'
tail -f /tmp/hear5.log
```

另一个终端：

```bash
tail -f /tmp/bridge.log
```

关键日志：

| 日志 | 含义 |
|---|---|
| `ASR_TEXT:` | 机器人产生最终识别文本 |
| `STATE=LISTENING` | 已进入连续会话 |
| `IDLE(ignored)` | 未唤醒时忽略环境语音 |
| `QUERY:` | 本轮提交给知识库和模型的问题 |
| `ANSWER:` | 千问最终回答 |
| `TTS_PCM:` | TTS、转换和播放结果 |
| `PERF_METRIC:` | 本轮结构化性能数据 |
| `STATE=TIMEOUT->IDLE` | 连续会话超时，恢复等待唤醒 |

项目日志：

```text
logs/performance_metrics.csv
logs/performance_metrics.jsonl
```

生成的 MP3 和 WAV 位于 `runtime_audio/`，正常完成或失败退出后会自动删除。

## 15. 对话行为和参数

当前关键参数位于 `g1_bridge.py` 和 `src/qwen_client.py`：

```text
模型：qwen-turbo
max_tokens：80
回答：最多一句话、40个汉字以内
知识库 top_k：2
历史：最近3轮
连续会话超时：120秒
机器人说完后的静默保护：2秒
```

状态机：

```text
idle      等待唤醒词
listening 已唤醒，可连续追问
paused    收到停止词，不处理普通语音
```

生产现场建议再增加：

- 固定最大连续轮数。
- 会话绝对时限。
- VAD。
- ASR 置信度门限。
- 误唤醒和环境误触发统计。
- 播放期间回声抑制。

## 16. 性能测试

### 16.1 固定 10 轮测试

保持完整服务运行，在另一个终端执行：

```bash
cd "$HOME/g1_qwen_rag"
source .venv/bin/activate
python run_synthetic_benchmark.py
python benchmark_report.py
```

固定问题脚本会把 `ASR_TEXT:` 写入 `/tmp/hear5.log`，因此它绕过了真实麦克风和机器人 ASR，但仍会真实执行：

```text
唤醒/会话状态机
→ 知识库
→ 千问
→ Edge TTS
→ GStreamer
→ 机器人完整播放
```

它适合比较模型、Prompt、回答长度和 TTS 优化，不适合评估识别准确率和真实 ASR 耗时。

输出：

```text
logs/performance_metrics.csv
logs/performance_metrics.jsonl
logs/performance_summary.md
logs/synthetic_run.log
```

### 16.2 真人 ASR 时间标记

在另一个终端运行：

```bash
cd "$HOME/g1_qwen_rag"
source .venv/bin/activate
python mark_asr_end.py
```

按提示开始说问题，说完最后一个字时立即按回车。程序会写入：

```text
/tmp/g1_asr_end_ms
```

下一条 ASR 结果到达时，桥接程序会计算人工估算的 ASR 耗时。

该方法受人工按键误差影响。正式产品应使用 VAD 结束事件或麦克风帧时间戳。

### 16.3 指标定义

- `kb_ms`：本地知识库检索。
- `llm_ms`：发送千问请求到收到完整文本。
- `tts_synth_ms`：Edge TTS 生成 MP3。
- `audio_convert_ms`：MP3 转 PCM WAV。
- `audio_first_chunk_ms`：启动播放进程到首个 `PLAY_CHUNK`。
- `first_response_ms`：收到 ASR 最终文本到首个音频块发送。
- `round_total_ms`：收到 ASR 最终文本到完整播放程序结束。
- `manual_asr_ms`：人工标记说话结束到收到 ASR 文本。

真正的口到耳首响可近似为：

```text
ASR耗时 + 系统首响
```

## 17. systemd 开机自启（可选）

建议先完成手工启动和至少 10 轮稳定性测试，再配置开机自启。

### 17.1 修改服务模板

模板默认使用：

```text
User=zzl
WorkingDirectory=/home/zzl/g1_qwen_rag
UNITREE_SDK_ROOT=/home/zzl/unitree_sdk2
```

换电脑后必须改成实际用户名和路径。

将环境模板复制到系统目录：

```bash
sudo cp systemd/g1-dialogue.env.example /etc/g1-dialogue.env
sudo nano /etc/g1-dialogue.env
```

示例：

```dotenv
G1_IFACE=enp11s0f1
UNITREE_SDK_ROOT=/home/你的用户名/unitree_sdk2
G1_HEAR_LOG=/tmp/hear5.log
EDGE_TTS_BIN=/home/你的用户名/g1_qwen_rag/.venv/bin/edge-tts
```

编辑两个 service 文件，将用户和路径替换为实际值，再安装：

```bash
sudo cp systemd/g1-voice.service /etc/systemd/system/
sudo cp systemd/g1-dialogue.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now g1-voice.service g1-dialogue.service
```

检查：

```bash
systemctl status g1-voice.service g1-dialogue.service --no-pager
journalctl -u g1-voice.service -n 100 --no-pager
journalctl -u g1-dialogue.service -n 100 --no-pager
```

停止和取消自启：

```bash
sudo systemctl disable --now g1-dialogue.service g1-voice.service
```

## 18. 真实问题与排查顺序

### 18.1 启动显示 OK，但机器人不回答

按顺序检查：

```bash
pgrep -af 'g1_voice|g1_bridge'
tail -n 100 /tmp/hear5.log
tail -n 100 /tmp/bridge.log
```

判断：

1. `/tmp/hear5.log` 没有 `LISTENING`：监听程序启动失败。
2. 有 `LISTENING`，说话后没有 `ASR_TEXT`：机器人没有发布 ASR，先检查机器人侧。
3. 有 `ASR_TEXT`，没有 `QUERY`：唤醒词、状态机或日志格式问题。
4. 有 `QUERY`，回答为“大脑暂时没响应”：千问网络、密钥或超时问题。
5. 有 `ANSWER`，没有 `TTS_PCM`：Edge TTS 或 GStreamer 问题。
6. 有 `PLAY_CHUNK ret` 非 0：机器人播放接口或 DDS 通信问题。

### 18.2 ASR 进程存活，但没有数据

这是在新机器人上真实遇到的问题。不要仅依赖：

```bash
kill -0 <pid>
```

正确健康检查应同时满足：

```text
监听进程存活
+ 最近一段时间收到实际音频/ASR事件
+ ASR_TEXT格式可以解析
```

可能原因：

- 新机器人未启动 ASR 服务。
- 固件版本不提供 `rt/audio_msg`。
- 麦克风采集服务或音频容器未启动。
- DDS Domain、网卡或组播路径不同。
- 语音功能需要额外授权或 App 设置。

### 18.3 内置中文 TTS 静音

现象：

```text
TTS_RET:0
```

但现场没有声音。

解决：使用 Edge TTS 生成 MP3，GStreamer 转为 16 kHz 单声道 PCM WAV，再通过 `g1_play_wav` 播放。

### 18.4 知识库加载失败

检查：

```bash
ls -lah "$HOME/.cache/huggingface"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5'); print('OK')"
```

如果离线加载失败，重新联网完成第 9.1 节的缓存步骤。

### 18.5 环境人声被当作连续追问

固定测试结束后，现场环境声音曾产生 3 条非测试 ASR 结果。它们没有计入正式 10 轮数据，但说明连续会话窗口会放大环境误触发。

临时处理：

- 停止并重新启动桥接服务，使状态回到 `idle`。
- 或等待 120 秒自动回到 `idle`。

长期处理：

- 增加 VAD 和 ASR 置信度。
- 设置最大连续轮数和绝对会话时限。
- 播放期间抑制机器人自身回声。
- 单独统计误唤醒率和环境误触发率。

### 18.6 有线网络正常但外网失败

检查：

```bash
ip route
ping -c 3 192.168.123.161
ping -c 3 223.5.5.5
```

如果默认路由走机器人有线网卡，删除有线默认网关，并设置 NetworkManager 的 `ipv4.never-default yes`。

### 18.7 多套进程互相干扰

```bash
pgrep -af 'g1_voice|g1_bridge'
```

正常情况下只应有一套监听和一套桥接程序。`start_voice.sh` 会清理旧进程，但 systemd 与手工启动不要同时使用。

## 19. 更换到另一台 G1 的检查清单

不要假设同型号机器人具备相同语音能力。换机器人时先执行：

1. 记录机器人型号、自由度和固件版本。
2. 确认有线网卡和 DDS 组播正常。
3. 单独运行 `g1_voice <iface> hear`。
4. 必须实际看到 `ASR_TEXT:`。
5. 单独测试 PCM WAV 播放。
6. 再测试千问和 Edge TTS。
7. 最后启动完整桥接程序。
8. 先跑 10 轮固定问题，再进行真人语音测试。

如果新机器人能播放但不能识别，不要修改 RAG 或模型代码，应检查机器人侧音频、ASR、容器和固件服务。

## 20. 安全和敏感信息

- 该项目默认只进行语音交互，主流程不主动执行肢体动作。
- 如果启用动作接口，必须保持安全距离并确保急停可用。
- 不要同时运行多个底层控制程序。
- 不要把 `.env`、API Key、SSH 密码、设备密码或生产日志提交到仓库。
- 分享日志前删除用户问题、设备标识和密钥。
- API Key 泄露后立即轮换，不要只删除文件。
- 不要把机器人内网设置为互联网默认路由。
- 长时间运行前先完成异常停止和进程清理测试。

## 21. 部署验收标准

从零部署完成后，至少满足：

- [ ] 有线网卡连接 G1，WiFi 保持互联网访问。
- [ ] `unitree_sdk2` 编译成功。
- [ ] `g1_voice` 和 `g1_play_wav` 已生成。
- [ ] 说话后能看到真实 `ASR_TEXT:`。
- [ ] 千问单独调用成功。
- [ ] BGE 模型可以离线加载。
- [ ] Edge TTS 可以生成 MP3。
- [ ] GStreamer 可以生成正确 WAV。
- [ ] G1 可以播放测试 WAV。
- [ ] `start_voice.sh` 启动后可用唤醒词进入会话。
- [ ] 连续追问正常，超时后回到 `idle`。
- [ ] 10 轮固定测试全部完成。
- [ ] CSV、JSONL 和汇总报告正常生成。
- [ ] 服务停止后不残留监听或桥接进程。
- [ ] `.env` 未提交到 Git。

## 22. 后续优化

1. 增加机器人音频流和 ASR Topic 的真实健康检查。
2. 使用 VAD 准确记录说话结束时间。
3. 将知识库向量持久化，缩短启动时间。
4. 引入流式大模型和流式 TTS，降低首响。
5. 增加 50 至 100 轮连续稳定性测试。
6. 增加网络断开、模型超时、TTS失败和播放失败的异常注入测试。
7. 增加误唤醒、环境误触发和机器人回声统计。
8. 将机器人相关逻辑抽象为 Adapter，方便迁移到其他机器人平台。

## 23. 许可与责任

本仓库中的自定义代码用于项目验证和二次开发参考。`unitree_sdk2` 及机器人固件遵循其各自许可和厂商要求。部署到真实机器人前，应核对所用 SDK 版本、固件能力和现场安全规范。

