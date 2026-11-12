"""Offline HTDemucs ONNX music source separation for X-Stage Song Studio PC.

The Windows Ready package embeds ONNX Runtime CPU, NumPy, and an MIT-licensed
htdemucs_fp16weights.onnx model (StemSplit/Meta Demucs). No model download at
runtime, no network requests, and no torch/PyTorch. FFmpeg converts inputs to a
standard 44.1 kHz stereo PCM WAV before running this worker.

Usage:
    python ai_separate.py INPUT_44100_STEREO_PCM16.wav INSTRUMENTAL.wav VOCALS.wav

Progress is written line-by-line as "AI_PROGRESS n/total", consumed by the
parent local engine. Exit code != 0 on any actual separation failure.
"""
from __future__ import annotations

import sys
import time
import wave
from pathlib import Path


def model_path() -> Path:
    return Path(__file__).resolve().parent / ".runtime" / "models" / "htdemucs_fp16weights.onnx"


def separate(input_path: Path, instrumental_path: Path, vocals_path: Path) -> None:
    import numpy as np
    import onnxruntime as ort

    model = model_path()
    if not model.is_file() or model.stat().st_size < 10_000_000:
        raise RuntimeError("Bundled HTDemucs ONNX model is missing or incomplete.")

    with wave.open(str(input_path), "rb") as wav:
        nchannels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frames = wav.getnframes()
        if nchannels != 2 or sample_rate != 44100 or sample_width != 2:
            raise ValueError(
                "Audio input must be 44.1 kHz stereo signed 16-bit WAV. "
                "The local FFmpeg step normally prepares this."
            )
        if frames < 1:
            raise ValueError("Audio file has no samples")
        if frames > 44100 * 60 * 45:
            raise ValueError("Audio exceeds 45 minutes; split into smaller parts first.")
        # NumPy + current stereo samples + two temporary stems fit on normal x64 PCs.
        samples = np.frombuffer(wav.readframes(frames), dtype="<i2").reshape(-1, 2)
        mixture = samples.astype(np.float32).T / 32768.0

    print("AI_STAGE Initializing bundled ONNX Runtime / Demucs model", flush=True)
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(4, max(1, __import__("os").cpu_count() or 2))
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(
        str(model), sess_options=options, providers=["CPUExecutionProvider"]
    )

    input_spec = session.get_inputs()[0]
    output_spec = session.get_outputs()[0]
    segment = 343980  # 7.8 seconds at 44.1 kHz; ONNX graph fixed-shape.
    shape = tuple(input_spec.shape)
    if len(shape) != 3 or shape[1] != 2 or shape[2] != segment:
        raise RuntimeError(f"Unexpected HTDemucs ONNX input shape: {shape!r}")
    if len(output_spec.shape) != 4 or output_spec.shape[1] != 4:
        raise RuntimeError(f"Unexpected HTDemucs ONNX output shape: {output_spec.shape!r}")
    # Meta Demucs stem order: drums, bass, other, vocals.
    vocal_index = 3
    overlap = segment // 4
    stride = segment - overlap
    count = max(1, (frames + stride - 1) // stride)
    vocals = np.zeros((2, frames), dtype=np.float32)
    weights = np.zeros(frames, dtype=np.float32)
    # Avoid attenuating beginning/end of a song; crossfade only when overlapping.
    fade = np.linspace(0, 1, overlap, dtype=np.float32)
    t0 = time.monotonic()

    for i in range(count):
        start = i * stride
        end = min(frames, start + segment)
        if start >= end:
            break
        chunk_len = end - start
        chunk = np.zeros((1, 2, segment), dtype=np.float32)
        chunk[0, :, :chunk_len] = mixture[:, start:end]
        outputs = session.run(None, {input_spec.name: chunk})
        pred = outputs[0]
        if pred.ndim != 4 or pred.shape[1] != 4 or pred.shape[2] != 2:
            raise RuntimeError(f"Unexpected HTDemucs ONNX output dimensions: {pred.shape!r}")
        vocal = pred[0, vocal_index, :, :chunk_len]
        w = np.ones(chunk_len, dtype=np.float32)
        if i > 0:
            fade_len = min(overlap, chunk_len)
            w[:fade_len] = fade[:fade_len]
        if end < frames:
            fade_len = min(overlap, chunk_len)
            w[-fade_len:] = np.minimum(w[-fade_len:], fade[:fade_len][::-1])
        vocals[:, start:end] += vocal * w
        weights[start:end] += w
        print(f"AI_PROGRESS {i + 1}/{count} elapsed={time.monotonic() - t0:.1f}", flush=True)

    np.maximum(weights, np.float32(1e-6), out=weights)
    vocals /= weights
    np.nan_to_num(vocals, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    instrumental = mixture - vocals

    def write_pcm16(target: Path, audio: "np.ndarray") -> None:
        audio = np.clip(audio.T, -1.0, 1.0)
        pcm = (audio * 32767).astype("<i2").tobytes()
        with wave.open(str(target), "wb") as stream:
            stream.setnchannels(2)
            stream.setframerate(44100)
            stream.setsampwidth(2)
            stream.writeframes(pcm)

    print("AI_STAGE Saving instrumental and vocal stems", flush=True)
    write_pcm16(instrumental_path, instrumental)
    write_pcm16(vocals_path, vocals)
    print("AI_COMPLETE", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: ai_separate.py INPUT_WAV INSTRUMENTAL_WAV VOCALS_WAV", file=sys.stderr)
        raise SystemExit(2)
    try:
        separate(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    except Exception as exc:
        print(f"AI_ERROR {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
