"""DAVE (Discord E2EE) layer for video frames."""
from typing import Any, Optional

from .codecs import START3, START4

try:
    import davey
except Exception:  # pragma: no cover - optional dependency
    davey = None


def decrypt_video_frame(voice_client: Any, user_id: int, frame: bytes, codec: str) -> Optional[bytes]:
    """Strip the DAVE layer from one assembled video frame.

    Returns the frame unchanged when the call is not end-to-end encrypted, the decrypted frame on
    success, or ``None`` when it cannot be decrypted (session not ready, wrong key, tampered...).
    Never raises.
    """
    state = getattr(voice_client, "_connection", None)
    if not getattr(state, "dave_protocol_version", 0):
        return frame
    session = getattr(state, "dave_session", None)
    if davey is None or session is None or not session.ready:
        return None
    variants = [frame]
    if codec == "h264":
        # The sender encrypts the NAL units as it has them; the start-code length is not on the wire,
        # so after the 4-byte form also try the 3-byte one.
        variants.append(frame.replace(START4, START3))
    for v in variants:
        try:
            return session.decrypt(int(user_id), davey.MediaType.video, v)
        except BaseException as e:  # davey / pyo3 panics are BaseExceptions
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
    return None
