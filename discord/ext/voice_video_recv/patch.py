"""Runtime patches that make discord.py + discord-ext-voice-recv receive video.

* voice gateway IDENTIFY / SELECT_PROTOCOL declare video support and the video codecs, and a receive-only
  video state (op 12) is announced right after SELECT_PROTOCOL, like the official client does;
* the READY ``streams`` (video / rtx SSRCs the server allocated for us) are remembered;
* ``AudioReader.callback`` hands video RTP to the :class:`VideoReceiver` instead of the audio pipeline.
"""
import logging
import struct
from typing import Any, Dict, Optional

from .codecs import CODECS, CODEC_BY_PT, RTX_PAYLOAD_TYPES

log = logging.getLogger("discord.ext.voice_video_recv")

_originals: Dict[str, Any] = {}
_active: Optional[Any] = None


def is_installed() -> bool:
    return bool(_originals)


def install(receiver) -> None:
    """Patch discord.py (idempotent; one process-wide receiver, the latest one wins)."""
    global _active
    _active = receiver
    if _originals:
        return
    from discord.gateway import DiscordVoiceWebSocket as WS
    from discord.ext.voice_recv import reader as _reader, rtp

    _originals["send_as_json"] = orig_send = WS.send_as_json
    _originals["initial_connection"] = orig_init = WS.initial_connection
    _originals["callback"] = orig_cb = _reader.AudioReader.callback

    async def send_as_json(self, data):
        op = data.get("op") if isinstance(data, dict) else None
        if op == self.IDENTIFY:
            data["d"]["video"] = True
            data["d"]["streams"] = [{"type": "video", "rid": "100", "quality": 100}]
        elif op == self.SELECT_PROTOCOL:
            data["d"]["codecs"] = CODECS
        await orig_send(self, data)
        if op == self.SELECT_PROTOCOL:
            try:
                st = (getattr(self, "_dvv_streams", None) or [{}])[0]
                vs, rs = st.get("ssrc", 0), st.get("rtx_ssrc", 0)
                await orig_send(self, {"op": 12, "d": {
                    "audio_ssrc": self._connection.ssrc, "video_ssrc": vs, "rtx_ssrc": rs,
                    "streams": [{"type": "video", "rid": "100", "ssrc": vs, "active": False, "quality": 100,
                                 "rtx_ssrc": rs, "max_bitrate": 2500000, "max_framerate": 20,
                                 "max_resolution": {"type": "fixed", "width": 1280, "height": 720}}]}})
                log.debug("announced receive-only video state (video_ssrc=%s, rtx_ssrc=%s)", vs, rs)
            except Exception as e:
                log.warning("video-state announce failed: %s", e)

    async def initial_connection(self, data):
        self._dvv_streams = data.get("streams")
        log.debug("READY streams from server: %s", self._dvv_streams)
        await orig_init(self, data)

    def callback(self, packet_data):
        rx = _active
        try:
            if rx is not None and len(packet_data) > 12 and not rtp.is_rtcp(packet_data):
                ssrc = struct.unpack_from(">I", packet_data, 8)[0]
                pt = packet_data[1] & 0x7F
                if ssrc in rx.ssrc_info or pt in CODEC_BY_PT or pt in RTX_PAYLOAD_TYPES:
                    if pt in RTX_PAYLOAD_TYPES:
                        return
                    pkt = rtp.decode_rtp(packet_data)
                    pkt.decrypted_data = self.decryptor.decrypt_rtp(pkt)
                    rx.handle_packet(self, pkt)
                    return
        except Exception as e:
            log.warning("video packet error: %s", e)
            return
        return orig_cb(self, packet_data)

    WS.send_as_json = send_as_json
    WS.initial_connection = initial_connection
    _reader.AudioReader.callback = callback
    log.debug("video receive patches installed")


def uninstall() -> None:
    """Restore the original discord.py behaviour."""
    global _active
    if not _originals:
        return
    from discord.gateway import DiscordVoiceWebSocket as WS
    from discord.ext.voice_recv import reader as _reader
    WS.send_as_json = _originals.pop("send_as_json")
    WS.initial_connection = _originals.pop("initial_connection")
    _reader.AudioReader.callback = _originals.pop("callback")
    _originals.clear()
    _active = None
