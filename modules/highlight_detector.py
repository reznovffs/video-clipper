"""
Heuristic 'interesting moment' detector.

There's no local, free, reliable model for judging what's "interesting" in
arbitrary speech, so this uses an anchor-based approach instead of blindly
scoring every stretch of the video:

  1. Find "anchors" - sentences that contain a real hook: a substantive
     question (not filler like "right?" / "you know?"), strong hook/emphasis
     language, or an exclamation.
  2. Build one candidate clip per anchor per target duration, with a bit of
     lead-in before the hook (so there's context) rather than starting the
     clip exactly on it.
  3. Filter out anything that isn't anchored on a real hook. Boring stretches
     of conversation don't produce candidates at all unless the video
     genuinely has nothing better to offer for a given duration.

This means a plain back-and-forth chat won't get clipped, but the moment
someone asks "do you think it's possible for humans to use 100% of their
brain?" (a real, substantive question) or drops emphatic language, that
becomes a candidate.
"""

HOOK_WORDS = {
    "amazing", "crazy", "secret", "never", "always", "best", "worst",
    "mistake", "incredible", "insane", "shocking", "actually", "honestly",
    "truth", "important", "key", "huge", "massive", "wrong", "right",
    "problem", "solution", "reveal", "why", "how", "story", "moment",
    "changed", "failed", "success", "money", "free", "warning", "stop",
    "wait", "listen", "believe", "literally", "wild", "brutal",
}

# A "real" question needs at least this many words - filters out filler tags
# like "right?", "ok?", "you know?" which end in '?' but aren't actual hooks.
QUESTION_MIN_WORDS = 4
FILLER_QUESTION_TAILS = {
    "right", "okay", "ok", "yeah", "huh", "you know", "isn't it", "don't you think",
}


def flatten_words(whisper_result: dict) -> list[dict]:
    """Turn whisper's segments -> a flat list of {word, start, end}."""
    words = []
    for seg in whisper_result.get("segments", []):
        for w in seg.get("words", []) or []:
            word_text = (w.get("word") or "").strip()
            if not word_text:
                continue
            words.append({
                "word": word_text,
                "start": float(w["start"]),
                "end": float(w["end"]),
            })
    return words


def _score_window(window_words: list[dict], duration: float) -> float:
    """Raw engagement score for a window (not yet normalized by duration)."""
    if not window_words:
        return -999

    text = " ".join(w["word"] for w in window_words).lower()
    score = 0.0

    for hw in HOOK_WORDS:
        if hw in text:
            score += 3.0

    score += text.count("?") * 2.0
    score += text.count("!") * 2.0

    words_per_sec = len(window_words) / duration if duration > 0 else 0
    score += words_per_sec * 1.5

    if words_per_sec < 1.0:
        score -= 5.0

    return score


def _density(window_words: list[dict], duration: float) -> float:
    """Score normalized by duration, so candidates of different target
    lengths (15s/30s/60s) can be compared and thresholded consistently."""
    return _score_window(window_words, duration) / max(duration, 1.0)


def _segment_sentences(words: list[dict]) -> list[list[dict]]:
    """Split the flat word list into sentence-like chunks based on terminal punctuation."""
    sentences = []
    current = []
    for w in words:
        current.append(w)
        if w["word"].strip().endswith((".", "!", "?")):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return sentences


def _is_real_question(sentence_words: list[dict]) -> bool:
    if not sentence_words:
        return False
    last_word = sentence_words[-1]["word"].strip()
    if not last_word.endswith("?"):
        return False
    if len(sentence_words) < QUESTION_MIN_WORDS:
        return False
    tail = " ".join(w["word"].strip(".,!?").lower() for w in sentence_words[-2:])
    if tail in FILLER_QUESTION_TAILS:
        return False
    return True


def _find_anchors(words: list[dict]) -> list[dict]:
    """Return sentences that contain a real hook, each with a weight reflecting
    how strong a hook it is (substantive question > hook word > exclamation)."""
    anchors = []
    for sentence in _segment_sentences(words):
        if not sentence:
            continue
        text = " ".join(w["word"] for w in sentence).lower()
        is_question = _is_real_question(sentence)
        has_hook_word = any(hw in text for hw in HOOK_WORDS)
        has_exclaim = "!" in text

        if is_question:
            weight = 3.0
        elif has_hook_word:
            weight = 2.0
        elif has_exclaim:
            weight = 1.0
        else:
            continue  # not a hook - skip, don't anchor a candidate here

        anchors.append({
            "start": sentence[0]["start"],
            "end": sentence[-1]["end"],
            "weight": weight,
        })
    return anchors


def _windows_from_anchors(words: list[dict], anchors: list[dict], duration: float,
                           total_duration: float, lead_in_ratio: float = 0.25) -> list[dict]:
    """Build one candidate window per anchor: starts a bit before the hook (for
    context) and runs for `duration`, clamped to the video's bounds."""
    candidates = []
    seen_starts = set()

    for anchor in anchors:
        lead_in = duration * lead_in_ratio
        start = max(0.0, anchor["start"] - lead_in)
        end = min(total_duration, start + duration)
        start = max(0.0, end - duration)  # re-clamp near the end of the video

        key = round(start, 1)
        if key in seen_starts:
            continue
        seen_starts.add(key)

        window_words = [w for w in words if w["start"] >= start and w["end"] <= end]
        if not window_words:
            continue

        density = _density(window_words, duration) + anchor["weight"] * 1.5  # bonus for being a real hook
        text = " ".join(w["word"] for w in window_words)
        candidates.append({
            "start": start, "end": end, "duration": duration,
            "score": round(density, 2), "text": text,
        })

    return candidates


def find_highlights(
    words: list[dict],
    target_durations: list[int],
    num_clips_per_duration: int = 2,
    min_score_density: float = 1.2,
) -> list[dict]:
    """
    Returns a list of dicts: {start, end, duration, score, text}, sorted by start time.

    min_score_density: candidates scoring below this (per-second engagement density)
    are treated as "boring" and excluded - unless nothing in a given duration clears
    the bar, in which case the least-boring options are used as a fallback so the app
    doesn't come back completely empty-handed on quieter videos.
    """
    if not words:
        return []

    total_duration = words[-1]["end"]
    anchors = _find_anchors(words)

    all_candidates = []
    for duration in target_durations:
        all_candidates.extend(_windows_from_anchors(words, anchors, duration, total_duration))

    selected = []
    for duration in target_durations:
        duration_candidates = sorted(
            [c for c in all_candidates if c["duration"] == duration],
            key=lambda c: -c["score"],
        )

        strong = [c for c in duration_candidates if c["score"] >= min_score_density]
        pool = strong if strong else duration_candidates[: max(3, num_clips_per_duration)]

        picked = []
        for c in pool:
            if len(picked) >= num_clips_per_duration:
                break
            overlaps = any(not (c["end"] <= p["start"] or c["start"] >= p["end"]) for p in picked)
            if not overlaps:
                picked.append(c)
        selected.extend(picked)

    selected.sort(key=lambda c: c["start"])
    return selected
