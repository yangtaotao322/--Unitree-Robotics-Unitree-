import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.dialogue_core import DialogueCore
from ubtech.mock_adapter import MockUbtechAdapter
from ubtech.ubtech_adapter import UbtechCredentials, _event_data, _parse_json_message


class FakeKnowledgeBase:
    def search(self, question, top_k=2):
        return [{"answer": "知识答案"}] * top_k


class FakeLlmClient:
    def __init__(self):
        self.history_lengths = []

    def ask(self, question, context="", history=None):
        self.history_lengths.append(len(history or []))
        return "测试回答"


class UbtechMigrationTests(unittest.TestCase):
    def test_json_envelope_and_event_data(self):
        envelope = _parse_json_message(
            '{"ok":true,"code":"OK","data":{"phase":"result","success":true}}'
        )
        self.assertTrue(envelope["ok"])
        self.assertEqual(_event_data(envelope)["phase"], "result")

    def test_credentials_do_not_require_device_id(self):
        credentials = UbtechCredentials("app", "key", "secret", "license")
        request = credentials.as_request()
        self.assertNotIn("device_id", request)
        self.assertEqual(request["license"], "license")

    def test_dialogue_history_is_limited_to_three_rounds(self):
        llm = FakeLlmClient()
        core = DialogueCore(FakeKnowledgeBase(), llm, max_history_rounds=3)
        for index in range(5):
            core.ask("问题%d" % index)
        self.assertEqual(len(core.history), 6)
        self.assertEqual(llm.history_lengths, [0, 2, 4, 6, 6])

    def test_mock_text_playback_reaches_final_result(self):
        adapter = MockUbtechAdapter(request_delay=0, playback_delay=0)
        result = adapter.speak("你好", wait=True)
        self.assertTrue(result.accepted)
        self.assertTrue(result.completed)
        self.assertTrue(result.success)
        self.assertEqual(result.raw_event["data"]["phase"], "result")

    def test_mock_action_accept_only_is_not_completed(self):
        adapter = MockUbtechAdapter(request_delay=0, playback_delay=0)
        result = adapter.play_action("A029", wait=False)
        self.assertTrue(result.accepted)
        self.assertFalse(result.completed)


if __name__ == "__main__":
    unittest.main()

