# discord-ext-voice-video-recv

Receive other members' **camera video** in a [discord.py](https://github.com/Rapptz/discord.py) voice call, as `PIL.Image`s.
It is a discord.py extension (`discord.ext.voice_video_recv`) that builds on the
[idoldange/discord-ext-voice-recv](https://github.com/idoldange/discord-ext-voice-recv) fork.

```
voice gateway op 12 (ssrc -> user)  -> which SSRC belongs to whom
UDP RTP (decrypted by voice_recv)   -> FrameAssembler  (VP8 / H264 depacketizer, loss detection)
frame                               -> DAVE (E2EE) decrypt via davey
frame                               -> PyAV decode in a background thread
image                               -> your on_frame(user_id, "camera", PIL.Image)
```

Bots normally never get video: the voice gateway only sends it to clients that declare video support.
This extension patches the voice handshake to declare it, announces a receive-only video state, diverts the
video RTP away from the audio pipeline, asks senders for keyframes (RTCP PLI) after packet loss, and strips
the DAVE layer.

> Screen shares (Go Live) are **not** delivered to bots by Discord, only cameras.

## Installing

```
pip install git+https://github.com/idoldange/discord-ext-voice-video-recv.git
```

This pulls in the dependencies, including the **fork** of voice-recv
(`discord-ext-voice_recv @ git+https://github.com/idoldange/discord-ext-voice-recv.git`) instead of the
upstream package: the fork parses the voice gateway VIDEO op and dispatches the `voice_member_video` event
that this extension needs. If upstream `discord-ext-voice_recv` is already installed, uninstall it first.

Requires Python 3.10+ and discord.py 2.7+ (DAVE support).

## Usage

```python
import discord
from discord.ext import voice_recv, voice_video_recv

client = discord.Client(intents=discord.Intents.all())

def on_frame(user_id: int, kind: str, image):          # runs in a decoder thread
    image.save(f"cam_{user_id}.jpg")

def on_stopped(user_id: int, kind: str):               # camera turned off / member left
    print("camera off:", user_id)

video = voice_video_recv.VideoReceiver(on_frame=on_frame, on_stream_stopped=on_stopped)
video.start(client)            # once, before connecting to voice

# ...then connect as usual:
vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
vc.listen(voice_recv.BasicSink(lambda user, data: None))     # the reader must be listening
```

`start()` = `install()` (patches `DiscordVoiceWebSocket` and `AudioReader.callback`, idempotent, process-wide)
+ `attach(client)` (registers `on_voice_member_video` / `on_voice_state_update` listeners).
`voice_video_recv.uninstall()` restores the original behaviour.

### Options

| argument | default | meaning |
| --- | --- | --- |
| `max_fps` | `2.5` | max pictures per second passed to `on_frame` (every frame is still decoded; `0` = no limit) |
| `max_width` | `960` | images wider than this are downscaled |
| `decoder_queue` | `30` | encoded frames buffered per stream; on overflow the backlog is dropped and a keyframe is requested |

Logs go to the `discord.ext.voice_video_recv` logger (`DEBUG` shows the video state, packet counters every 10 s and the PLI count).

## Layout

| module | role |
| --- | --- |
| `receiver.py` | `VideoReceiver`: state tracking, per-stream assembler/decoder, keyframe requests |
| `patch.py` | handshake + reader patches (`install` / `uninstall`) |
| `depacketizer.py` | `FrameAssembler`: RTP payloads -> frames (VP8 RFC 7741, H264 RFC 6184 STAP-A/FU-A -> Annex-B) |
| `dave.py` | DAVE frame decryption (H264: tries 4- and 3-byte start codes) |
| `decoder.py` | `FrameDecoder`: PyAV decoding thread |
| `rtcp.py` | encrypted PLI packet (`aead_xchacha20_poly1305_rtpsize`) |

## Caveats

* Experimental: it monkey-patches discord.py internals and relies on the server forwarding video to `udp`-mode voice clients.
* Only the `aead_xchacha20_poly1305_rtpsize` transport mode can send PLI keyframe requests; other modes just wait for the next keyframe.
* H264 and VP8 only.

## License

MIT
