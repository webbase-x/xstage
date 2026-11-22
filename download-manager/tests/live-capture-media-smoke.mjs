// Windows CI: exercise bundled FFmpeg/FFprobe with synthetic video,
// real audio and a one-second pause. No live platform/network required.
import assert from 'node:assert/strict';
import { mkdtempSync, existsSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const tools = process.argv[2];
assert.ok(tools, 'Expected bundled media tools directory');
const ffmpeg = join(tools, 'ffmpeg.exe');
const ffprobe = join(tools, 'ffprobe.exe');
assert.ok(existsSync(ffmpeg) && existsSync(ffprobe), 'Bundled tools missing');
const scratch = mkdtempSync(join(tmpdir(), 'xstage-live-smoke-'));

function run(executable, args, limit = 60_000) {
  const result = spawnSync(executable, args, {
    encoding: 'utf8', timeout: limit, maxBuffer: 4 * 1024 * 1024,
    windowsHide: true
  });
  if (result.error || result.status !== 0)
    throw new Error('Synthetic media command failed: ' + executable + '\n' +
      (result.stderr || result.error?.message || '').slice(-2000));
  return result;
}

try {
  const master = join(scratch, 'synthetic-master.mkv');
  const clip = join(scratch, 'synthetic-clip.partial.mp4');
  // Original audio: 4s tone + 1s silence + 4s tone, alongside synthetic video.
  run(ffmpeg, [
    '-hide_banner', '-loglevel', 'error', '-y',
    '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=9',
    '-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=44100:duration=4',
    '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=1',
    '-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=44100:duration=4',
    '-filter_complex', '[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]',
    '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', master
  ]);
  assert.ok(existsSync(master));

  const detected = run(ffmpeg, [
    '-hide_banner', '-nostdin', '-i', master, '-map', '0:a:0', '-vn',
    '-af', 'silencedetect=noise=-35dB:d=0.6', '-f', 'null', '-'
  ]);
  const start = /silence_start:\s*([0-9.]+)/.exec(detected.stderr || '');
  const end = /silence_end:\s*([0-9.]+)/.exec(detected.stderr || '');
  assert.ok(start && end, 'Real FFmpeg must report the audio pause');
  assert.ok(Number(start[1]) >= 3.8 && Number(start[1]) <= 4.2);
  assert.ok(Number(end[1]) >= 4.8 && Number(end[1]) <= 5.2);

  // Accurate audio/video re-encode near detected pause, instead of
  // unsafe GOP-boundary stream-copy cuts in the middle of speech.
  run(ffmpeg, [
    '-hide_banner', '-nostdin', '-loglevel', 'error',
    '-ss', '0', '-i', master, '-t', String((Number(start[1]) + Number(end[1])) / 2),
    '-map', '0:v:0?', '-map', '0:a:0?',
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
    '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-y', clip
  ]);
  const probe = run(ffprobe, [
    '-v', 'error', '-show_entries', 'stream=codec_type',
    '-of', 'csv=p=0', clip
  ]);
  assert.match(probe.stdout, /video/);
  assert.match(probe.stdout, /audio/);
  const mp4 = readFileSync(clip);
  assert.ok(mp4.includes(Buffer.from('ftyp')) && mp4.includes(Buffer.from('moov')),
    'Synthetic clip must have playable MP4 metadata');
  console.log('PASS: real bundled FFmpeg detects silence and produces a playable speech-pause-aligned MP4');
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
