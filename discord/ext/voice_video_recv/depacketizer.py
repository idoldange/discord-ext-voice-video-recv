"""RTP payloads of one SSRC -> whole encoded frames (VP8 per RFC 7741, H264 per RFC 6184)."""
import struct
from typing import List, Optional, Tuple

from .codecs import START4


class FrameAssembler:
    """Collects RTP payloads of a single stream into complete encoded frames.

    ``push`` returns ``(frame_bytes, is_keyframe)`` when a frame is complete and usable, else ``None``.
    Any lost packet damages the frame and everything after it until the next keyframe, so after a loss
    ``need_key`` stays True and nothing is returned until a clean keyframe has been completed. Callers
    should send a keyframe request (PLI) while ``need_key`` is set.

    H264 frames come out as Annex-B with 4-byte start codes; VP8 frames come out as raw VP8 frames.
    """

    def __init__(self, codec: str) -> None:
        if codec not in ("vp8", "h264"):
            raise ValueError(f"unsupported codec: {codec!r}")
        self.codec = codec
        self.ts: Optional[int] = None
        self.parts: List[bytes] = []
        self.key = False
        self.ok = True
        self.last_seq: Optional[int] = None
        self.need_key = True

    def push(self, seq: int, ts: int, marker: bool, data: bytes) -> Optional[Tuple[bytes, bool]]:
        if self.last_seq is not None and ((seq - self.last_seq) & 0xFFFF) != 1:
            self.ok = False
            self.need_key = True
        self.last_seq = seq

        if self.ts is not None and ts != self.ts:
            if self.parts:                      # previous frame never got its marker packet -> it is lost
                self.need_key = True
            self.parts, self.key, self.ok = [], False, True
        self.ts = ts

        try:
            chunk, key = self._vp8(data) if self.codec == "vp8" else self._h264(data)
        except Exception:
            self.ok = False
            self.need_key = True
            return None

        if chunk:
            self.parts.append(chunk)
        self.key = self.key or key
        if not marker:
            return None

        frame, key, ok = b"".join(self.parts), self.key, self.ok
        self.parts, self.key, self.ok, self.ts = [], False, True, None
        if not ok or not frame:
            return None
        if key:
            self.need_key = False
        return (frame, key) if not self.need_key else None

    @staticmethod
    def _vp8(p: bytes) -> Tuple[bytes, bool]:
        i = 1
        start = bool(p[0] & 0x10) and (p[0] & 0x0F) == 0     # S bit set and partition id 0
        if p[0] & 0x80:                                       # X: extended control bits
            x = p[1]
            i = 2
            if x & 0x80:                                      # I: picture id (7 or 15 bit)
                i += 2 if p[i] & 0x80 else 1
            if x & 0x40:                                      # L: TL0PICIDX
                i += 1
            if x & 0x30:                                      # T / K
                i += 1
        body = p[i:]
        return body, bool(start and body and (body[0] & 0x01) == 0)

    @staticmethod
    def _h264(p: bytes) -> Tuple[bytes, bool]:
        t = p[0] & 0x1F
        if t == 24:                                           # STAP-A
            out, i, key = [], 1, False
            while i + 2 <= len(p):
                n = struct.unpack_from(">H", p, i)[0]
                nal = p[i + 2:i + 2 + n]
                out.append(START4 + nal)
                key = key or (nal[0] & 0x1F) in (5, 7)
                i += 2 + n
            return b"".join(out), key
        if t == 28:                                           # FU-A
            hdr = p[1]
            if hdr & 0x80:                                    # start of a fragmented NAL
                nal_hdr = bytes([(p[0] & 0xE0) | (hdr & 0x1F)])
                return START4 + nal_hdr + p[2:], (hdr & 0x1F) in (5, 7)
            return p[2:], False
        return START4 + p, t in (5, 7)                        # single NAL unit
