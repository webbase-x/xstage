// X-Stage native PCM FIFO for BASSASIO output callbacks.
// Build as a Windows DLL; no Python invocation or allocation on audio callback.
// Stereo interleaved float32; the ASIO host still needs channel wiring.
#include <atomic>
#include <cstdint>
#include <cstring>
#include <memory>
#include <new>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define XSTAGE_API extern "C" __declspec(dllexport)
#else
#define XSTAGE_API extern "C"
#endif

struct XStagePcmBridge {
    explicit XStagePcmBridge(uint32_t frames)
        : capacity(frames), data(new (std::nothrow) float[static_cast<size_t>(frames) * 2]()) {}
    uint32_t capacity;
    std::unique_ptr<float[]> data;
    std::atomic<uint64_t> read{0}, write{0}, underruns{0}, overruns{0};
    // One producer, one consumer; keep callback lock-free.
};

XSTAGE_API XStagePcmBridge* xstage_pcm_create(uint32_t frames) noexcept {
    if (frames == 0 || frames > 480000) return nullptr;
    auto* q = new (std::nothrow) XStagePcmBridge(frames);
    if (!q) return nullptr;
    if (!q->data) { delete q; return nullptr; }
    return q;
}

// Caller must stop producer and callback before destroy.
XSTAGE_API void xstage_pcm_destroy(XStagePcmBridge* q) noexcept { delete q; }

XSTAGE_API uint32_t xstage_pcm_push(XStagePcmBridge* q, const float* stereo,
                                   uint32_t frames) noexcept {
    if (!q || !stereo) return 0;
    const uint64_t read = q->read.load(std::memory_order_acquire);
    const uint64_t write = q->write.load(std::memory_order_relaxed);
    const uint64_t free_frames = q->capacity - (write - read);
    const uint32_t accepted = static_cast<uint32_t>(
        frames < free_frames ? frames : free_frames);
    for (uint32_t i = 0; i < accepted; ++i) {
        const size_t at = static_cast<size_t>((write + i) % q->capacity) * 2;
        q->data[at] = stereo[static_cast<size_t>(i) * 2];
        q->data[at + 1] = stereo[static_cast<size_t>(i) * 2 + 1];
    }
    q->write.store(write + accepted, std::memory_order_release);
    q->overruns.fetch_add(frames - accepted, std::memory_order_relaxed);
    return accepted;
}

XSTAGE_API uint32_t xstage_pcm_pop(XStagePcmBridge* q, float* stereo,
                                  uint32_t frames) noexcept {
    if (!q || !stereo) return 0;
    const uint64_t read = q->read.load(std::memory_order_relaxed);
    const uint64_t write = q->write.load(std::memory_order_acquire);
    const uint64_t available = write - read;
    const uint32_t copied = static_cast<uint32_t>(
        frames < available ? frames : available);
    for (uint32_t i = 0; i < copied; ++i) {
        const size_t at = static_cast<size_t>((read + i) % q->capacity) * 2;
        stereo[static_cast<size_t>(i) * 2] = q->data[at];
        stereo[static_cast<size_t>(i) * 2 + 1] = q->data[at + 1];
    }
    if (frames > copied)
        std::memset(stereo + static_cast<size_t>(copied) * 2, 0,
                    static_cast<size_t>(frames - copied) * 2 * sizeof(float));
    q->read.store(read + copied, std::memory_order_release);
    q->underruns.fetch_add(frames - copied, std::memory_order_relaxed);
    return copied;
}

XSTAGE_API uint64_t xstage_pcm_underruns(const XStagePcmBridge* q) noexcept {
    return q ? q->underruns.load(std::memory_order_relaxed) : 0;
}
XSTAGE_API uint64_t xstage_pcm_overruns(const XStagePcmBridge* q) noexcept {
    return q ? q->overruns.load(std::memory_order_relaxed) : 0;
}

// BASSASIO ASIOPROC: length is bytes. This callback does not touch Python,
// allocate, acquire a lock or call BASSMIDI. Requires float32 stereo output
// (8 bytes/frame) and a host-managed lifecycle: stop ASIO before destroy.
#ifdef _WIN32
XSTAGE_API DWORD CALLBACK xstage_asio_callback(BOOL input, DWORD channel,
                                               void* buffer, DWORD length,
                                               void* user) noexcept {
    (void)channel;
    if (!buffer || input || (length % 8) != 0 || !user) {
        if (buffer && length) std::memset(buffer, 0, length);
        return 0;
    }
    auto* queue = static_cast<XStagePcmBridge*>(user);
    xstage_pcm_pop(queue, static_cast<float*>(buffer), length / 8);
    return length;
}
#endif
