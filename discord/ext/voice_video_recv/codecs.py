"""Payload types and codec list announced to the Discord voice gateway."""

PT_AUDIO = 120
PT_H264, PT_H264_RTX = 101, 102
PT_VP8, PT_VP8_RTX = 103, 104

CODEC_BY_PT = {PT_H264: "h264", PT_VP8: "vp8"}
RTX_PAYLOAD_TYPES = frozenset({PT_H264_RTX, PT_VP8_RTX})

# SELECT_PROTOCOL "codecs" list. The server only forwards codecs we declare here.
CODECS = [
    {"name": "opus", "type": "audio", "priority": 1000, "payload_type": PT_AUDIO, "rtx_payload_type": None},
    {"name": "H264", "type": "video", "priority": 1000, "payload_type": PT_H264, "rtx_payload_type": PT_H264_RTX},
    {"name": "VP8", "type": "video", "priority": 2000, "payload_type": PT_VP8, "rtx_payload_type": PT_VP8_RTX},
]

START3 = b"\x00\x00\x01"
START4 = b"\x00\x00\x00\x01"
