"""Generate original, royalty-free test fixtures. No existing songs are copied."""
from pathlib import Path
import math
import struct
import wave


def vlq(value):
    out = [value & 127]
    value >>= 7
    while value:
        out.insert(0, (value & 127) | 128)
        value >>= 7
    return bytes(out)


def meta(kind, value):
    return bytes([255, kind]) + vlq(len(value)) + value


def build_demo(folder):
    folder.mkdir(parents=True, exist_ok=True)
    events = [(0, meta(3, "ทำนองทดสอบ newKaraoke".encode())),
              (0, meta(0x51, b"\x07\xa1\x20")), (0, bytes([0xC0, 0])),
              (0, bytes([0xC1, 48])), (0, bytes([0xB0, 7, 100]))]
    melody = [60, 64, 67, 72, 69, 67, 64, 62, 60, 62, 64, 67, 65, 64, 62, 60]
    lyrics = ["/สวัสดี ", "ยินดี", "ต้อนรับ ", "ทุกคน", "/ลองปรับ ", "คีย์เพลง ", "แล้วร้อง ", "ด้วยกัน",
              "/เพิ่มเพลง ", "เข้าคิว ", "กดเล่น ", "ต่อไป", "/ขอให้ ", "วันนี้ ", "มีเสียง ", "เพลง"]
    for index, (note, word) in enumerate(zip(melody, lyrics)):
        tick = index * 960
        events.extend([(tick, meta(5, word.encode("utf-8"))),
                       (tick, bytes([0x90, note, 76])), (tick + 820, bytes([0x80, note, 0]))])
        if index % 4 == 0:
            for chord in [48, 52, 55]:
                events.extend([(tick, bytes([0x91, chord, 44])), (tick + 3700, bytes([0x81, chord, 0]))])
        for sub in range(2):
            events.extend([(tick + sub * 480, bytes([0x99, 42, 40])),
                           (tick + sub * 480 + 80, bytes([0x89, 42, 0]))])
    events.append((16 * 960, meta(0x2F, b"")))
    events.sort(key=lambda event: event[0])
    body = bytearray()
    previous = 0
    for tick, event in events:
        body.extend(vlq(tick - previous) + event)
        previous = tick
    midi = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(body)) + body
    (folder / "DEMO01 - ทดสอบ MIDI - newKaraoke.mid").write_bytes(midi)
    wav_path = folder / "DEMO02 - ทดสอบเสียงและเนื้อร้อง - newKaraoke.wav"
    rate = 22050
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        for note in melody:
            frequency = 440 * 2 ** ((note - 69) / 12)
            block = bytearray()
            for frame in range(rate):
                t = frame / rate
                envelope = min(t * 30, 1) * max(0, 1 - t) ** 2
                sample = math.sin(2 * math.pi * frequency * t) * 0.16 * envelope
                block.extend(struct.pack("<h", int(sample * 32767)))
            output.writeframes(block)
    wav_path.with_suffix(".lrc").write_text(
        "[ti:ทดสอบเสียงและเนื้อร้อง]\n[ar:newKaraoke]\n"
        "[00:00.00]<00:00.00>สวัสดี <00:01.00>ยินดี <00:02.00>ต้อนรับ <00:03.00>ทุกคน\n"
        "[00:04.00]<00:04.00>เพลงทดสอบ <00:06.00>สำหรับลองระบบ\n"
        "[00:08.00]<00:08.00>เพิ่มเพลง <00:09.00>เข้าคิว <00:10.00>แล้วกด <00:11.00>เล่น\n"
        "[00:12.00]<00:12.00>ขอให้วันนี้ <00:14.00>มีเสียงเพลง\n", encoding="utf-8")
    return midi


if __name__ == "__main__":
    build_demo(Path(__file__).resolve().parents[1] / "samples")
