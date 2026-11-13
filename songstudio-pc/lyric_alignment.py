"""Non-destructive timing assistance for owner-supplied, untimed song lyrics.

Whisper provides *approximate* phrase intervals, not forced alignment. Align
the owner's exact lines monotonically to the existing ASR draft and explicitly
flag weak/interpolated timing. Never replace the owner's words with ASR guesses,
never publish to song catalogs, and never claim syllable-perfect timing.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from math import isfinite
from statistics import median
import re
import unicodedata

MAX_LINES = 350
MAX_TEXT_LENGTH = 20000
TIMESTAMP = re.compile(r"^\s*\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")


def _chars(text):
    # Thai vowels and tone marks are combining marks; isalnum() alone would
    # discard those and reduce the quality of matching Thai phrases.
    return "".join(char.casefold() for char in unicodedata.normalize("NFC", text)
                   if char.isalnum() or unicodedata.category(char).startswith("M"))


def _stamp(seconds):
    minutes, sec = divmod(round(max(0.0, seconds) * 100) / 100, 60)
    return f"[{int(minutes):02d}:{sec:05.2f}]"


def _read_owner_lines(text):
    if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
        raise ValueError("เนื้อร้องที่วางต้องเป็นข้อความไม่เกิน 20,000 ตัวอักษร")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("กรุณาวางเนื้อเพลงที่ถูกต้องทีละบรรทัดก่อนกด AI จัดเวลา")
    if len(lines) > MAX_LINES:
        raise ValueError("เนื้อเพลงมีจำนวนบรรทัดมากเกินไป กรุณาแบ่งเป็นช่วงสั้นลง")
    if any(TIMESTAMP.match(line) for line in lines):
        raise ValueError("ช่องนี้รับเนื้อเพลงที่ยังไม่มีเวลา หากมี [นาที:วินาที] อยู่แล้ว ให้แก้เวลาในช่อง LRC โดยตรง")
    # Interlude rename is an explicit owner-selected product label, not an
    # AI transcription of spoken words.
    return [line.replace("[เสียงดนตรี]", "[X-Stage Karaoke]") for line in lines]


def align_lyrics(owner_text, asr_draft):
    """Return a review-only LRC with owner's exact words and timing warnings."""
    lines = _read_owner_lines(owner_text)
    segments = asr_draft.get("lines", []) if isinstance(asr_draft, dict) else []
    if not isinstance(segments, list) or not segments:
        raise ValueError("ยังไม่มีผลถอดเสียง AI ที่มีเวลาจริงสำหรับจับคู่กับเนื้อเพลง")
    asr_chars, times = [], []
    segment_speeds = []
    for segment in sorted((s for s in segments if isinstance(s, dict)),
                          key=lambda s: float(s.get("startTime", 0))):
        text = str(segment.get("text") or "")
        normalized = _chars(text)
        try:
            start, end = float(segment["startTime"]), float(segment["endTime"])
        except (ValueError, TypeError, KeyError):
            continue
        if (not isfinite(start) or not isfinite(end) or
                start < 0 or end <= start or end > 24 * 3600 or not normalized):
            continue
        segment_speeds.append((end - start) / len(normalized))
        for j, char in enumerate(normalized):
            asr_chars.append(char)
            times.append(start + (end - start) * j / len(normalized))
    if not asr_chars:
        raise ValueError("AI ไม่มีช่วงคำร้องที่อ่านได้ กรุณาตรวจว่าเสียงต้นฉบับมีคนร้อง")
    speech_speed = min(.65, max(.06, median(segment_speeds)))
    owner_chars, mapping, counts = [], [], []
    for i, line in enumerate(lines):
        normalized = _chars(line)
        if not normalized:
            raise ValueError(f"บรรทัดที่ {i+1} ไม่มีข้อความเนื้อร้องที่จับคู่ได้")
        counts.append(len(normalized))
        for j, char in enumerate(normalized):
            owner_chars.append(char)
            mapping.append((i, j))
    # SequenceMatcher is order-preserving: repeated choruses cannot go
    # backwards on the recording. For very long tracks, autojunk prevents
    # pathological matching on repeated single letters.
    matcher = SequenceMatcher(None, "".join(asr_chars), "".join(owner_chars),
                              autojunk=max(len(asr_chars), len(owner_chars)) > 3500)
    matched = [0] * len(lines)
    candidates = [[] for _ in lines]
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            target_line, target_char = mapping[block.b + k]
            source_idx = block.a + k
            matched[target_line] += 1
            candidates[target_line].append(
                times[source_idx] - target_char * speech_speed)
    coverage = [min(1., matched[i] / counts[i]) for i in range(len(lines))]
    # Refuse to fabricate a timeline when Whisper bears too little resemblance
    # to the pasted lyrics (e.g., instrumental-only recordings or wrong song).
    strong = [i for i, score in enumerate(coverage)
              if score >= .32 and matched[i] >= 2]
    overall = sum(matched) / len(owner_chars)
    if not strong or overall < .16:
        raise ValueError(
            "จับคู่เนื้อร้องกับเสียงไม่มั่นใจเพียงพอ · โปรดตรวจว่าเลือกเพลงถูกต้อง "
            "มีเสียงคนร้อง และร่าง Whisper ถอดเสียงได้ ก่อนจัดเวลาใหม่")
    anchors = {}
    for i in strong:
        # Median of matched character candidates resists one off-target word.
        anchors[i] = max(0.0, median(candidates[i]))
    # Enforce chronological anchor progression; preserve ASR positions in
    # their original order instead of reordering user-supplied lines.
    last = -0.01
    for i in sorted(anchors):
        anchors[i] = max(anchors[i], last + .01)
        last = anchors[i]
    starts = [None] * len(lines)
    for i, value in anchors.items():
        starts[i] = value
    keys = sorted(anchors)
    for i in range(len(lines)):
        if starts[i] is not None:
            continue
        previous = max((j for j in keys if j < i), default=None)
        following = next((j for j in keys if j > i), None)
        if previous is not None and following is not None:
            weights = [max(1, n) for n in counts[previous:following]]
            portion = sum(weights[:i-previous]) / sum(weights)
            starts[i] = anchors[previous] + (
                anchors[following] - anchors[previous]) * portion
        elif previous is not None:
            starts[i] = anchors[previous] + speech_speed * sum(counts[previous:i])
        elif following is not None:
            starts[i] = max(0.0, anchors[following] -
                            speech_speed * sum(counts[i:following]))
    for i in range(1, len(starts)):
        # LRC has start timestamps only. Keep them strictly monotonic while
        # still requiring a human to confirm spacing by listening.
        starts[i] = max(starts[i], starts[i-1] + .01)
    issues = []
    uncertain = 0
    for i, score in enumerate(coverage):
        if i not in anchors or score < .62:
            uncertain += 1
            if len(issues) < 12:
                reason = ("ประเมินเวลาระหว่างท่อน" if i not in anchors
                          else "พบคำตรงกันเพียงบางส่วน")
                issues.append(f"บรรทัด {i+1}: {reason} · ควรฟังตรวจ")
    lrc = "\n".join(_stamp(start) + line for start, line in zip(starts, lines)) + "\n"
    return {
        "rawLrc": lrc, "lines": len(lines), "uncertain": uncertain,
        "matchedCharacters": sum(matched), "totalCharacters": len(owner_chars),
        "issues": issues,
        "requiresReview": True,
        "message": (
            f"จัดเวลาเบื้องต้น {len(lines)} บรรทัด · "
            f"ต้องฟังตรวจ {uncertain} บรรทัด · "
            "ใช้คำร้องที่วางไว้ ไม่ใช้คำที่ Whisper เดาแทน"
        ),
    }
