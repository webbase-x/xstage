"""Offline AI transcription drafts for X-Stage Song Studio PC.

Whisper.cpp multilingual ASR transcribes *audible human voices*, NOT MIDI notes.
Results may be wrong or hallucinated on music. Store only as unverified drafts
in the Windows user's private AppData, never auto-publish to song catalogs.
The shipped Ready ZIP carries the CLI and model; no runtime model download.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

AUDIO_SUFFIXES = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".wma", ".flac", ".ogg", ".oga"}
LANGUAGES = {"th", "en", "auto"}
MAX_AUDIO_SECONDS = 20 * 60
MAX_PROCESS_SECONDS = 60 * 60


def resources(runtime: Path) -> tuple[Path, Path]:
    runtime = Path(runtime)
    return runtime / "whisper" / "whisper-cli.exe", runtime / "models" / "ggml-base.bin"


def readiness(runtime: Path) -> tuple[bool, str]:
    """Give a clear packaging error instead of a disabled button with no cause."""
    cli, model = resources(runtime)
    if not cli.is_file():
        return False, "ไม่พบ whisper-cli.exe ใน .runtime/whisper · โปรดใช้ PC Ready ZIP ที่แตกไฟล์ครบ"
    if not model.is_file():
        return False, "ไม่พบโมเดล ggml-base.bin ใน .runtime/models · โปรดใช้ PC Ready ZIP รุ่นเต็ม"
    try:
        if model.stat().st_size <= 100_000_000:
            return False, "โมเดล Whisper ไม่สมบูรณ์ · ดาวน์โหลด PC Ready ZIP ใหม่แล้วแตกทั้งหมด"
    except OSError as exc:
        return False, "ตรวจโมเดล Whisper ไม่ได้: " + str(exc)
    return True, ""


def available(runtime: Path) -> bool:
    return readiness(runtime)[0]


def _source_key(source: Path) -> str:
    original = Path(source).expanduser().resolve()
    stat = original.stat()
    identity = f"{str(original).casefold()}\0{stat.st_size}\0{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def draft_path(data_dir: Path, source: Path) -> Path:
    return Path(data_dir) / "ai-lyrics-drafts" / (_source_key(source) + ".json")


def load_draft(data_dir: Path, source: Path):
    try:
        file = draft_path(data_dir, source)
        result = json.loads(file.read_text(encoding="utf-8"))
        if (result.get("source") != "AI_DRAFT_UNVERIFIED"
                or not isinstance(result.get("lines"), list)
                or not result["lines"]):
            return None
        return result
    except (ValueError, OSError, KeyError):
        return None


def json_to_draft(payload: dict, code: str, language: str) -> dict:
    segments = payload.get("transcription")
    if not isinstance(segments, list):
        raise ValueError("AI ไม่ส่งรายการคำร้องที่อ่านได้")
    result = []
    for segment in segments[:2500]:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "").strip()
        if not text or text.lower() in ("[music]", "[silence]", "(music)", "♪"):
            continue
        offsets = segment.get("offsets") or {}
        start, end = offsets.get("from"), offsets.get("to")
        if not isinstance(start, (float, int)) or not isinstance(end, (float, int)):
            continue
        start, end = round(start / 1000, 3), round(end / 1000, 3)
        if start < 0 or end <= start or end > MAX_AUDIO_SECONDS + 30:
            continue
        result.append({"startTime": start, "endTime": end, "text": text})
    if not result:
        raise ValueError("AI ไม่พบเสียงร้องที่ถอดเป็นคำได้ · ไม่สร้างเนื้อร้องจากเสียงดนตรี")
    result.sort(key=lambda entry: entry["startTime"])
    def stamp(seconds):
        mins, sec = divmod(max(0., float(seconds)), 60)
        return f"[{int(mins):02d}:{sec:05.2f}]"
    lrc = "\n".join(stamp(entry["startTime"]) + entry["text"] for entry in result) + "\n"
    return {
        "source": "AI_DRAFT_UNVERIFIED", "songCode": code,
        "language": language, "model": "whisper.cpp ggml-base (multilingual)",
        "requiresReview": True, "lines": result, "rawLrc": lrc,
        "notice": "AI draft only. Do not publish or trust words/timings until manually verified.",
    }


def _run(cmd, cancelled, phase, on_status, *, timeout, environment=None, cwd=None):
    """Run without opening CMD and without a subprocess PIPE deadlock."""
    opts = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, env=environment)
    if cwd is not None:
        opts["cwd"] = str(cwd)
    if os.name == "nt":
        opts["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen([str(c) for c in cmd], **opts)
    started = time.monotonic()
    # Background draining avoids blocking if whisper writes long diagnostics.
    last_output = []
    def drain():
        while True:
            line = process.stderr.readline()
            if not line:
                return
            if len(last_output) >= 80:
                last_output.pop(0)
            last_output.append(line.decode("utf-8", errors="replace").strip())
    worker = threading.Thread(target=drain, daemon=True)
    worker.start()
    try:
        last_message = 0.0
        while process.poll() is None:
            if cancelled.is_set():
                process.terminate()
                raise RuntimeError("ผู้ใช้ยกเลิก AI ถอดเนื้อร้อง")
            elapsed = time.monotonic() - started
            if elapsed > timeout:
                process.terminate()
                raise RuntimeError(phase + " ใช้เวลานานเกินกำหนด")
            if elapsed - last_message >= 3:
                on_status(f"{phase} · ใช้เวลาแล้ว {int(elapsed)} วินาที")
                last_message = elapsed
            cancelled.wait(.35)
        worker.join(timeout=2)
        if process.returncode:
            code = process.returncode & 0xFFFFFFFF
            native_crash = (
                " · Windows 0xC0000409: whisper-cli ปิดตัวเองผิดปกติ"
                " (อาจเกี่ยวกับพาธภาษาไทยหรือข้อผิดพลาดในโปรแกรม Whisper)"
                if code == 0xC0000409 else ""
            )
            raise RuntimeError(phase + " ไม่สำเร็จ (exit " + str(process.returncode) +
                               native_crash + "): " + " / ".join(last_output[-4:])[:450])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stderr.close()


def transcribe(source: Path, code: str, data_dir: Path, runtime: Path,
               ffmpeg: str, cancelled, on_status, language="th") -> dict:
    source = Path(source)
    if source.suffix.lower() not in AUDIO_SUFFIXES:
        raise ValueError("AI ถอดคำร้องได้เฉพาะไฟล์เสียงที่มีคนร้อง ไม่ใช่ MIDI/NCN/KAR แบบดนตรีล้วน")
    if not source.is_file() or source.is_symlink():
        raise ValueError("ไม่พบไฟล์เสียงที่ต้องการถอดคำร้อง")
    if language not in LANGUAGES:
        raise ValueError("ภาษา AI ต้องเป็น th, en หรือ auto")
    cli, model = resources(runtime)
    ready, reason = readiness(runtime)
    if not ready:
        raise RuntimeError("Whisper AI ไม่พร้อม: " + reason)
    output = draft_path(data_dir, source)
    existing = load_draft(data_dir, source)
    if existing:
        return existing
    on_status("AI กำลังตรวจไฟล์เสียงและเตรียมการถอดเนื้อร้อง")
    with tempfile.TemporaryDirectory(prefix="xstage-whisper-") as scratch:
        folder = Path(scratch)
        wav = folder / "audio-16k.wav"
        ffargs = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                  "-i", str(source), "-vn", "-t", str(MAX_AUDIO_SECONDS),
                  "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)]
        _run(ffargs, cancelled, "กำลังแปลงเสียงชั่วคราวสำหรับ AI", on_status, timeout=180)
        if not wav.is_file() or wav.stat().st_size < 32044:
            raise ValueError("ไฟล์เสียงสั้นเกินไปหรือไม่สามารถแปลงเป็น WAV สำหรับ AI")
        name = folder / "draft"
        result_file = folder / "draft.json"
        # whisper.cpp on Windows may terminate (0xC0000409) when the model
        # filename contains Thai/non-ASCII argv bytes, and can also reject an
        # absolute Unicode WAV path as "input file not found" (exit 2).
        # All native CLI arguments must therefore be ASCII *relative* names.
        # Work inside a private temp cwd (CreateProcessW supports Unicode cwd).
        # A same-volume hardlink avoids copying the large model; a cross-drive
        # copy preserves compatibility. Neither touches the source model.
        model_stage = folder / "model.bin"
        on_status("AI กำลังเตรียมโมเดลสำหรับ Whisper โดยไม่เปลี่ยนไฟล์ต้นฉบับ")
        try:
            os.link(model, model_stage)
        except OSError:
            shutil.copyfile(model, model_stage)
        if model_stage.stat().st_size != model.stat().st_size:
            raise RuntimeError("คัดลอกโมเดล Whisper ชั่วคราวไม่สมบูรณ์")
        whisper_cwd = folder
        model_arg = "model.bin"

        # A chosen-language pass can reject sung/dialectal phrases as silence.
        # Retry once with multilingual automatic language detection, using the
        # exact same temporary WAV. Never invent lyrics or publish a draft.
        languages = [language] if language == "auto" else [language, "auto"]
        draft = None
        for attempt, detected_language in enumerate(languages):
            if cancelled.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิก AI ถอดเนื้อร้อง")
            result_file.unlink(missing_ok=True)
            if attempt:
                on_status("ไม่พบคำร้องจากภาษาที่เลือก · ลองตรวจจับภาษาอัตโนมัติอีกครั้ง")
            args = [cli, "-m", model_arg, "-f", "audio-16k.wav",
                    "-l", detected_language, "-oj", "-of", "draft", "-np"]
            on_status("Whisper กำลังถอดเสียงร้องเป็นร่างเนื้อร้อง ไม่แก้ต้นฉบับ")
            _run(args, cancelled, "Whisper AI กำลังถอดเนื้อร้อง", on_status,
                 timeout=MAX_PROCESS_SECONDS, cwd=whisper_cwd)
            if not result_file.is_file():
                raise RuntimeError("Whisper ทำงานเสร็จแต่ไม่สร้างผล JSON · ตรวจไฟล์ AI Runtime")
            payload = json.loads(result_file.read_text(encoding="utf-8-sig"))
            try:
                draft = json_to_draft(payload, code, detected_language)
                break
            except ValueError as exc:
                if "ไม่พบเสียงร้องที่ถอดเป็นคำ" not in str(exc):
                    raise
                if attempt == len(languages) - 1:
                    raise ValueError(
                        "AI ไม่พบคำร้องในไฟล์เสียงนี้ แม้ลองตรวจจับภาษาแล้ว "
                        "· กรุณายืนยันว่าไฟล์มีเสียงคนร้องชัดเจน "
                        "และทดลองไฟล์เสียงร้องแยก (vocals) หากมี") from exc
        if draft is None:
            raise RuntimeError("Whisper ไม่คืนเนื้อร้องที่ใช้ได้")
    # Only a finished JSON text draft persists in the user's private AppData.
    # Transient PCM and Whisper output are removed on TemporaryDirectory exit.
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + "." + os.urandom(6).hex() + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(draft, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    on_status("AI ถอดเนื้อร้องเป็นฉบับร่างแล้ว · กรุณาตรวจและบันทึกด้วยตนเอง")
    return draft
