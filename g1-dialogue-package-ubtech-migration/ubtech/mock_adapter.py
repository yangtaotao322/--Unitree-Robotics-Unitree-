"""Deterministic UBTECH adapter used for local integration tests."""

import time
import uuid
from typing import Any, Dict, Optional

from src.robot_adapter import PlaybackResult, RobotAdapter


class MockUbtechAdapter(RobotAdapter):
    def __init__(self, request_delay: float = 0.005, playback_delay: float = 0.01):
        self.request_delay = request_delay
        self.playback_delay = playback_delay
        self.spoken_texts = []
        self.actions = []

    def health_check(self) -> Dict[str, Any]:
        return {
            "authorized": True,
            "ready": True,
            "current_mode": "MOCK",
            "simulated": True,
        }

    def _result(self, request_type: str, wait: bool) -> PlaybackResult:
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        time.sleep(self.request_delay)
        request_ms = (time.perf_counter() - started) * 1000
        if wait:
            time.sleep(self.playback_delay)
        playback_ms = (time.perf_counter() - started) * 1000 if wait else None
        return PlaybackResult(
            request_id=request_id,
            request_type=request_type,
            accepted=True,
            completed=wait,
            success=True,
            request_ms=request_ms,
            first_event_ms=request_ms if wait else None,
            playback_ms=playback_ms,
            message="mock playback completed" if wait else "mock request accepted",
            raw_response={"ok": True, "data": {"uuid": request_id, "accepted": True}},
            raw_event=(
                {
                    "ok": True,
                    "data": {
                        "uuid": request_id,
                        "request_type": request_type,
                        "phase": "result",
                        "success": True,
                        "code": 0,
                    },
                }
                if wait
                else {}
            ),
        )

    def speak(
        self,
        text: str,
        action: str = "",
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> PlaybackResult:
        if not text.strip():
            raise ValueError("text must not be empty")
        self.spoken_texts.append({"text": text.strip(), "action": action})
        return self._result("play_text", wait)

    def play_action(
        self,
        action: str,
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> PlaybackResult:
        if not action.strip():
            raise ValueError("action must not be empty")
        self.actions.append(action.strip())
        return self._result("play_action", wait)

    def interrupt(self) -> Dict[str, Any]:
        return {"ok": True, "code": "OK", "message": "mock interrupted", "data": {}}

    def get_motion_info_list(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "code": "OK",
            "message": "mock motion list",
            "data": {"motion_info_list": []},
        }
