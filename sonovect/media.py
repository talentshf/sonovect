"""One explicit, bounded media decode boundary before either model backend."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import math
import shutil
import subprocess
import wave

FORMATS = "wav,mp3,flac,ogg,mov,matroska,aac,aiff,avi"
AUDIO_EXAMPLES = ["WAV", "FLAC", "MP3", "M4A/AAC", "OGG/Opus", "AIFF"]
VIDEO_EXAMPLES = ["MP4", "MOV", "MKV", "WebM", "AVI"]


class MediaError(RuntimeError):
    """Public bounded error code; decoder output never reaches a client."""


def decoder_available():
    return all(shutil.which(name) for name in ("ffmpeg", "ffprobe"))


def _run(command, timeout):
    try:
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout, check=False)
    except FileNotFoundError:
        raise MediaError("media_decoder_unavailable") from None
    except subprocess.TimeoutExpired:
        raise MediaError("media_decode_timeout") from None


def _seconds(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


@contextmanager
def prepare_media(path: Path, options: dict, settings, *, scratch_dir=None):
    """Decode by content, select an audio stream and preserve its container offset.

    No visual inference, network demuxers, filename inference or model rewriting.
    The temporary WAV shares the operator's task volume and is always removed.
    """
    probe = _run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                  "-format_whitelist", FORMATS, "-show_entries",
                  "stream=codec_type,sample_rate,channels,start_time:format=start_time",
                  "-of", "json", str(path)], min(30, settings.media_timeout))
    if probe.returncode:
        raise MediaError("media_decode_failed")
    try:
        info = json.loads(probe.stdout)
        streams = info.get("streams", [])
        audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if not audio:
            raise MediaError("media_no_audio")
        track = options.get("audio_track", 0)
        if track >= len(audio):
            raise MediaError("media_audio_track_unavailable")
        selected = audio[track]
        offset = max(0, round(1000 * (_seconds(selected.get("start_time")) -
                                     _seconds(info.get("format", {}).get("start_time")))))
    except (ValueError, TypeError, AttributeError, KeyError):
        raise MediaError("media_decode_failed") from None
    if offset >= settings.max_media_seconds * 1000:
        raise MediaError("media_duration_exceeded")
    with TemporaryDirectory(prefix="decode-", dir=scratch_dir or settings.data_dir) as directory:
        decoded = Path(directory) / "audio.wav"
        # Permit at most one extra second so oversized sources fail, never truncate successfully.
        result = _run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error",
                       "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS,
                       "-i", str(path), "-map", f"0:a:{track}", "-vn", "-sn", "-dn",
                       "-af", f"asetpts=PTS-STARTPTS,aresample=16000:async=1:first_pts=0,adelay={offset}:all=1",
                       "-ac", "1", "-c:a", "pcm_s16le", "-threads", "1",
                       "-map_metadata", "-1", "-t", str(settings.max_media_seconds + 1),
                       "-y", str(decoded)], settings.media_timeout)
        if result.returncode:
            raise MediaError("media_decode_failed")
        try:
            with wave.open(str(decoded), "rb") as handle:
                frames, rate = handle.getnframes(), handle.getframerate()
        except (OSError, EOFError, wave.Error):
            raise MediaError("media_decode_failed") from None
        if not frames:
            raise MediaError("media_no_audio")
        if frames > settings.max_media_seconds * rate:
            raise MediaError("media_duration_exceeded")
        metadata = {"kind": "video" if any(s.get("codec_type") == "video" for s in streams) else "audio",
                    "audio_track": track, "audio_tracks": len(audio),
                    "source_channels": selected.get("channels"), "source_sample_rate": selected.get("sample_rate"),
                    "duration_ms": round(frames * 1000 / rate), "leading_silence_ms": offset,
                    "timeline_origin": "container_start", "decoded_sample_rate": rate, "decoded_channels": 1}
        yield decoded, metadata
