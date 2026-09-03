"""ROS2 adapter for the UBTECH Walker SDK.

The imports that only exist in the robot's ``demo_runtime`` container are
loaded lazily, so this module can still be unit-tested on a normal PC.
"""

import json
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple

from src.robot_adapter import PlaybackResult, RobotAdapter


AUTH_SERVICE = "/robo/auth/call/authorize"
AUTH_STATE_SERVICE = "/robo/auth/call/auth_state"
READY_STATE_SERVICE = "/robo/system/call/get_ready_state"
PLAY_TEXT_SERVICE = "/robo/audio/call/play_text"
PLAY_ACTION_SERVICE = "/robo/audio/call/play_action"
INTERRUPT_SERVICE = "/robo/audio/call/interrupt_action_audio"
MOTION_LIST_SERVICE = "/robo/audio/call/get_motion_info_list"
AUDIO_OPEN_SERVICE = "/robo/audio/call/open_stream"
AUDIO_STATE_SERVICE = "/robo/audio/call/stream_state"
AUDIO_CLOSE_SERVICE = "/robo/audio/call/close_stream"
PLAYBACK_TOPIC = "/robo/media/subscribe/playback_state"


class UbtechDependencyError(RuntimeError):
    pass


class UbtechServiceError(RuntimeError):
    def __init__(self, service: str, message: str, payload: Optional[dict] = None):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.payload = payload or {}


def _parse_json_message(value: Any) -> Dict[str, Any]:
    """Parse an SDK JSON envelope without ever using ``eval``."""

    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    text = str(value).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except json.JSONDecodeError as exc:
        raise ValueError(f"SDK returned non-JSON data: {text[:160]}") from exc


def _event_data(envelope: Dict[str, Any]) -> Dict[str, Any]:
    data = envelope.get("data")
    return data if isinstance(data, dict) else envelope


@dataclass(frozen=True)
class UbtechCredentials:
    appid: str
    api_key: str
    api_secret: str
    license_text: str
    device_id: str = ""

    @classmethod
    def from_env(cls) -> "UbtechCredentials":
        license_file = os.getenv("UBTECH_LICENSE_FILE", "").strip()
        license_text = os.getenv("UBTECH_LICENSE_TEXT", "").strip()
        if license_file:
            path = Path(license_file).expanduser()
            if not path.is_file():
                raise ValueError(f"UBTECH_LICENSE_FILE does not exist: {path}")
            license_text = path.read_text(encoding="utf-8").strip()

        values = {
            "appid": os.getenv("UBTECH_APPID", "").strip(),
            "api_key": os.getenv("UBTECH_API_KEY", "").strip(),
            "api_secret": os.getenv("UBTECH_API_SECRET", "").strip(),
            "license_text": license_text,
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError("missing UBTECH credentials: " + ", ".join(missing))
        return cls(
            **values,
            device_id=os.getenv("UBTECH_DEVICE_ID", "").strip(),
        )

    def as_request(self) -> Dict[str, Any]:
        request = {
            "appid": self.appid,
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "license": self.license_text,
        }
        if self.device_id:
            request["device_id"] = self.device_id
        return request


class UbtechRos2Adapter(RobotAdapter):
    """Use UBTECH's ROS2 services and playback-state topic."""

    def __init__(
        self,
        node_name: str = "smart_dialogue_ubtech_adapter",
        service_timeout: Optional[float] = None,
        playback_timeout: Optional[float] = None,
    ) -> None:
        os.environ.setdefault("ROS_DOMAIN_ID", "20")
        os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp")
        self.service_timeout = service_timeout or float(
            os.getenv("UBTECH_SERVICE_TIMEOUT", "3")
        )
        self.playback_timeout = playback_timeout or float(
            os.getenv("UBTECH_PLAYBACK_TIMEOUT", "45")
        )
        try:
            import rclpy
            from robo_sdk.srv import StringCall
            from std_msgs.msg import String
            from std_srvs.srv import Trigger
            from rclpy.qos import QoSProfile, ReliabilityPolicy
        except ImportError as exc:
            raise UbtechDependencyError(
                "UBTECH ROS2 dependencies are unavailable. Run inside demo_runtime "
                "after: source /opt/ros/humble/setup.bash"
            ) from exc

        self._rclpy = rclpy
        self._StringCall = StringCall
        self._Trigger = Trigger
        self._owns_rclpy = not rclpy.ok()
        if self._owns_rclpy:
            rclpy.init(args=None)
        self.node = rclpy.create_node(node_name)
        self._events: Deque[Tuple[float, Dict[str, Any]]] = deque()
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self._playback_subscription = self.node.create_subscription(
            String, PLAYBACK_TOPIC, self._on_playback, qos
        )
        self._clients: Dict[Tuple[str, Any], Any] = {}

    def _on_playback(self, message: Any) -> None:
        try:
            envelope = _parse_json_message(message.data)
        except ValueError as exc:
            envelope = {"ok": False, "code": "INVALID_EVENT", "message": str(exc)}
        self._events.append((time.perf_counter(), envelope))

    def _client(self, service: str, service_type: Any) -> Any:
        key = (service, service_type)
        if key not in self._clients:
            client = self.node.create_client(service_type, service)
            if not client.wait_for_service(timeout_sec=self.service_timeout):
                raise UbtechServiceError(service, "service unavailable")
            self._clients[key] = client
        return self._clients[key]

    def _finish_future(self, service: str, future: Any) -> Any:
        self._rclpy.spin_until_future_complete(
            self.node, future, timeout_sec=self.service_timeout
        )
        if not future.done():
            raise UbtechServiceError(service, "service timeout")
        exception = future.exception()
        if exception:
            raise UbtechServiceError(service, type(exception).__name__)
        return future.result()

    def _call_string(self, service: str, params: Dict[str, Any]) -> Dict[str, Any]:
        client = self._client(service, self._StringCall)
        request = self._StringCall.Request()
        request.params = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
        response = self._finish_future(service, client.call_async(request))
        envelope = _parse_json_message(getattr(response, "result", ""))
        self._raise_if_failed(service, envelope)
        return envelope

    def _call_trigger(
        self, service: str, require_ok: bool = True
    ) -> Dict[str, Any]:
        client = self._client(service, self._Trigger)
        request = self._Trigger.Request()
        response = self._finish_future(service, client.call_async(request))
        envelope = _parse_json_message(getattr(response, "message", ""))
        if not envelope:
            envelope = {
                "ok": bool(getattr(response, "success", False)),
                "code": "OK" if getattr(response, "success", False) else "FAILED",
                "message": getattr(response, "message", ""),
                "data": {},
            }
        if require_ok:
            self._raise_if_failed(service, envelope)
        return envelope

    @staticmethod
    def _raise_if_failed(service: str, envelope: Dict[str, Any]) -> None:
        if envelope.get("ok") is False:
            message = str(envelope.get("message") or envelope.get("code") or "failed")
            raise UbtechServiceError(service, message, envelope)

    def authorize(self, credentials: UbtechCredentials) -> Dict[str, Any]:
        return self._call_string(AUTH_SERVICE, credentials.as_request())

    def authorize_from_env(self) -> Dict[str, Any]:
        return self.authorize(UbtechCredentials.from_env())

    def auth_state(self) -> Dict[str, Any]:
        return self._call_trigger(AUTH_STATE_SERVICE, require_ok=False)

    def ready_state(self) -> Dict[str, Any]:
        return self._call_trigger(READY_STATE_SERVICE)

    def health_check(self) -> Dict[str, Any]:
        auth = self.auth_state()
        authorized = bool(_event_data(auth).get("authorized", False))
        result: Dict[str, Any] = {"authorized": authorized, "auth": auth}
        if authorized:
            ready = self.ready_state()
            ready_data = _event_data(ready)
            result.update(
                {
                    "ready": bool(ready_data.get("ready", False)),
                    "current_mode": ready_data.get("current_mode", ""),
                    "ready_response": ready,
                }
            )
        else:
            result.update({"ready": False, "current_mode": ""})
        return result

    def ensure_authorized(self) -> Dict[str, Any]:
        state = self.auth_state()
        if _event_data(state).get("authorized"):
            return state
        self.authorize_from_env()
        state = self.auth_state()
        if not _event_data(state).get("authorized"):
            raise UbtechServiceError(AUTH_STATE_SERVICE, "authorization not active", state)
        return state

    def _wait_for_playback(
        self,
        request_id: str,
        request_type: str,
        started: float,
        timeout: float,
    ) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
        deadline = time.perf_counter() + timeout
        first_event_ms: Optional[float] = None
        while time.perf_counter() < deadline:
            self._rclpy.spin_once(self.node, timeout_sec=0.1)
            while self._events:
                event_time, envelope = self._events.popleft()
                data = _event_data(envelope)
                event_id = str(data.get("uuid", ""))
                event_type = str(data.get("request_type", ""))
                if event_id and event_id != request_id:
                    continue
                if event_type and event_type != request_type:
                    continue
                if first_event_ms is None:
                    first_event_ms = (event_time - started) * 1000
                if str(data.get("phase", "")).lower() == "result":
                    return first_event_ms, (event_time - started) * 1000, envelope
        return first_event_ms, None, {}

    def _play(
        self,
        service: str,
        request_type: str,
        params: Dict[str, Any],
        wait: bool,
        timeout: Optional[float],
    ) -> PlaybackResult:
        request_id = str(params.get("uuid") or uuid.uuid4())
        params["uuid"] = request_id
        self._events.clear()
        started = time.perf_counter()
        envelope = self._call_string(service, params)
        request_ms = (time.perf_counter() - started) * 1000
        response_data = _event_data(envelope)
        request_id = str(response_data.get("uuid") or request_id)
        accepted = bool(response_data.get("accepted", envelope.get("ok", False)))
        if not wait:
            return PlaybackResult(
                request_id=request_id,
                request_type=request_type,
                accepted=accepted,
                completed=False,
                success=accepted,
                code=int(response_data.get("code", 0) or 0),
                message=str(envelope.get("message", "")),
                request_ms=request_ms,
                raw_response=envelope,
            )

        first_event_ms, playback_ms, event = self._wait_for_playback(
            request_id,
            request_type,
            started,
            timeout or self.playback_timeout,
        )
        data = _event_data(event) if event else {}
        completed = playback_ms is not None
        success = completed and bool(data.get("success", False))
        message = str(
            data.get("message")
            or ("playback timeout" if not completed else "playback failed")
        )
        return PlaybackResult(
            request_id=request_id,
            request_type=request_type,
            accepted=accepted,
            completed=completed,
            success=success,
            code=int(data.get("code", 0) or 0),
            message=message,
            request_ms=request_ms,
            first_event_ms=first_event_ms,
            playback_ms=playback_ms,
            raw_response=envelope,
            raw_event=event,
        )

    def speak(
        self,
        text: str,
        action: str = "",
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> PlaybackResult:
        spoken = text.strip()
        if not spoken:
            raise ValueError("text must not be empty")
        params: Dict[str, Any] = {"text": spoken, "save": False}
        if action:
            params["action"] = action
        return self._play(PLAY_TEXT_SERVICE, "play_text", params, wait, timeout)

    def play_action(
        self,
        action: str,
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> PlaybackResult:
        motion_id = action.strip()
        if not motion_id:
            raise ValueError("action must not be empty")
        return self._play(
            PLAY_ACTION_SERVICE,
            "play_action",
            {"action": motion_id},
            wait,
            timeout,
        )

    def interrupt(self) -> Dict[str, Any]:
        return self._call_trigger(INTERRUPT_SERVICE)

    def get_motion_info_list(self) -> Dict[str, Any]:
        return self._call_string(MOTION_LIST_SERVICE, {})

    def open_audio_stream(self) -> Dict[str, Any]:
        return self._call_trigger(AUDIO_OPEN_SERVICE)

    def audio_stream_state(self) -> Dict[str, Any]:
        return self._call_trigger(AUDIO_STATE_SERVICE)

    def close_audio_stream(self) -> Dict[str, Any]:
        return self._call_trigger(AUDIO_CLOSE_SERVICE)

    def close(self) -> None:
        if getattr(self, "node", None) is not None:
            self.node.destroy_node()
            self.node = None
        if self._owns_rclpy and self._rclpy.ok():
            self._rclpy.shutdown()

    def __enter__(self) -> "UbtechRos2Adapter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

