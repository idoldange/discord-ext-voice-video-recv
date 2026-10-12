"""Background decoding of one video stream with PyAV."""
import logging
import queue
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("discord.ext.voice_video_recv")


class FrameDecoder(threading.Thread):
    """Decodes encoded frames off the network thread and emits PIL images.

    Frames are queued (oldest dropped when full). At most ``max_fps`` pictures per second are converted
    to images and passed to ``on_image``; every frame is still decoded so the reference chain stays valid.
    ``on_error`` is called when decoding fails (the caller should request a keyframe).
    """

    def __init__(self, codec: str, on_image: Callable[[Any], None], on_error: Optional[Callable[[], None]] = None,
                 *, max_fps: float = 2.5, max_width: int = 960, queue_size: int = 12) -> None:
        super().__init__(daemon=True, name=f"dvv-decoder-{codec}")
        self.codec, self.on_image, self.on_error = codec, on_image, on_error
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 0.0
        self.max_width = max_width
        self.q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=queue_size)
        self._last = 0.0
        self.start()

    def put(self, frame: Optional[bytes]) -> bool:
        """Queue an encoded frame (``None`` stops the thread). Returns False if the frame was dropped.

        A full queue means the decoder cannot keep up. Dropping just the oldest frame would silently break
        the reference chain (artifacts until the next keyframe), so the whole backlog is discarded and
        ``on_error`` is called so the caller waits for / requests a fresh keyframe.
        """
        try:
            self.q.put_nowait(frame)
            return True
        except queue.Full:
            self._drain()
            if frame is None:
                self.q.put_nowait(None)
                return True
            if self.on_error:
                self.on_error()
            return False

    def _drain(self) -> None:
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def stop(self) -> None:
        self.put(None)

    def run(self) -> None:
        import av
        ctx = av.CodecContext.create(self.codec, "r")
        while True:
            frame = self.q.get()
            if frame is None:
                return
            try:
                for pkt in ctx.parse(frame):
                    for fr in ctx.decode(pkt):
                        now = time.monotonic()
                        if now - self._last < self.min_interval:
                            continue
                        self._last = now
                        img = fr.to_image()
                        if self.max_width and img.width > self.max_width:
                            img = img.resize((self.max_width, max(1, img.height * self.max_width // img.width)))
                        self.on_image(img)
            except Exception as e:
                log.warning("decode error (%s): %s", self.codec, e)
                if self.on_error:
                    self.on_error()
