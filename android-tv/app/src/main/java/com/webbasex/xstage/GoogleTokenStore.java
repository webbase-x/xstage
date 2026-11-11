package com.webbasex.xstage;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Encrypted storage for the Google refresh token; never store a new token in plaintext.
 * Supports one-time migration from legacy SharedPreferences after an APK update.
 * Android 6+ (minSdk 23) provides AndroidKeyStore AES/GCM.
 */
final class GoogleTokenStore {
    private static final String PREFS = "xstage_tv_google_auth";
    private static final String LEGACY_KEY = "refresh_token";
    private static final String ENCRYPTED_KEY = "refresh_token_encrypted_v1";
    private static final String ALIAS = "xstage_google_refresh_aes_v1";

    private final SharedPreferences prefs;

    GoogleTokenStore(Context context) {
        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    synchronized String read() {
        String encrypted = prefs.getString(ENCRYPTED_KEY, "");
        if (encrypted != null && !encrypted.isEmpty()) {
            try {
                byte[] all = Base64.decode(encrypted, Base64.NO_WRAP);
                if (all.length < 14) throw new IllegalStateException("Encrypted token too short");
                ByteBuffer payload = ByteBuffer.wrap(all);
                int ivLength = payload.get() & 0xff;
                if (ivLength != 12 || payload.remaining() < 16) {
                    throw new IllegalStateException("Invalid refresh token IV");
                }
                byte[] iv = new byte[ivLength];
                payload.get(iv);
                byte[] ciphertext = new byte[payload.remaining()];
                payload.get(ciphertext);
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
                return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
            } catch (Exception e) {
                // Keystore can be invalidated by device resets. Never use corrupted tokens.
                clear();
                return "";
            }
        }
        String legacy = prefs.getString(LEGACY_KEY, "");
        if (legacy == null || legacy.isEmpty()) return "";
        try {
            write(legacy);
            return legacy;
        } catch (Exception e) {
            // Do not retain an old plaintext token after a failed migration.
            clear();
            return "";
        }
    }

    synchronized void write(String token) throws Exception {
        if (token == null || token.isEmpty()) {
            clear();
            return;
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] iv = cipher.getIV();
        byte[] ciphertext = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        ByteBuffer output = ByteBuffer.allocate(1 + iv.length + ciphertext.length);
        output.put((byte) iv.length);
        output.put(iv);
        output.put(ciphertext);
        prefs.edit().putString(ENCRYPTED_KEY,
                Base64.encodeToString(output.array(), Base64.NO_WRAP))
                .remove(LEGACY_KEY).apply();
    }

    synchronized void clear() {
        prefs.edit().remove(ENCRYPTED_KEY).remove(LEGACY_KEY).apply();
    }

    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        SecretKey existing = (SecretKey) store.getKey(ALIAS, null);
        if (existing != null) return existing;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build());
        return generator.generateKey();
    }
}
