package app.airshow.tv

import android.content.Context

/** Fixed AirPlay identity and optional user-defined location suffix. */
object ReceiverNamePolicy {
    const val PREFIX = "X-Stage Mirror TV"
    const val MAX_NAME_LENGTH = 64
    val MAX_SUFFIX_LENGTH: Int get() = MAX_NAME_LENGTH - PREFIX.length - 1

    fun suffixOf(fullName: String): String = when {
        fullName == PREFIX -> ""
        fullName.startsWith("$PREFIX ") -> fullName.removePrefix("$PREFIX ")
        else -> fullName.trim()
    }

    fun fromSuffix(rawSuffix: String): String {
        val cleaned = rawSuffix
            .filterNot { Character.isISOControl(it) }
            .trim()
            .replace(Regex("\\s+"), " ")
            .take(MAX_SUFFIX_LENGTH)
            .trim()
        return if (cleaned.isEmpty()) PREFIX else "$PREFIX $cleaned"
    }

    fun isValid(fullName: String): Boolean =
        fullName.length <= MAX_NAME_LENGTH &&
        fullName == fromSuffix(suffixOf(fullName))

    /** Preserve pre-existing custom names across migration to the fixed prefix. */
    fun migratePreviousName(context: Context) {
        val prefs = context.getSharedPreferences(Prefs.NAME, Context.MODE_PRIVATE)
        val old = prefs.getString(Prefs.SERVER_NAME.key, null) ?: return
        if (!isValid(old)) {
            val migrated = fromSuffix(suffixOf(old))
            prefs.edit().putString(Prefs.SERVER_NAME.key, migrated).apply()
        }
    }
}
