"""Small shared helpers."""
import os
import subprocess
import json


def ensure_dirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def hex_to_ass_color(hex_color: str) -> str:
    """Convert '#RRGGBB' to ASS subtitle color format '&H00BBGGRR'."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        hex_color = "FFFFFF"
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H00{b}{g}{r}".upper()


def format_ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:01d}:{m:02d}:{s:05.2f}"


def format_mmss(seconds: float) -> str:
    """Human-readable m:ss / h:mm:ss for UI labels (not ASS subtitle timing)."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_timestamp(ts: str) -> float:
    """Parse 's', 'm:ss', or 'h:mm:ss' into seconds. Also accepts plain seconds."""
    ts = ts.strip()
    parts = ts.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"Couldn't parse timestamp '{ts}' - use m:ss or h:mm:ss")

    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        m, s = nums
        return m * 60 + s
    if len(nums) == 3:
        h, m, s = nums
        return h * 3600 + m * 60 + s
    raise ValueError(f"Couldn't parse timestamp '{ts}' - use m:ss or h:mm:ss")


def parse_time_range(line: str) -> tuple:
    """Parse a line like '8:30-9:48' or '8:30 to 9:48' into (start_seconds, end_seconds)."""
    line = line.strip()
    if not line:
        raise ValueError("Empty line")

    normalized = line.replace("–", "-").replace(" to ", "-")
    if "-" not in normalized:
        raise ValueError(f"'{line}' - expected a range like 8:30-9:48")

    start_str, end_str = normalized.split("-", 1)
    start = parse_timestamp(start_str)
    end = parse_timestamp(end_str)
    if end <= start:
        raise ValueError(f"'{line}' - end must be after start")
    return start, end


def safe_ffmpeg_path(path: str) -> str:
    """Escape a filesystem path for use inside an ffmpeg -vf subtitles='...' filter,
    which is picky about Windows drive letters and backslashes."""
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace(":", r"\:")
    return p


def get_video_resolution(video_path: str, fallback=(1920, 1080)) -> tuple:
    """Probe the source video's width/height via ffprobe, so subtitle sizing
    can match the actual output frame instead of assuming a fixed resolution."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json", video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        info = json.loads(result.stdout)
        stream = info["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except Exception:
        return fallback


def get_video_duration(video_path: str):
    """Probe total duration in seconds via ffprobe. Returns None if it can't be determined."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except Exception:
        return None
