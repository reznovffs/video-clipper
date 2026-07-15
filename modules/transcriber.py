"""
Transcription using faster-whisper (CTranslate2 backend).

Why faster-whisper instead of openai-whisper:
- Same model weights / accuracy as OpenAI Whisper, but 4-10x faster on CPU
  (int8 quantization) and faster on GPU too. This is the single biggest
  lever for cutting down processing time on long videos.
- Built-in VAD (voice activity detection) filtering skips silent stretches
  instead of wasting time transcribing dead air - very common in podcasts/
  streams with pauses.
- Results are also cached to disk per (video, model size), so re-running
  the app on the same video (e.g. just to change subtitle style/colors)
  reuses the existing transcript instead of re-transcribing from scratch.
"""
import os
import json
import hashlib

from faster_whisper import WhisperModel

_model_cache = {}
CACHE_DIR = os.path.join("temp", "transcript_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _pick_device_and_compute_type():
    """Use GPU if available (much faster), otherwise fast int8 on CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def load_model(model_size: str = "base") -> WhisperModel:
    device, compute_type = _pick_device_and_compute_type()
    key = (model_size, device, compute_type)
    if key not in _model_cache:
        _model_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _model_cache[key]


def _cache_key(video_path: str, model_size: str) -> str:
    stat = os.stat(video_path)
    raw = f"{os.path.abspath(video_path)}|{stat.st_size}|{stat.st_mtime}|{model_size}"
    return hashlib.md5(raw.encode()).hexdigest()


def transcribe_video(video_path: str, model_size: str = "base", use_cache: bool = True) -> dict:
    """
    Transcribe a video/audio file with word-level timestamps.
    Returns the same shape as before: {"segments": [{"start","end","text","words":[...]}]}
    so the rest of the pipeline (highlight_detector.py etc.) doesn't need to change.
    """
    cache_path = os.path.join(CACHE_DIR, _cache_key(video_path, model_size) + ".json")

    if use_cache and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    model = load_model(model_size)
    segments_gen, _info = model.transcribe(
        video_path,
        word_timestamps=True,
        vad_filter=True,             # skip silence -> less audio to process, cleaner highlights
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    segments = []
    for seg in segments_gen:
        words = [
            {"word": w.word, "start": w.start, "end": w.end}
            for w in (seg.words or [])
        ]
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "words": words,
        })

    result = {"segments": segments}

    if use_cache:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f)

    return result
