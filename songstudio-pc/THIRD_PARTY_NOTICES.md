# Third-party components bundled with X-Stage Song Studio PC Ready

The portable Windows ZIP is assembled on GitHub Actions from the following upstream projects. It includes runtimes; it is **not** an independent claim that the Song Studio engine itself provides additional missing features.

| Component | Source | License / Notes |
|---|---|---|
| Python 3.13.10 embeddable (Windows x64) | https://www.python.org/ftp/python/3.13.10/python-3.13.10-embeddable-amd64.zip | PSF License; original LICENSE.txt copied when available |
| FFmpeg Windows release essentials | https://www.gyan.dev/ffmpeg/builds/ | FFmpeg LGPL/GPL, depending on build configuration; Gyan binary archives and vendor SHA-256 checks; corresponding FFmpeg source: https://ffmpeg.org/download.html, build documentation at https://www.gyan.dev/ffmpeg/builds/ |
| FluidSynth 2.6.2 x64 cpp11 | https://github.com/FluidSynth/fluidsynth/releases/tag/v2.6.2 | LGPL 2.1+ (see upstream repo and distributed DLLs). Official release asset checksum pinned in build script |
| HTDemucs fp16 ONNX AI model (166 MB) | https://huggingface.co/StemSplitio/htdemucs-onnx | MIT; original Meta Demucs / ONNX export by StemSplit; model SHA256 d05c269d0178d2a72ad484b10b11dd370193fc923201c3b27a99f848745db70a |\n| NumPy 2.2.6 | https://pypi.org/project/numpy/2.2.6/ | BSD-3-Clause; Windows x64 wheel bundled |\n| ONNX Runtime 1.23.2 CPU and transitive dependencies | https://pypi.org/project/onnxruntime/1.23.2/ | MIT and licenses of transitive wheels; Python 3.13 Windows x64 wheels bundled |\n| GeneralUser GS 2.0.3 | https://github.com/mrbumpy409/GeneralUser-GS/tree/684543d5e5efaef08d02be50dcda8d552478fa60 | Attribution: S. Christian Collins. See bundled `GeneralUser-GS-LICENSE.txt`. Redistribution is permitted under its stated terms, with notice. Samples have historical provenance caveats described by author. |

The GeneralUser GS bank is not sold separately. Any distribution must respect the author's license and include the license text. Its use does not imply endorsement by the author.

FFmpeg's executable and FluidSynth libraries are separate third-party programs dynamically invoked by this application. All existing copyright, license and source availability obligations remain applicable. The build process uses exact upstream download URLs and verifies the FFmpeg vendor SHA256 plus the pinned FluidSynth release SHA256, then writes SHA256 checksums for shipped runtime files and the ZIP archive.

**No Google OAuth secrets, user songs or credentials are bundled.** Songs are processed locally in the user's machine after extracting the archive.

**The AI vocal-separation model is included in Ready Build 303.** It runs on the CPU offline and may need substantial RAM. Google Drive sync remains outside this source preview. The light Source ZIP contains source and an integrity-locked model reference, not the 166 MB binary; the Ready ZIP contains the binary and all Python dependencies. Adding a model would require choosing a licensed model, validating hardware requirements and measuring its size/quality. It must not be misrepresented as included.

| Whisper.cpp native Windows CPU binary b5454 | https://github.com/ggml-org/whisper.cpp/releases/tag/b5454 | MIT, upstream ggml-org/whisper.cpp · Windows x64 ZIP SHA256 6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb |
| Whisper multilingual base GGML model | https://huggingface.co/ggerganov/whisper.cpp/blob/main/ggml-base.bin | MIT OpenAI Whisper / GGML model conversion. 147,951,465 bytes; SHA256 60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe. For voice-to-text drafts only. |
