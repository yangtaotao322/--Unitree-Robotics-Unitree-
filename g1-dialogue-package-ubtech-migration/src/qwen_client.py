import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv(".env")


class QwenClient:
    def __init__(self, system_identity=None):
        self.client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=10.0,
        )
        self.model = os.getenv("QWEN_MODEL", "qwen-turbo")
        self.system_identity = (
            system_identity
            or os.getenv("ROBOT_ASSISTANT_IDENTITY")
            or "宇树G1机器人上的智能语音助手"
        )

    def ask(self, question, context="", history=None):
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"你是{self.system_identity}。优先依据知识库回答；"
                        "知识库没有时使用通用知识。直接给结论，只用自然中文口语，"
                        "不要Markdown、表情、项目符号或舞台描述。最多一句话，"
                        "控制在40个汉字以内。"
                        + (("\n知识库参考：\n" + context) if context else "")
                    ),
                }
            ]
            messages.extend(history or [])
            messages.append({"role": "user", "content": question})
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=10.0,
                max_tokens=80,
            )
            return response.choices[0].message.content
        except Exception as exc:
            return "抱歉，我的大脑暂时没响应，请稍后再试（%s）。" % type(exc).__name__
