"""VideoReceiver: turns Discord voice RTP video into decoded PIL images."""
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .codecs import CODEC_BY_PT, PT_AUDIO
from .dave import decrypt_video_frame
from .decoder import FrameDecoder
from .depacketizer import FrameAssembler
from .rtcp import AEAD_RTPSIZE, build_pli

log = logging.getLogger("discord.ext.voice_video_recv")

FrameCallback = Callable[[int, str, Any], None]
StopCallback = Callable[[int, str], None]


class VideoReceiver:
    """Receives other members' camera video in a discord.py voice call.

    ``on_frame(user_id, kind, image)`` is called from a decoder thread with a ``PIL.Image`` (``kind`` is
    ``"camera"``). ``on_stream_stopped(user_id, kind)`` is called (event-loop thread) when a member's
    camera turns off or they leave. Use :meth:`start` once, before connecting to voice.
    """

    def __init__(self, on_frame: Optional[FrameCallback] = None, on_stream_stopped: Optional[StopCallback] = None,
                 *, max_fps: float = 2.5, max_width: int = 960, decoder_queue: int = 30,
                 stats_interval: float = 10.0) -> None:
        self.on_frame = on_frame
        self.on_stream_stopped = on_stream_stopped
        self.max_fps, self.max_width, self.decoder_queue = max_fps, max_width, decoder_queue
        self.stats_interval = stats_interval
        self.ssrc_info: Dict[int, Tuple[int, str]] = {}       # video ssrc -> (user id, kind)
        self.asm: Dict[int, FrameAssembler] = {}
        self.dec: Dict[int, FrameDecoder] = {}
        self.packets: Dict[Tuple[int, int], int] = {}         # (ssrc, payload type) -> packets
        self.counters = {"frames": 0, "dave_fail": 0, "pli": 0}
        self._pli_t: Dict[int, float] = {}
        self._pli_n = 0
        self._log_t = time.monotonic()
        self._client = None

    # ── setup ──
    def start(self, client) -> "VideoReceiver":
        """Patch discord.py's voice gateway/reader (declares video support) and listen to client events."""
        from .patch import install
        install(self)
        self.attach(client)
        return self

    def attach(self, client) -> None:
        """Register the discord.py event listeners (only needed if you do not call :meth:`start`)."""
        self._client = client
        client.add_listener(self.on_voice_member_video, "on_voice_member_video")
        client.add_listener(self._on_voice_state_update, "on_voice_state_update")

    # ── discord events ──
    async def on_voice_member_video(self, member, streams) -> None:
        self.on_video_state(member, streams)

    async def _on_voice_state_update(self, member, before, after) -> None:
        me = getattr(self._client, "user", None)
        if me is not None and member.id == me.id:
            if before.channel is not None and after.channel is None:
                self.reset()
            return
        if before.channel is not None and after.channel != before.channel:
            self.forget_user(member.id)

    def on_video_state(self, member, streams) -> None:
        """Voice gateway VIDEO update for one member (``voice_member_video`` event payload)."""
        if member is None:
            return
        uid = member.id
        for ssrc, (u, _k) in list(self.ssrc_info.items()):
            if u == uid:
                self._drop(ssrc)
        active = 0
        for s in streams.streams:
            if getattr(s, "type", "video") == "screen":       # Go Live is never sent to bots
                continue
            if s.active and s.ssrc:
                self.ssrc_info[s.ssrc] = (uid, "camera")
                active += 1
        if streams.video_ssrc and active == 0 and any(getattr(s, "active", True) for s in streams.streams):
            self.ssrc_info[streams.video_ssrc] = (uid, "camera")
            active += 1
        if not active:
            self._stopped(uid)
        log.debug("%s video state: %r", member, streams)

    def forget_user(self, uid: int) -> None:
        for ssrc, (u, _k) in list(self.ssrc_info.items()):
            if u == uid:
                self._drop(ssrc)
        self._stopped(uid)

    def reset(self) -> None:
        """Forget every stream (call when the bot leaves the voice channel)."""
        users = {u for u, _k in self.ssrc_info.values()}
        for ssrc in list(self.ssrc_info):
            self._drop(ssrc)
        self.packets.clear()
        for uid in users:
            self._stopped(uid)

    def _stopped(self, uid: int) -> None:
        if self.on_stream_stopped:
            try:
                self.on_stream_stopped(uid, "camera")
            except Exception:
                log.exception("on_stream_stopped failed")

    def _drop(self, ssrc: int) -> None:
        self.ssrc_info.pop(ssrc, None)
        self.asm.pop(ssrc, None)
        d = self.dec.pop(ssrc, None)
        if d:
            d.stop()

    # ── RTP (socket thread) ──
    def handle_packet(self, reader, pkt) -> None:
        """One transport-decrypted RTP packet (``pkt.decrypted_data`` is the codec payload)."""
        ssrc, pt = pkt.ssrc, pkt.payload
        self.packets[(ssrc, pt)] = self.packets.get((ssrc, pt), 0) + 1
        self._maybe_log()
        info = self.ssrc_info.get(ssrc)
        codec = CODEC_BY_PT.get(pt)
        if info is None or codec is None or not pkt.decrypted_data:
            return
        asm = self.asm.get(ssrc)
        if asm is None or asm.codec != codec:
            asm = self.asm[ssrc] = FrameAssembler(codec)
        done = asm.push(pkt.sequence, pkt.timestamp, pkt.marker, bytes(pkt.decrypted_data))
        if asm.need_key:
            self._request_keyframe(reader, ssrc)
        if done is None:
            return
        frame = decrypt_video_frame(reader.voice_client, info[0], done[0], codec)
        if frame is None:
            self.counters["dave_fail"] += 1
            asm.need_key = True
            return
        dec = self.dec.get(ssrc)
        if dec is None:
            uid, kind = info
            dec = self.dec[ssrc] = FrameDecoder(
                codec, lambda img, u=uid, k=kind: self._emit(u, k, img),
                lambda a=asm: setattr(a, "need_key", True),
                max_fps=self.max_fps, max_width=self.max_width, queue_size=self.decoder_queue)
        self.counters["frames"] += 1
        dec.put(frame)

    def _emit(self, uid: int, kind: str, img) -> None:
        if self.on_frame:
            try:
                self.on_frame(uid, kind, img)
            except Exception:
                log.exception("on_frame failed")

    def _request_keyframe(self, reader, ssrc: int) -> None:
        now = time.monotonic()
        if now - self._pli_t.get(ssrc, 0.0) < 1.0:
            return
        self._pli_t[ssrc] = now
        try:
            dec = reader.decryptor
            if dec.mode != AEAD_RTPSIZE:
                return
            conn = reader.voice_client._connection
            self._pli_n = (self._pli_n + 1) & 0xFFFFFFFF
            conn.socket.sendall(build_pli(dec.box, conn.ssrc, ssrc, self._pli_n))
            self.counters["pli"] += 1
        except Exception as e:
            log.warning("PLI failed: %s", e)

    def _maybe_log(self) -> None:
        now = time.monotonic()
        if now - self._log_t < self.stats_interval:
            return
        self._log_t = now
        vid = {k: v for k, v in self.packets.items() if k[1] != PT_AUDIO}
        log.debug("packets (ssrc,pt)->n: %s | %s", vid, self.counters)
