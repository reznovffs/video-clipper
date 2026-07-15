"""
AI Video Clipper — local desktop app.

Flow, organized as tabs so it's not one giant overwhelming page:
  Tab 1: Upload, transcribe, find/pick highlight candidates (or add your own by timestamp)
  Tab 2: Subtitle style, with a live preview frame so you're not guessing
  Tab 3: Optional background music, with a live audio preview of the volume mix
  Tab 4: Export settings + the actual render

Everything runs locally. No accounts, no cloud calls, no payments.
"""
import os
import traceback

import gradio as gr

from modules.transcriber import transcribe_video
from modules.highlight_detector import find_highlights, flatten_words
from modules.subtitles import SubtitleStyle, generate_ass
from modules.clipper import create_clip
from modules.preview import render_style_preview, render_music_preview, pick_preview_timestamp
from modules.utils import ensure_dirs, get_video_resolution, format_mmss, parse_time_range

OUTPUT_DIR = "output"
TEMP_DIR = "temp"
PREVIEW_DIR = os.path.join(TEMP_DIR, "preview")
ensure_dirs(OUTPUT_DIR, TEMP_DIR, PREVIEW_DIR)

# Fonts commonly used for TikTok/YouTube Shorts-style captions.
# "(built-in)" ones are typically preinstalled on Windows and will just work.
# The rest are free Google Fonts widely used for caption styling, but need to be
# downloaded and installed on your system first (see README) - libass silently
# falls back to a default font if the chosen one isn't installed, so if a preview
# doesn't look right, that's the most likely reason.
FONT_OPTIONS = [
    "Arial Black (built-in)",
    "Impact (built-in)",
    "Verdana (built-in)",
    "Segoe UI Black (built-in)",
    "Montserrat (install first)",
    "Poppins (install first)",
    "Bebas Neue (install first)",
    "Anton (install first)",
    "Oswald (install first)",
]


def _clean_font_name(label: str) -> str:
    """UI shows 'Montserrat (install first)' - ffmpeg/libass just needs 'Montserrat'."""
    return label.split(" (")[0]


def _candidate_label(c: dict) -> str:
    preview = c["text"].strip()
    if len(preview) > 70:
        preview = preview[:70].rstrip() + "..."
    return (f"[{c['duration']}s | score {c['score']:.1f}] "
            f"{format_mmss(c['start'])}–{format_mmss(c['end'])} — \"{preview}\"")


def _manual_label(start: float, end: float, text: str) -> str:
    preview = text.strip()
    if len(preview) > 60:
        preview = preview[:60].rstrip() + "..."
    tag = f"[MANUAL {format_mmss(start)}–{format_mmss(end)}]"
    return f'{tag} "{preview}"' if preview else tag


def find_highlights_ui(video_path, model_size, durations, candidates_per_duration,
                        use_cache, progress=gr.Progress()):
    if not video_path:
        return "⚠️ Please upload a video first.", gr.update(choices=[], value=[]), None, None

    if not durations:
        return "⚠️ Select at least one clip length.", gr.update(choices=[], value=[]), None, None

    try:
        progress(0.05, desc="Loading Whisper model (first run downloads it)...")
        progress(0.1, desc="Transcribing audio... this can take a while")
        result = transcribe_video(video_path, model_size=model_size, use_cache=use_cache)

        progress(0.6, desc="Transcription done. Scoring candidate moments...")
        words = flatten_words(result)
        if not words:
            return "⚠️ No speech was detected in this video.", gr.update(choices=[], value=[]), None, None

        target_durations = sorted(int(d) for d in durations)
        candidates = find_highlights(
            words, target_durations, num_clips_per_duration=int(candidates_per_duration)
        )

        if not candidates:
            return ("⚠️ Couldn't find good candidate moments automatically. "
                     "You can still add clips manually below using exact timestamps.",
                     gr.update(choices=[], value=[]), words, {})

        candidates.sort(key=lambda c: -c["score"])
        label_map = {_candidate_label(c): c for c in candidates}
        labels = list(label_map.keys())

        progress(1.0, desc="Done")
        status = (f"✅ Found {len(candidates)} candidate clip(s). "
                  f"Check the ones you want, then head to the Subtitle Style tab.")
        return status, gr.update(choices=labels, value=labels[: min(6, len(labels))]), words, label_map

    except Exception:
        traceback.print_exc()
        return "❌ Something went wrong — see the terminal for the full error.", gr.update(choices=[], value=[]), None, None


def add_manual_clips(manual_text, words, label_map, current_selection):
    if not words:
        return ("⚠️ Click 'Find Highlights' first (it transcribes the video - "
                 "needed even if you're only adding manual clips, so subtitles can be generated)."), \
               gr.update(), label_map

    if not manual_text or not manual_text.strip():
        return "⚠️ Enter at least one time range, e.g. 8:30-9:48", gr.update(), label_map

    label_map = dict(label_map or {})
    total_duration = words[-1]["end"] if words else None
    added_labels = []
    errors = []

    for line in manual_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            start, end = parse_time_range(line)
        except ValueError as e:
            errors.append(str(e))
            continue

        start = max(0.0, start)
        if total_duration is not None:
            end = min(total_duration, end)
        if end <= start:
            errors.append(f"'{line}' - out of range or invalid after clamping to video length")
            continue

        window_words = [w for w in words if w["start"] >= start and w["end"] <= end]
        text = " ".join(w["word"] for w in window_words)
        label = _manual_label(start, end, text)

        label_map[label] = {
            "start": start, "end": end,
            "duration": round(end - start),
            "score": None, "text": text,
        }
        added_labels.append(label)

    status_lines = []
    if added_labels:
        status_lines.append(f"✅ Added {len(added_labels)} manual clip(s).")
    if errors:
        status_lines.append("⚠️ " + " | ".join(errors))
    status = "\n".join(status_lines) if status_lines else "Nothing added."

    all_labels = list(label_map.keys())
    new_selection = list(dict.fromkeys((current_selection or []) + added_labels))
    return status, gr.update(choices=all_labels, value=new_selection), label_map


def _current_style(font_label, font_size, text_color, outline_color, position, bold, max_words_per_line):
    return SubtitleStyle(
        font_name=_clean_font_name(font_label),
        font_size=int(font_size),
        primary_color=text_color,
        outline_color=outline_color,
        position=position,
        bold=bold,
        max_words_per_line=int(max_words_per_line),
    )


def update_subtitle_preview(video_path, selected_labels, label_map, font_label, font_size,
                             text_color, outline_color, position, bold, max_words_per_line, vertical):
    if not video_path:
        return None
    try:
        style = _current_style(font_label, font_size, text_color, outline_color, position, bold, max_words_per_line)
        resolution = (1080, 1920) if vertical else get_video_resolution(video_path)

        desired_ts = None
        if selected_labels and label_map and selected_labels[0] in label_map:
            desired_ts = label_map[selected_labels[0]]["start"] + 1.0
        timestamp = pick_preview_timestamp(video_path, desired=desired_ts)

        out_path = os.path.join(PREVIEW_DIR, "style_preview.jpg")
        return render_style_preview(video_path, style, vertical, resolution, out_path, timestamp=timestamp)
    except Exception as e:
        print(f"[warn] subtitle preview failed: {e}")
        return None


def update_music_preview(video_path, selected_labels, label_map, bg_music_path, bg_music_volume):
    if not video_path or not bg_music_path:
        return None
    try:
        desired_ts = None
        if selected_labels and label_map and selected_labels[0] in label_map:
            desired_ts = label_map[selected_labels[0]]["start"] + 1.0
        timestamp = pick_preview_timestamp(video_path, desired=desired_ts)

        out_path = os.path.join(PREVIEW_DIR, "music_preview.m4a")
        return render_music_preview(video_path, bg_music_path, (bg_music_volume or 0) / 100.0,
                                     out_path, timestamp=timestamp, duration=6.0)
    except Exception as e:
        print(f"[warn] music preview failed: {e}")
        return None


def generate_selected_clips(video_path, selected_labels, label_map, words,
                             font_label, font_size, text_color, outline_color,
                             position, bold, max_words_per_line, fast_render,
                             vertical, bg_music_path, bg_music_volume,
                             progress=gr.Progress()):
    if not video_path:
        return "⚠️ Please upload a video first.", []
    if not label_map or not words:
        return "⚠️ Click 'Find Highlights' first.", []
    if not selected_labels:
        return "⚠️ Select at least one candidate clip to render.", []

    try:
        for f in os.listdir(OUTPUT_DIR):
            os.remove(os.path.join(OUTPUT_DIR, f))

        selected = [label_map[l] for l in selected_labels if l in label_map]
        selected.sort(key=lambda c: c["start"])

        style = _current_style(font_label, font_size, text_color, outline_color, position, bold, max_words_per_line)
        output_resolution = (1080, 1920) if vertical else get_video_resolution(video_path)

        out_files = []
        total = len(selected)
        for i, h in enumerate(selected):
            progress(i / total, desc=f"Rendering clip {i + 1}/{total}...")
            ass_path = os.path.join(TEMP_DIR, f"sub_{i}.ass")
            generate_ass(words, h["start"], h["end"], ass_path, style, resolution=output_resolution)

            out_name = f"clip_{i + 1:02d}_{h['duration']}s.mp4"
            out_path = os.path.join(OUTPUT_DIR, out_name)
            try:
                preset = "ultrafast" if fast_render else "veryfast"
                create_clip(video_path, h["start"], h["end"], ass_path, out_path,
                            preset=preset, vertical=vertical,
                            bg_music_path=bg_music_path or None,
                            bg_music_volume=(bg_music_volume or 0) / 100.0)
                out_files.append(out_path)
            except Exception as e:
                print(f"[warn] failed to render clip {i}: {e}")

        progress(1.0, desc="Done!")
        if not out_files:
            return "❌ All clip renders failed — check the terminal log for the ffmpeg error.", []

        return f"✅ Generated {len(out_files)} clip(s). Saved in the '{OUTPUT_DIR}' folder.", out_files

    except Exception:
        traceback.print_exc()
        return "❌ Something went wrong — see the terminal for the full error.", []


with gr.Blocks(title="AI Video Clipper", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        "# 🎬 AI Video Clipper\n"
        "Turn a long video into short, subtitled clips — fully local, no accounts, no cloud."
    )

    words_state = gr.State(None)
    label_map_state = gr.State(None)

    with gr.Tabs():
        # ---------------------------------------------------------------- TAB 1
        with gr.Tab("1. Upload & Highlights"):
            video_input = gr.Video(label="Upload your video")

            with gr.Accordion("Transcription & candidate settings", open=True):
                with gr.Row():
                    model_size = gr.Dropdown(
                        ["tiny", "base", "small", "medium"], value="base",
                        label="Whisper model", info="Bigger = more accurate, slower.",
                    )
                    candidates_per_duration = gr.Slider(
                        2, 10, value=5, step=1, label="Candidates per length",
                    )
                durations = gr.CheckboxGroup(
                    ["15", "30", "60"], value=["15", "30", "60"], label="Clip lengths (seconds)"
                )
                use_cache = gr.Checkbox(
                    value=True, label="Reuse transcript if this exact video was processed before",
                )

            find_btn = gr.Button("🔍 Find Highlights", variant="primary")
            find_status = gr.Textbox(label="Status", interactive=False, lines=2)

            with gr.Accordion("Already know a part you want? Add it manually", open=False):
                manual_clips_input = gr.Textbox(
                    lines=3, label="Time ranges (one per line)",
                    placeholder="8:30-9:48\n12:00-12:45\n1:02:10-1:03:00",
                    info="m:ss or h:mm:ss. Requires 'Find Highlights' to have run first.",
                )
                add_manual_btn = gr.Button("Add Manual Clip(s)")
                manual_status = gr.Textbox(label="Manual add status", interactive=False)

            gr.Markdown("**Pick the clips you want to render:**")
            candidate_picker = gr.CheckboxGroup(choices=[], value=[], label=None, show_label=False)

        # ---------------------------------------------------------------- TAB 2
        with gr.Tab("2. Subtitle Style"):
            with gr.Row():
                with gr.Column(scale=1):
                    font_name = gr.Dropdown(
                        FONT_OPTIONS, value=FONT_OPTIONS[0], label="Font",
                        info="Popular TikTok/Shorts caption fonts. '(install first)' fonts "
                             "need to be installed on your system — see README.",
                    )
                    font_size = gr.Slider(20, 90, value=42, step=2, label="Font size")
                    with gr.Row():
                        text_color = gr.ColorPicker(value="#FFFFFF", label="Text color")
                        outline_color = gr.ColorPicker(value="#000000", label="Outline color")
                    position = gr.Radio(
                        ["bottom", "center", "top"], value="bottom", label="Position"
                    )
                    bold = gr.Checkbox(value=True, label="Bold")
                    max_words_per_line = gr.Slider(
                        2, 8, value=4, step=1, label="Words per subtitle burst",
                        info="Lower = short punchy captions. Higher = full sentences.",
                    )
                    vertical = gr.Checkbox(
                        value=False, label="Crop to vertical 9:16 (TikTok / Reels / Shorts)",
                    )
                with gr.Column(scale=1):
                    gr.Markdown("**Live preview** — updates automatically as you change settings.")
                    style_preview_image = gr.Image(label=None, show_label=False, interactive=False)

        # ---------------------------------------------------------------- TAB 3
        with gr.Tab("3. Background Music (optional)"):
            gr.Markdown(
                "Original dialogue always stays at full volume. The track loops to cover "
                "each clip's full length and is applied to every clip you generate."
            )
            bg_music_file = gr.Audio(type="filepath", label="Background music track")
            bg_music_volume = gr.Slider(0, 100, value=25, step=5, label="Background music volume (%)")
            preview_music_btn = gr.Button("🔊 Preview Music Mix")
            music_preview_audio = gr.Audio(label="Preview (6s mix)", interactive=False)

        # ---------------------------------------------------------------- TAB 4
        with gr.Tab("4. Export"):
            fast_render = gr.Checkbox(
                value=False, label="Fast render mode (larger file size, quicker export)",
            )
            generate_btn = gr.Button("🚀 Generate Selected Clips", variant="primary")
            status = gr.Textbox(label="Export status", interactive=False)
            output_files = gr.File(label="Generated clips (also saved to /output)", file_count="multiple")

    # ---------------------------------------------------------------- Wiring

    find_btn.click(
        find_highlights_ui,
        inputs=[video_input, model_size, durations, candidates_per_duration, use_cache],
        outputs=[find_status, candidate_picker, words_state, label_map_state],
    )

    add_manual_btn.click(
        add_manual_clips,
        inputs=[manual_clips_input, words_state, label_map_state, candidate_picker],
        outputs=[manual_status, candidate_picker, label_map_state],
    )

    # Live subtitle preview: regenerate on any style-affecting change.
    # Sliders use .release() (fires once you let go) so dragging doesn't spam ffmpeg.
    preview_inputs = [video_input, candidate_picker, label_map_state, font_name, font_size,
                       text_color, outline_color, position, bold, max_words_per_line, vertical]
    gr.on(
        triggers=[video_input.change, candidate_picker.change, font_name.change,
                  font_size.release, text_color.change, outline_color.change,
                  position.change, bold.change, max_words_per_line.release, vertical.change],
        fn=update_subtitle_preview,
        inputs=preview_inputs,
        outputs=[style_preview_image],
    )

    # Music preview: on demand via button, plus auto on upload / volume release.
    music_preview_inputs = [video_input, candidate_picker, label_map_state, bg_music_file, bg_music_volume]
    gr.on(
        triggers=[preview_music_btn.click, bg_music_file.change, bg_music_volume.release],
        fn=update_music_preview,
        inputs=music_preview_inputs,
        outputs=[music_preview_audio],
    )

    generate_btn.click(
        generate_selected_clips,
        inputs=[
            video_input, candidate_picker, label_map_state, words_state,
            font_name, font_size, text_color, outline_color, position, bold,
            max_words_per_line, fast_render, vertical,
            bg_music_file, bg_music_volume,
        ],
        outputs=[status, output_files],
    )

if __name__ == "__main__":
    demo.launch()
