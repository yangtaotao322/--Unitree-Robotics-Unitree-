"""Robot-independent playback interface used by dialogue applications."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PlaybackResult:
    """Result of one robot speech or action request.

    ``accepted`` only means the robot accepted the command. ``completed`` and
    ``success`` must come from the robot's final playback event.
    """

    request_id: str
    request_type: str
    accepted: bool
    completed: bool
    success: bool
    code: int = 0
    message: str = ""
    request_ms: float = 0.0
    first_event_ms: Optional[float] = None
    playback_ms: Optional[float] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    raw_event: Dict[str, Any] = field(default_factory=dict)


class RobotAdapter(ABC):
    """Small stable boundary between the dialogue core and a robot SDK."""

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Return authorization and readiness information."""

    @abstractmethod
    def speak(
        self,
        text: str,
        action: str = "",
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> PlaybackResult:
        """Speak text and optionally wait for the final playback event."""

    @abstractmethod
    def play_action(
        self,
        action: str,
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> PlaybackResult:
        """Play a robot action and optionally wait for completion."""

    @abstractmethod
    def interrupt(self) -> Dict[str, Any]:
        """Interrupt the current speech or action."""

    def close(self) -> None:
        """Release adapter resources."""

