"""Cuts a segment out of the source video and burns in the .ass subtitles, via ffmpeg.
Optionally mixes in a looping background music track at a chosen volume."""
import subprocess
from .utils import safe_ffmpeg_path


def create_clip(video_path: str, start: float, end: float, ass_path: str, out_path: str,
                 preset: str = "veryfast", vertical: bool = False,
                 bg_music_path: str = None, bg_music_volume: float = 0.3):
    """
    preset: ffmpeg x264 preset. 'veryfast'/'ultrafast' render much quicker at a slightly
    larger file size for the same quality - a good trade for short clips.
    vertical: if True, center-crop the clip to a 1080x1920 (9:16) frame -
    the standard TikTok/Reels/Shorts format - before burning in subtitles.
    bg_music_path: optional path to a music file. It's looped to cover the whole clip
    (so a short music file still works on a 60s clip) and mixed under the original
    audio - the original audio/dialogue is left untouched at full volume.
    bg_music_volume: 0.0-1.0, how loud the background music is relative to itself
    (applied before mixing).
    """
    duration = max(0.1, end - start)
    ass_escaped = safe_ffmpeg_path(ass_path)

    vf_parts = []
    if vertical:
        # Scale so the shorter side fills 1080x1920, then crop the overflow from center.
        vf_parts.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
    vf_parts.append(f"subtitles='{ass_escaped}'")
    video_filter = ",".join(vf_parts)

    if bg_music_path:
        # Loop the music indefinitely; the global -t below caps total output length,
        # so it always covers the clip regardless of the music file's own length.
        filter_complex = (
            f"[0:v]{video_filter}[vout];"
            f"[1:a]volume={bg_music_volume}[bgvol];"
            f"[0:a][bgvol]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-i", video_path,
            "-stream_loop", "-1", "-i", bg_music_path,
            "-t", str(duration),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", preset, "-crf", "22",
            "-threads", "0",
            "-c:a", "aac", "-b:a", "160k",
            out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),          # seek BEFORE -i = fast (keyframe-ish) seek
            "-i", video_path,
            "-t", str(duration),
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", preset, "-crf", "22",
            "-threads", "0",            # use all CPU cores for encoding
            "-c:a", "aac", "-b:a", "128k",
            out_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for clip {out_path}:\n{result.stderr[-2000:]}")
    return out_path
