"""
Generates burned-in-ready subtitle files (.ass) for a clip, with full style
control: font, size, colors, outline, bold, and vertical position.

.ass (Advanced SubStation Alpha) is used instead of .srt because ffmpeg's
subtitles filter can apply per-style colors/fonts/positioning directly from
the .ass header - .srt has no styling support.
"""
from dataclasses import dataclass
from .utils import hex_to_ass_color, format_ass_timestamp

# vertical position -> ASS alignment codes (numpad layout)
_ALIGN_MAP = {"bottom": 2, "center": 5, "top": 8}


@dataclass
class SubtitleStyle:
    font_name: str = "Arial"
    font_size: int = 42
    primary_color: str = "#FFFFFF"   # text color, hex
    outline_color: str = "#000000"   # outline/stroke color, hex
    bold: bool = True
    position: str = "bottom"         # "bottom" | "center" | "top"
    outline_width: int = 3
    max_words_per_line: int = 4      # smaller = shorter, punchier subtitle bursts
    margin_v: int = 60               # vertical margin from that edge, in px


def _group_words_into_lines(words: list[dict], clip_start: float, clip_end: float, max_words: int):
    lines = []
    chunk = []
    for w in words:
        if clip_start <= w["start"] <= clip_end:
            chunk.append(w)
            if len(chunk) >= max_words:
                lines.append(chunk)
                chunk = []
    if chunk:
        lines.append(chunk)
    return lines


def generate_ass(words: list[dict], clip_start: float, clip_end: float, out_path: str,
                  style: SubtitleStyle, resolution: tuple = (1080, 1920)):
    """Write an .ass subtitle file, with timestamps shifted to be relative to clip_start.
    `resolution` should match the actual output frame (e.g. (1080,1920) for a vertical
    crop, or the source video's own width/height for uncropped clips) so font sizing
    scales correctly relative to the real video frame."""
    primary = hex_to_ass_color(style.primary_color)
    outline = hex_to_ass_color(style.outline_color)
    align = _ALIGN_MAP.get(style.position, 2)
    bold_flag = -1 if style.bold else 0
    res_x, res_y = resolution

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_name},{style.font_size},{primary},{primary},{outline},&H00000000,{bold_flag},0,0,0,100,100,0,0,1,{style.outline_width},0,{align},40,40,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Text
"""

    lines = _group_words_into_lines(words, clip_start, clip_end, style.max_words_per_line)
    events = []
    for line in lines:
        start = line[0]["start"] - clip_start
        end = line[-1]["end"] - clip_start
        text = " ".join(w["word"].strip() for w in line).replace("\n", " ")
        events.append(f"Dialogue: 0,{format_ass_timestamp(start)},{format_ass_timestamp(end)},Default,{text}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))

    return out_path
