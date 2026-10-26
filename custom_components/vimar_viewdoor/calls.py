"""Unverified call-related notifications observed during an existing preview.

Android QvPlayerCore dispatches transparent command 23 to
onOtherDoorBellCall(channel, name). This is NOT proven to be the initial ring.
No subscription, ring, answer, decline or unlock commands are transmitted.
"""
import logging
from dataclasses import dataclass
from typing import Callable

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class CallCandidate:
    channel: int
    command: int = 23
    verified: bool = False


def parse_call_candidate(message: dict) -> CallCandidate | None:
    header = message.get('header')
    if message.get('is_media') or header is None or header.packet_type != 254:
        return None
    raw = header.raw
    if len(raw) != 32 or raw[13] != 23:
        return None
    size = header.raw_size
    payload = message.get('payload', b'')
    if not 1 <= size <= 256 or len(payload) < size:
        return None
    # Omit the following device-supplied name; it may identify a household.
    channel = payload[0]
    return CallCandidate(channel=channel)


def observe_session(session, observer: Callable[[CallCandidate], None]):
    """Observe a single session without global patches or a new connection."""
    receive = session.recv_message
    def observed_receive(*, timeout=1.0):
        message = receive(timeout=timeout)
        candidate = parse_call_candidate(message)
        if candidate is not None:
            try:
                observer(candidate)
            except Exception as exc:
                # Experimental notification handling must not break video.
                _LOGGER.warning('Call candidate observer failed: %s',type(exc).__name__)
        return message
    session.recv_message = observed_receive
    return session
