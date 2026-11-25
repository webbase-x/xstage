package app.airshow.tv.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.Handler
import android.os.Looper
import android.util.Log

data class MdnsService(val name: String, val type: String, val port: Int, val txt: Map<String, String>)

/**
 * NsdManager registration is asynchronous. A transient failure previously only
 * logged a warning and left iPhones unable to discover this device until restart.
 * Retry failed registrations on a capped backoff until teardown; never retry a live service.
 * release() cancels pending retries and unregisters all active listeners.
 */
class NsdServiceManager(private val ctx: Context) {
    private val manager = ctx.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val handler = Handler(Looper.getMainLooper())
    private val stateLock = Any()
    private var multicastLock: WifiManager.MulticastLock? = null
    private val listeners = mutableSetOf<NsdManager.RegistrationListener>()
    @Volatile private var released = false

    fun acquireMulticastLock() {
        val wifi = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        synchronized(stateLock) {
            if (released || multicastLock != null) return
            multicastLock = wifi.createMulticastLock("xstage_mirror_mdns").apply {
                setReferenceCounted(false)
                acquire()
            }
        }
    }

    fun register(services: List<MdnsService>) {
        services.forEach { service -> registerAttempt(service, 0) }
    }

    private fun registerAttempt(service: MdnsService, attempt: Int) {
        if (released) return
        val info = NsdServiceInfo().apply {
            serviceName = service.name
            serviceType = service.type
            port = service.port
            service.txt.forEach { (k, v) -> setAttribute(k, v) }
        }
        val listener = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(actual: NsdServiceInfo) {
                if (released) {
                    try { manager.unregisterService(this) } catch (_: RuntimeException) { }
                    return
                }
                Log.i(TAG, "${service.type} ready as '${actual.serviceName}' (attempt ${attempt + 1})")
                if (actual.serviceName != service.name) {
                    Log.w(TAG, "Android renamed colliding service '${service.name}' -> '${actual.serviceName}'")
                }
            }
            override fun onRegistrationFailed(info: NsdServiceInfo, code: Int) {
                val wasPending = synchronized(stateLock) { listeners.remove(this) }
                if (!wasPending || released) return
                Log.w(TAG, "${service.type} registration failed: $code")
                scheduleRetry(service, attempt)
            }
            override fun onServiceUnregistered(info: NsdServiceInfo) {
                synchronized(stateLock) { listeners.remove(this) }
                Log.i(TAG, "${service.type} unregistered")
            }
            override fun onUnregistrationFailed(info: NsdServiceInfo, code: Int) {
                synchronized(stateLock) { listeners.remove(this) }
                Log.w(TAG, "${service.type} unregister failed: $code")
            }
        }
        synchronized(stateLock) {
            if (released) return
            listeners.add(listener)
            try {
                manager.registerService(info, NsdManager.PROTOCOL_DNS_SD, listener)
            } catch (e: RuntimeException) {
                listeners.remove(listener)
                Log.w(TAG, "${service.type} registerService threw", e)
                scheduleRetry(service, attempt)
            }
        }
    }

    private fun scheduleRetry(service: MdnsService, attempt: Int) {
        if (released) return
        val next = (attempt + 1).coerceAtMost(RETRY_DELAYS_MS.lastIndex)
        handler.postDelayed({
            if (!released) registerAttempt(service, next)
        }, RETRY_DELAYS_MS[attempt.coerceAtMost(RETRY_DELAYS_MS.lastIndex)])
    }

    fun release() {
        val existing: List<NsdManager.RegistrationListener>
        val lock: WifiManager.MulticastLock?
        synchronized(stateLock) {
            if (released) return
            released = true
            existing = listeners.toList()
            listeners.clear()
            lock = multicastLock
            multicastLock = null
        }
        handler.removeCallbacksAndMessages(null)
        existing.forEach { listener ->
            try { manager.unregisterService(listener) } catch (_: Exception) { }
        }
        if (lock?.isHeld == true) lock.release()
    }

    private companion object {
        const val TAG = "XStageMirrorDiscovery"
        val RETRY_DELAYS_MS = longArrayOf(700L, 1_800L, 4_000L, 8_000L, 30_000L)
    }
}
