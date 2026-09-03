import json
import os
import numpy as np
from sentence_transformers import SentenceTransformer
class KnowledgeBase:
    def __init__(self, file_path):
        self.data = []
        self.model = SentenceTransformer("BAAI/bge-small-zh-v1.5", device="cpu")
        files = []
        if os.path.isdir(file_path):
            for f in os.listdir(file_path):
                if f.endswith(".json"):
                    files.append(os.path.join(file_path, f))
        else:
            files.append(file_path)
        for file in files:
            try:
                with open(file, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, list):
                        self.data.extend(content)
            except Exception as e:
                print("读取失败:", file, e)
        self.texts = [
            item.get("question", "") + " " + item.get("answer", "")
            for item in self.data
        ]
        if self.texts:
            self.embeddings = self.model.encode(
                self.texts,
                normalize_embeddings=True,
                convert_to_numpy=True
            )
        else:
            self.embeddings = np.empty((0, 0))
        print(f"知识库加载完成：{len(self.data)} 条")
    def search(self, query, top_k=3):
        if not self.data:
            return []
        query_embedding = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True
        )[0]
        scores = np.dot(self.embeddings, query_embedding)
        indexes = np.argsort(scores)[::-1][:top_k]
        results = []
        for i in indexes:
            item = dict(self.data[i])
            item["score"] = float(scores[i])
            results.append(item)
        return results
