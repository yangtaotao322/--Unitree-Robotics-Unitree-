# 优必选机器人智慧对话迁移与上机闭环指南

## 1. 当前实现范围

本项目已把宇树 G1 上层能力拆成公共对话核心和机器人适配层：

```text
输入文字
  -> BGE 知识库检索
  -> Qwen 生成短回答
  -> UbtechRos2Adapter.play_text
  -> /robo/audio/call/play_text
  -> /robo/media/subscribe/playback_state
  -> phase=result 后判定本轮完成
```

已完成软件层实现和本地模拟测试。真实鉴权、真实播报、动作执行、音频输入及 ASR 耗时必须在优必选实体机器人接入后验证。

## 2. 为什么必须等待 playback_state

`play_text` 和 `play_action` 的同步响应只代表请求被机器人受理，不能作为播放成功依据。本适配层在发起请求前创建可靠 QoS 的 `playback_state` 订阅，并使用请求 `uuid` 匹配事件。只有收到：

```json
{
  "data": {
    "uuid": "与请求一致",
    "request_type": "play_text",
    "phase": "result",
    "code": 0,
    "success": true
  }
}
```

才将本轮标记为 `completed=true`、`success=true`。超时、最终 `success=false` 或服务拒绝都会计入失败。

## 3. 文件说明

- `src/dialogue_core.py`：与机器人无关的知识检索、Qwen 调用和三轮上下文。
- `src/robot_adapter.py`：统一的机器人播报/动作接口及结果数据结构。
- `ubtech/ubtech_adapter.py`：优必选 ROS2 鉴权、状态、播报、动作、音频流及完成事件适配。
- `ubtech/mock_adapter.py`：无实体机器人时的软件闭环模拟器。
- `ubtech_dialogue.py`：状态检查、鉴权、直接播报、动作测试和连续问答入口。
- `run_ubtech_mock_smoke.py`：十轮软件闭环冒烟测试。
- `.env.ubtech.example`：不含真实凭证的配置模板。
- `start_ubtech.sh`：优必选开发容器内的启动脚本。

## 4. 上机前准备

1. 开发电脑使用 Ubuntu，设置有线地址为 `192.168.11.99/24`。
2. 优必选 Walker Orin 文档默认有线地址为 `192.168.11.3`。
3. 向项目负责人或厂商取得本机对应的 `appid`、`api_key`、`api_secret`、`device_id` 和 License 文件。
4. 不要把真实鉴权数据发到群聊、日志或 GitHub。
5. 在机器人侧启动并进入官方 Demo 容器：

```bash
udoke up -c demo_runtime
udoke exec -c demo_runtime
source /opt/ros/humble/setup.bash
```

6. 确认 ROS2 环境：

```bash
export ROS_DOMAIN_ID=20
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 service list | grep '^/robo/'
ros2 topic list | grep '^/robo/'
```

若看不到 `/robo/` 服务，不要继续测试大模型；应先处理容器、ROS Domain、RMW 或厂商服务状态。

## 5. 安装项目

在 `demo_runtime` 容器中进入项目目录，然后执行：

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
chmod +x start_ubtech.sh
```

必须使用 `--system-site-packages`，否则虚拟环境可能看不到容器中的 `rclpy` 和 `robo_sdk` 消息类型。

首次联网缓存 BGE：

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"
```

## 6. 配置文件

```bash
cp .env.example .env
cp .env.ubtech.example .env.ubtech
chmod 600 .env .env.ubtech
```

在 `.env` 中填写 Qwen Key；在 `.env.ubtech` 中填写优必选鉴权参数和 License 文件路径。不得把 License 全文直接写进终端历史，优先使用 `UBTECH_LICENSE_FILE`。

## 7. 分层闭环步骤

### 7.1 鉴权和 ready 状态

首次鉴权：

```bash
bash start_ubtech.sh --authorize --check
```

以后只检查状态：

```bash
bash start_ubtech.sh --check
```

合格输出必须同时满足：

```text
authorized=true
ready=true
```

### 7.2 直接文本播报

```bash
bash start_ubtech.sh --say "语音系统连接测试"
```

验收不能只看服务返回，必须看到：

```text
accepted=true
completed=true
success=true
```

并由现场人员确认机器人确实出声。

### 7.3 动作列表和单动作

```bash
bash start_ubtech.sh --list-actions
bash start_ubtech.sh --play-action A029
```

动作编号必须来自当前机器人的动作列表，不能直接假定示例 `A029` 在所有固件中都存在。

### 7.4 单轮智慧问答

```bash
bash start_ubtech.sh --ask "请介绍一下你自己"
```

该命令实际经过知识库、Qwen、`play_text`和`playback_state`。指标写入：

```text
logs/ubtech_performance_metrics.csv
```

### 7.5 连续文字问答

```bash
bash start_ubtech.sh --interactive
```

连续完成十轮固定问题，检查三轮上下文、播放完成事件和异常率。

## 8. 指标解释

- `kb_ms`：知识库检索时间。
- `llm_ms`：Qwen 完整回答时间。
- `play_request_ms`：发出 `play_text` 到服务返回“已受理”的时间。
- `playback_first_event_ms`：发出播报请求到收到第一个播放状态事件的时间。
- `text_input_to_first_event_ms`：文字输入到第一个播放状态事件的时间。
- `playback_complete_ms`：发出播报请求到收到 `phase=result` 的时间。
- `round_total_ms`：文字输入到本轮最终完成的总时间。

注意：`playback_first_event_ms`不是麦克风意义上的“声音首响”。真实声学首响仍需录音或机器人侧音频开始事件测量，不能用服务受理时间代替。

## 9. 本地验证

不连接机器人时执行：

```bash
python -m unittest discover -s tests -v
python run_ubtech_mock_smoke.py
python ubtech_dialogue.py --mock --check
python ubtech_dialogue.py --mock --say "模拟播报测试"
```

模拟结果只能证明代码编排、状态判定、历史裁剪和异常出口正常，不能作为机器人性能数据。

## 10. 实体机验收标准

1. 鉴权和 ready 检查通过。
2. 直接文本播报 3/3 成功，现场实际听到声音。
3. 动作执行 3/3 成功，`uuid`与最终事件一致。
4. 固定问答 10/10 完成，异常率为 0%。
5. 服务返回成功但无最终事件必须记为失败。
6. 断网、错误动作编号和播报打断各验证一次，日志能定位到具体阶段。
7. 在接入音频流和 ASR 后，单独测量 ASR、LLM、TTS/播报、首响和整轮耗时。

## 11. 尚未闭环部分

1. 实体优必选机器人未接入时，无法验证真实 SDK 服务、鉴权凭证和 License。
2. 音频流使用共享内存，必须读取 `stream_state` 返回的实际配置后再开发 reader。
3. SDK文档未给出直接 ASR 文本接口，语音闭环预计需要自建 ASR。
4. `play_text`接口由机器人内部完成播报，目前不假定支持外部 Edge TTS 音频注入。

