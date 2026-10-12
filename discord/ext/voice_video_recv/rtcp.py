"""RTCP helpers for the Discord voice UDP connection."""
import struct

AEAD_RTPSIZE = "aead_xchacha20_poly1305_rtpsize"


def build_pli(box, sender_ssrc: int, media_ssrc: int, counter: int) -> bytes:
    """Encrypted RTCP Picture Loss Indication (PSFB fmt 1) asking ``media_ssrc`` for a keyframe.

    Only valid for the ``aead_xchacha20_poly1305_rtpsize`` transport mode: the 8-byte RTCP header is
    sent in clear (used as AAD), the media SSRC is encrypted and a 4-byte big-endian counter is
    appended as the nonce suffix.
    """
    header = struct.pack(">BBHI", 0x81, 206, 2, sender_ssrc)
    suffix = struct.pack(">I", counter & 0xFFFFFFFF)
    nonce = suffix + bytes(20)
    ct = box.encrypt(struct.pack(">I", media_ssrc), header, nonce).ciphertext
    return header + ct + suffix
