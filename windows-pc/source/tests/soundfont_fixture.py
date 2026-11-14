"""Original tiny sine-wave SF2, for automated tests only (not a musical library)."""
import math
import struct
from pathlib import Path


def chunk(tag, data):
    return tag + struct.pack('<I', len(data)) + data + (b'\0' if len(data) % 2 else b'')


def make_font(path, amplitude=16000):
    # One second, exact 440 cycles, plus the SoundFont 46-point guard region.
    samples = b''.join(struct.pack('<h', int(amplitude * math.sin(2*math.pi*440*i/48000))) for i in range(48000)) + b'\0'*92
    info = chunk(b'LIST', b'INFO' + chunk(b'ifil', struct.pack('<HH', 2, 1)) + chunk(b'INAM', b'X-Stage test sine\0'))
    sdta = chunk(b'LIST', b'sdta' + chunk(b'smpl', samples))
    phdr = struct.pack('<20sHHHIII', b'Sine test', 0, 0, 0, 0, 0, 0) + struct.pack('<20sHHHIII', b'EOP', 0, 0, 1, 0, 0, 0)
    pbag = struct.pack('<HHHH', 0, 0, 1, 0)
    pgen = struct.pack('<HHHH', 41, 0, 0, 0)
    inst = struct.pack('<20sH20sH', b'Sine', 0, b'EOI', 1)
    ibag = struct.pack('<HHHH', 0, 0, 3, 0)
    igen = struct.pack('<HHHHHHHH', 54, 1, 58, 69, 53, 0, 0, 0)
    shdr = struct.pack('<20sIIIIIBbHH', b'Sine', 0, 48000, 0, 48000, 48000, 69, 0, 0, 1)
    shdr += struct.pack('<20sIIIIIBbHH', b'EOS', 48046, 48046, 48046, 48046, 48000, 0, 0, 0, 1)
    pdta = chunk(b'LIST', b'pdta' + b''.join(chunk(tag, data) for tag, data in [
        (b'phdr', phdr), (b'pbag', pbag), (b'pmod', b'\0'*10), (b'pgen', pgen), (b'inst', inst),
        (b'ibag', ibag), (b'imod', b'\0'*10), (b'igen', igen), (b'shdr', shdr)]))
    Path(path).write_bytes(chunk(b'RIFF', b'sfbk' + info + sdta + pdta))
    return Path(path)
