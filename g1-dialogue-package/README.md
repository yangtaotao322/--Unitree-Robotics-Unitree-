# 宇树 G1 智慧语音对话系统

这套代码实现了从机器人语音识别到大模型回答、知识库增强、中文语音合成、机器人扬声器播放，以及性能测试和异常统计的完整链路。

## 1. 工作流程

```text
用户说话
  ↓
G1 麦克风与固件 ASR
  ↓ rt/audio_msg
g1_voice.cpp 提取最终识别文本
  ↓ /tmp/hear5.log
g1_bridge.py 唤醒词与会话状态机
  ↓
knowledge_base.py 向量检索本地知识
  ↓
qwen_client.py 调用千问模型
  ↓
Edge TTS 合成 MP3
  ↓
GStreamer 转为 16 kHz/单声道/16 bit PCM WAV
  ↓
g1_play_wav.cpp 通过 Unitree PlayStream 播放
  ↓
机器人说出回答，并写入逐轮性能指标
```

## 2. 代码目录

```text
g1-smart-dialogue/
├─ g1_bridge.py                 # 主程序：状态机、RAG、TTS、播放和性能埋点
├─ start_voice.sh               # 一键启动/停止
├─ src/
│  ├─ qwen_client.py            # 千问兼容 OpenAI API 调用
│  └─ knowledge_base.py         # BGE 中文向量知识库
├─ knowledge/                   # JSON 格式知识库
├─ voice/
│  ├─ g1_voice.cpp              # 订阅 G1 ASR 消息
│  ├─ g1_play_wav.cpp           # PCM WAV 流式发送给 G1
│  └─ CMakeLists.snippet.txt    # Unitree SDK 编译目标
├─ run_synthetic_benchmark.py   # 固定10轮自动测试
├─ benchmark_report.py          # 汇总平均值/P50/P95/异常率
├─ mark_asr_end.py              # 人工记录说话结束时刻
├─ systemd/                     # 开机自启服务模板
├─ docs/optimization-results.md # 优化前后数据
├─ requirements.txt
└─ .env.example
```

## 3. 硬件和网络

建议使用双网卡：

- 有线网卡连接机器人内网，例如 `enp11s0f1 -> 192.168.123.18/24`。
- WiFi 负责互联网，用于调用千问和 Edge TTS。
- 不要给机器人有线网卡配置默认路由，默认路由应走 WiFi。

检查：

```bash
ip -br address
ip route
ping -c 3 192.168.123.161
ping -c 3 192.168.123.164
```

实际机器人地址可能不同，以现场网络为准。

## 4. 安装 Unitree SDK2

先按照宇树官方说明安装并编译 `unitree_sdk2`。假设目录为：

```text
/home/zzl/unitree_sdk2
```

把本项目中的两个 C++ 文件复制到 SDK：

```bash
cp voice/g1_voice.cpp /home/zzl/unitree_sdk2/example/g1/voice/
cp voice/g1_play_wav.cpp /home/zzl/unitree_sdk2/example/g1/voice/
```

将 `voice/CMakeLists.snippet.txt` 的内容加入：

```text
/home/zzl/unitree_sdk2/example/g1/CMakeLists.txt
```

重新编译：

```bash
cd /home/zzl/unitree_sdk2
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

确认生成：

```bash
ls -l build/bin/g1_voice build/bin/g1_play_wav
```

## 5. 安装 Python 和音频依赖

Ubuntu 示例：

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip gstreamer1.0-tools \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly
```

创建虚拟环境：

```bash
cd /home/zzl/g1_qwen_rag
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

首次运行 `sentence-transformers` 时需要下载 `BAAI/bge-small-zh-v1.5`。下载完成后可设置离线模式运行。

## 6. 配置模型和运行参数

复制配置模板：

```bash
cp .env.example .env
chmod 600 .env
```

填写自己的密钥：

```dotenv
DASHSCOPE_API_KEY=your_dashscope_api_key_here
QWEN_MODEL=qwen-turbo
G1_IFACE=enp11s0f1
UNITREE_SDK_ROOT=/home/zzl/unitree_sdk2
G1_HEAR_LOG=/tmp/hear5.log
EDGE_TTS_BIN=/home/zzl/g1_qwen_rag/.venv/bin/edge-tts
```

不要把 `.env` 提交到 Git，也不要在代码、配置文件或聊天记录中保存真实密钥。

## 7. 知识库格式

`knowledge/` 下的每个 JSON 文件是数组：

```json
[
  {
    "question": "宇树G1适合什么场景？",
    "answer": "宇树G1适合科研教学、具身智能、工业验证和服务机器人开发。"
  }
]
```

启动时会读取目录内所有 `.json` 文件，使用 `BAAI/bge-small-zh-v1.5` 生成向量并进行余弦相似度检索。

## 8. 启动机器人对话

```bash
cd /home/zzl/g1_qwen_rag
chmod +x start_voice.sh
bash start_voice.sh
```

启动成功后说：

```text
你好，小宇，请介绍一下你自己。
```

唤醒后可以连续追问。停止服务可在启动终端输入 `q`，或按 `Ctrl+C`。

查看日志：

```bash
tail -f /tmp/hear5.log
tail -f /tmp/bridge.log
```

## 9. 单独验证每一层

### 9.1 验证 ASR

```bash
/home/zzl/unitree_sdk2/build/bin/g1_voice enp11s0f1 hear
```

说话后应看到：

```text
ASR_TEXT:你好，小宇
```

### 9.2 验证千问

```bash
source .venv/bin/activate
python -c "from src.qwen_client import QwenClient; print(QwenClient().ask('你好'))"
```

### 9.3 验证 Edge TTS 与转换

```bash
edge-tts --voice zh-CN-XiaoxiaoNeural --text "你好，我是宇树机器人" --write-media /tmp/test.mp3
gst-launch-1.0 -q filesrc location=/tmp/test.mp3 ! decodebin ! audioconvert ! \
  audioresample ! audio/x-raw,format=S16LE,rate=16000,channels=1 ! wavenc ! \
  filesink location=/tmp/test.wav
```

### 9.4 验证机器人播放

```bash
/home/zzl/unitree_sdk2/build/bin/g1_play_wav enp11s0f1 /tmp/test.wav
```

## 10. 性能测试

启动正式服务后，在另一个终端运行：

```bash
source .venv/bin/activate
python run_synthetic_benchmark.py
python benchmark_report.py
```

输出文件：

```text
logs/performance_metrics.csv
logs/performance_metrics.jsonl
logs/performance_summary.md
```

记录指标包括：

- 知识库检索耗时
- 模型响应耗时
- TTS合成耗时
- 音频转换耗时
- 播放调用到首个音频包耗时
- ASR最终文本到音频首包的系统首响
- 整轮播放完成时间
- 成功率、异常阶段、异常类型和连续成功轮数

当前 G1 ASR 只输出最终文本，没有提供准确的用户说话结束事件。因此真正的口到耳首响应需要额外采集语音结束时间。`mark_asr_end.py` 提供人工标记方式，但正式项目建议接入 VAD 或音频帧时间戳。

## 11. systemd 开机自启（可选）

先确认服务文件中的用户和项目路径符合现场环境：

```bash
sudo cp systemd/g1-dialogue.env.example /etc/g1-dialogue.env
sudo cp systemd/g1-voice.service /etc/systemd/system/
sudo cp systemd/g1-dialogue.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now g1-voice.service g1-dialogue.service
```

检查：

```bash
systemctl status g1-voice.service g1-dialogue.service
journalctl -u g1-dialogue.service -f
```

API Key 仍保存在项目目录的 `.env`，权限应设置为 `600`。

## 12. 已实施的首轮优化

- `qwen-plus` 切换为低延迟的 `qwen-turbo`。
- 回答限制为一句话、40个汉字以内。
- 对话历史从5轮减少为3轮。
- 知识库候选从3条减少为2条。
- TTS语速从 `+5%` 调整为 `+15%`。

固定10轮测试结果：

- 模型响应：1151 ms -> 524 ms，提升54.5%。
- 系统首响：3517 ms -> 2683 ms，提升23.7%。
- 整轮完成：14627 ms -> 8788 ms，提升39.9%。
- 优化前后均为10/10成功，异常率0%。

详细结果见 `docs/optimization-results.md`。

## 13. 常见问题

### 机器人不回答

```bash
pgrep -af 'g1_voice|g1_bridge'
tail -n 100 /tmp/hear5.log
tail -n 100 /tmp/bridge.log
```

确认只有一套 ASR 和桥接进程，机器人内网接口名称正确，外网可以访问模型和 TTS。

### 中文 TTS 返回成功但没有声音

部分固件内置中文 TTS 可能静音。本项目不依赖内置中文 TTS，而是使用 Edge TTS + PCM WAV + PlayStream。

### 测试后误响应环境人声

连续对话窗口内，环境语音可能被当作追问。可重启桥接进程恢复等待唤醒；生产版本建议增加 ASR 置信度、VAD、固定会话上限和误唤醒统计。

### 首次启动知识库较慢

BGE模型需要加载并计算知识库向量。可以在后续版本中将知识向量持久化，启动时直接读取缓存。

## 14. 后续优化方向

1. 使用流式大模型和流式 TTS，在首句生成后立即播放。
2. 引入 VAD，准确记录用户说话结束时间和 ASR耗时。
3. 缓存知识库向量，缩短启动时间。
4. 增加50至100轮稳定性和异常注入测试。
5. 增加误唤醒率、误识别率、模型超时率和TTS失败率。
6. 为连续对话增加最大轮数或绝对会话时限。

## 15. 安全说明

- 不要在仓库中保存 `.env`、API Key、SSH密码或生产日志。
- 如果密钥曾以明文写入配置文件，应立即在服务商控制台轮换。
- 机器人动作与音频测试应在安全区域进行，确保急停可用。
