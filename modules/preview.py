"""
Fast, cheap previews so you're not gambling with subtitle/music settings blind.

Both previews reuse the exact same rendering logic as the real clip export
(same .ass generation, same ffmpeg filters, same audio mixing) so what you see
here is what you'll actually get - just applied to a single frame / a few
seconds of audio instead of a whole clip, so it renders in under a second.
"""
import os
import subprocess

from .subtitles import SubtitleStyle, generate_ass
from .utils import safe_ffmpeg_path, get_video_duration

SAMPLE_CAPTION = "This is how your captions will look on the real clip!"


def _sample_words(text: str, start: float = 0.0, words_per_minute: int = 170):
    """Fake word-level timestamps for the sample caption, so it can go through
    the same generate_ass() used for real clips."""
    words = text.split()
    seconds_per_word = 60.0 / words_per_minute
    out = []
    t = start
    for w in words:
        out.append({"word": w, "start": t, "end": t + seconds_per_word})
        t += seconds_per_word
    return out


def pick_preview_timestamp(video_path: str, desired: float = None) -> float:
    """A safe timestamp to grab a frame/audio from - clamped inside the video's
    actual length so we don't ask ffmpeg to seek past the end."""
    duration = get_video_duration(video_path)
    if desired is None:
        desired = 3.0
    if duration is None:
        return max(0.0, desired)
    return max(0.0, min(desired, max(0.0, duration - 1.0)))


def render_style_preview(video_path: str, style: SubtitleStyle, vertical: bool,
                          resolution: tuple, out_path: str, timestamp: float = 3.0) -> str:
    """Grab one frame from the video and burn in a sample caption using the
    given style. Returns out_path, raises RuntimeError if ffmpeg fails."""
    ass_path = out_path + ".ass"
    sample_words = _sample_words(SAMPLE_CAPTION)
    generate_ass(sample_words, clip_start=0.0, clip_end=6.0, out_path=ass_path,
                 style=style, resolution=resolution)
    ass_escaped = safe_ffmpeg_path(ass_path)

    vf_parts = []
    if vertical:
        vf_parts.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
    vf_parts.append(f"subtitles='{ass_escaped}'")
    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp), "-i", video_path,
        "-frames:v", "1", "-q:v", "3",
        "-vf", vf,
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"Preview frame render failed:\n{result.stderr[-1500:]}")
    return out_path


def render_music_preview(video_path: str, bg_music_path: str, bg_music_volume: float,
                          out_path: str, timestamp: float = 3.0, duration: float = 6.0) -> str:
    """Mix a few seconds of the video's real audio with the background music at the
    chosen volume, so you can hear the balance before rendering full clips."""
    filter_complex = (
        f"[1:a]volume={bg_music_volume}[bgvol];"
        f"[0:a][bgvol]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp), "-i", video_path,
        "-stream_loop", "-1", "-i", bg_music_path,
        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-c:a", "aac", "-b:a", "160k",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"Music preview render failed:\n{result.stderr[-1500:]}")
    return out_path
