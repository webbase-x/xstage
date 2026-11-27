package com.webbasex.xstage;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.system.Os;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Locale;

/**
 * Disk-backed read-only shared catalog. No JS array or sql.js heap is required.
 * Network and SQL operations must run off the Activity UI thread.
 * A verified previous revision remains readable until its replacement is complete.
 */
final class NativeCatalogStore implements AutoCloseable {
    private static final int PAGE_SIZE = 5;
    private static final int BUFFER_SIZE = 128 * 1024;
    private static final long DISK_RESERVE = 32L * 1024 * 1024;
    private static final String RETIRED_ROOT = "1RYekUHCC3qs661cUrbxkNauUz_SuqZvy";
    private final File directory;
    private SQLiteDatabase database;
    private String activeScope = "";
    private String activeRevision = "";
    private long activeCount;
    private File activeFile;
    interface Progress {
        void update(long received, long total);
    }

    NativeCatalogStore(Context context) {
        directory = new File(context.getFilesDir(), "catalog-v1");
    }

    private static void require(boolean condition, String message) throws IOException {
        if (!condition) throw new IOException(message);
    }

    private static String hex(byte[] digest) {
        StringBuilder result = new StringBuilder(digest.length * 2);
        for (byte value : digest) result.append(String.format(Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }

    private static String scope(String sub, String root) throws Exception {
        require(sub != null && sub.length() > 0 && sub.length() <= 256, "Invalid account");
        require(root != null && root.matches("[A-Za-z0-9_-]{5,256}") && !RETIRED_ROOT.equals(root), "Invalid library");
        return hex(MessageDigest.getInstance("SHA-256").digest((sub + "\u0000" + root).getBytes(StandardCharsets.UTF_8)));
    }

    private static String validId(String id) throws IOException {
        require(id != null && id.matches("[A-Za-z0-9_-]{5,256}"), "Invalid Drive file ID");
        return id;
    }

    private static HttpURLConnection connect(String url, String token) throws Exception {
        require(token != null && !token.isEmpty() && token.length() <= 8192 &&
                !token.contains("\n") && !token.contains("\r"), "Invalid access token");
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(20000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("Accept-Encoding", "identity");
        return connection;
    }

    private static JSONObject json(String url, String token) throws Exception {
        HttpURLConnection c = connect(url, token);
        try {
            require(c.getResponseCode() == 200, "Google metadata request failed (HTTP " + c.getResponseCode() + ")");
            try (InputStream in = c.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] b = new byte[8192];
                int n;
                while ((n = in.read(b)) != -1) {
                    require(out.size() + n <= 1024 * 1024, "Google metadata too large");
                    out.write(b, 0, n);
                }
                return new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
            }
        } finally { c.disconnect(); }
    }

    private static JSONObject metadata(String id, String token) throws Exception {
        return json("https://www.googleapis.com/drive/v3/files/" + validId(id) +
                "?fields=id,name,parents,size,md5Checksum,trashed,mimeType&supportsAllDrives=true", token);
    }

    private static void verifyParent(JSONObject file, String parent) throws Exception {
        JSONArray parents = file.optJSONArray("parents");
        require(!file.optBoolean("trashed") && parents != null && parents.length() == 1 &&
                parent.equals(parents.optString(0)), "Drive file is outside the selected library");
    }

    // Strict root -> DB -> songs.sqlite3 verification, including account identity.
    private static JSONObject verifySource(String token, String sub, String root,
                                           String dbId, String fileId) throws Exception {
        return verifySource(token, sub, root, dbId, fileId, "songs.sqlite3");
    }
    private static JSONObject verifySource(String token, String sub, String root,
                                           String dbId, String fileId, String name) throws Exception {
        JSONObject account = json("https://openidconnect.googleapis.com/v1/userinfo", token);
        require(account.optBoolean("email_verified") && sub.equals(account.optString("sub")), "Google account changed");
        JSONObject rootMeta = metadata(root, token);
        require(!rootMeta.optBoolean("trashed") && root.equals(rootMeta.optString("id")) &&
                "application/vnd.google-apps.folder".equals(rootMeta.optString("mimeType")), "Invalid Drive library");
        JSONObject folder = metadata(dbId, token);
        verifyParent(folder, root);
        require(dbId.equals(folder.optString("id")) && "DB".equals(folder.optString("name")) &&
                "application/vnd.google-apps.folder".equals(folder.optString("mimeType")), "Invalid DB folder");
        JSONObject file = metadata(fileId, token);
        verifyParent(file, dbId);
        require(fileId.equals(file.optString("id")) && name.equals(file.optString("name")) &&
                !"application/vnd.google-apps.shortcut".equals(file.optString("mimeType")), "Invalid catalog file");
        return file;
    }

    private static long longHeader(HttpURLConnection c, String name) {
        try { return Long.parseLong(c.getHeaderField(name)); }
        catch (Exception ignored) { return -1; }
    }

    private static void stream(String id, String token, File target, long size,
                               String md5, Progress progress) throws Exception {
        long existing = target.isFile() ? target.length() : 0;
        if (existing > size) {
            require(target.delete(), "Cannot reset invalid partial catalog");
            existing = 0;
        }
        MessageDigest digest = MessageDigest.getInstance("MD5");
        byte[] buffer = new byte[BUFFER_SIZE];
        if (existing > 0) {
            try (InputStream in = new java.io.FileInputStream(target)) {
                int n;
                while ((n = in.read(buffer)) != -1) {
                    if (Thread.currentThread().isInterrupted()) throw new IOException("Catalog download cancelled");
                    digest.update(buffer, 0, n);
                }
            }
        }
        if (existing < size) {
            HttpURLConnection c = connect("https://www.googleapis.com/drive/v3/files/" +
                    validId(id) + "?alt=media&supportsAllDrives=true", token);
            try {
                if (existing > 0) c.setRequestProperty("Range", "bytes=" + existing + "-");
                int status = c.getResponseCode();
                if (existing > 0 && status == 200) {
                    // A server that ignores Range requires a clean restart.
                    existing = 0;
                    digest.reset();
                } else if (existing > 0) {
                    require(status == 206 && ("bytes " + existing + "-" + (size - 1) + "/" + size)
                            .equals(c.getHeaderField("Content-Range")), "Invalid catalog resume range");
                } else {
                    require(status == 200, "Catalog download failed (HTTP " + status + ")");
                }
                long advertised = longHeader(c, "Content-Length");
                require(advertised < 0 || advertised == size - existing, "Catalog size changed");
                long received = existing;
                long reported = existing - BUFFER_SIZE * 8L;
                try (InputStream in = c.getInputStream(); FileOutputStream out = new FileOutputStream(target, existing > 0)) {
                    int n;
                    while ((n = in.read(buffer)) != -1) {
                        if (Thread.currentThread().isInterrupted()) throw new IOException("Catalog download cancelled");
                        require(n <= size - received, "Catalog exceeded its verified size");
                        out.write(buffer, 0, n);
                        digest.update(buffer, 0, n);
                        received += n;
                        if (progress != null && (received - reported >= BUFFER_SIZE * 8L || received == size)) {
                            progress.update(received, size);
                            reported = received;
                        }
                    }
                    out.getFD().sync();
                    require(received == size, "Catalog download interrupted");
                }
            } finally { c.disconnect(); }
        }
        if (target.length() != size || !md5.equals(hex(digest.digest()))) {
            // An invalid complete transfer cannot be resumed forever.
            if (target.length() >= size) target.delete();
            throw new IOException("Catalog checksum or length mismatch");
        }
    }

    private static String scalar(SQLiteDatabase db, String sql, String[] args) throws Exception {
        try (Cursor cursor = db.rawQuery(sql, args)) {
            require(cursor.moveToFirst(), "SQLite result missing");
            return cursor.getString(0);
        }
    }

    private static SQLiteDatabase openVerified(File file, boolean fullCheck) throws Exception {
        SQLiteDatabase db = SQLiteDatabase.openDatabase(file.getAbsolutePath(), null,
                SQLiteDatabase.OPEN_READONLY | SQLiteDatabase.NO_LOCALIZED_COLLATORS);
        boolean valid = false;
        try {
            if (fullCheck) require("ok".equals(scalar(db, "PRAGMA quick_check(1)", null)), "SQLite integrity check failed");
            require("xstage-sqlite3-v1".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='format'", null)) &&
                    "1".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='schemaVersion'", null)) &&
                    "snapshot".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='kind'", null)) &&
                    ("shared-v1".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='pcSchema'", null)) ||
                    "verified-compact-v1".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='pcSchema'", null))), "Unsupported SQLite catalog schema");
            // Verify required tables/columns without materializing all rows.
            try (Cursor ignored = db.rawQuery("SELECT ordinal,id,web_song_id,payload,code,title,artist,playable FROM songs LIMIT 0", null)) {
                ignored.getColumnCount();
            }
            valid = true;
            return db;
        } finally { if (!valid) db.close(); }
    }

    private static void validateBinding(SQLiteDatabase db, String sourceMD5, long sourceBytes) throws Exception {
        boolean sidecar = "verified-compact-v1".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='pcSchema'", null));
        if (!sidecar && sourceMD5.isEmpty()) return;
        require(sidecar && sourceMD5.matches("[a-f0-9]{32}") &&
                "xstage-verified-compact-v1".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='mediaIdentity'", null)) &&
                sourceMD5.equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='sourceMD5'", null)) &&
                Long.toString(sourceBytes).equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='sourceBytes'", null)) &&
                "0".equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='rejectedCount'", null)), "Verified catalog stale or incomplete");
        String count = scalar(db, "SELECT COUNT(*) FROM songs WHERE playable=1", null);
        require(!"0".equals(count) && count.equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='verifiedCount'", null)) &&
                count.equals(scalar(db, "SELECT value FROM catalog_meta WHERE key='expectedCount'", null)), "Verified count mismatch");
        // Stream rows through Cursor rather than requiring JSON1 on older Android SQLite builds.
        try (Cursor rows = db.rawQuery("SELECT web_song_id,payload FROM songs WHERE playable=1", null)) {
            while (rows.moveToNext()) {
                if (Thread.currentThread().isInterrupted()) throw new IOException("Catalog validation cancelled");
                JSONObject song = new JSONObject(rows.getString(1));
                JSONObject media = song.optJSONObject("xmid");
                require(rows.getString(0).equals(song.optString("webSongId")) &&
                        song.optBoolean("verifiedOriginal") && media != null &&
                        media.optString("sha256").matches("[a-f0-9]{64}") &&
                        media.optString("md5Checksum").matches("[a-f0-9]{32}") &&
                        media.optLong("size", 0) > 0, "Unverified media in playable catalog");
            }
        }
    }
    private static String contentRevision(String md5, long size) {
        return md5 + "-" + size;
    }

    /**
     * Reuse unchanged revision on disk; never replace an active DB before a complete
     * download, digest check and SQLite validation. One canonical DB per account/root.
     * A content-keyed temporary file survives an interrupted transfer for Range resume.
     */
    synchronized JSONObject open(String token, String sub, String root, String dbId,
                                 String fileId, Progress progress) throws Exception {
        return open(token, sub, root, dbId, fileId, "", "", 0, progress);
    }
    synchronized JSONObject open(String token, String sub, String root, String dbId,
                                 String fileId, String sourceId, String sourceMD5, long sourceBytes, Progress progress) throws Exception {
        String owner = scope(sub, root);
        String name = sourceId.isEmpty() ? "songs.sqlite3" : "songs.verified.sqlite3";
        if (!sourceId.isEmpty()) {
            JSONObject original = verifySource(token, sub, root, dbId, sourceId);
            require(sourceMD5.matches("[a-f0-9]{32}") && sourceBytes >= 100 &&
                sourceMD5.equalsIgnoreCase(original.optString("md5Checksum")) &&
                Long.toString(sourceBytes).equals(original.optString("size")), "Original catalog revision changed");
        }
        JSONObject info = verifySource(token, sub, root, dbId, fileId, name);
        long size = Long.parseLong(info.optString("size", "0"));
        String md5 = info.optString("md5Checksum", "").toLowerCase(Locale.ROOT);
        require(size >= 100 && md5.matches("[a-f0-9]{32}"), "Missing catalog size/checksum");
        // File ID authorizes the source; bytes, not file ID or modifiedTime, identify
        // the local revision. Re-uploading identical bytes must not cause a download.
        String revision = contentRevision(md5, size);
        if (database != null && database.isOpen() && owner.equals(activeScope) &&
                revision.equals(activeRevision) && activeFile != null &&
                activeFile.isFile() && activeFile.length() == size) {
            validateBinding(database, sourceMD5, sourceBytes);
            return summary(true);
        }
        File folder = new File(directory, owner);
        require(folder.isDirectory() || folder.mkdirs(), "Cannot create catalog directory");
        File target = new File(folder, revision + ".sqlite3");
        File temp = new File(folder, revision + ".part");
        SQLiteDatabase candidate = null;
        boolean cached = false;
        try {
            if (target.isFile() && target.length() == size) {
                try {
                    MessageDigest digest = MessageDigest.getInstance("MD5");
                    try (InputStream in = new java.io.FileInputStream(target)) {
                        byte[] b = new byte[BUFFER_SIZE]; int n;
                        while ((n = in.read(b)) != -1) digest.update(b, 0, n);
                    }
                    require(md5.equals(hex(digest.digest())), "Cached checksum mismatch");
                    candidate = openVerified(target, false);
                    validateBinding(candidate, sourceMD5, sourceBytes);
                    cached = true;
                } catch (Exception invalid) {
                    if (candidate != null) candidate.close();
                    candidate = null;
                }
            }
            if (!cached) {
                long partial = temp.isFile() && temp.length() <= size ? temp.length() : 0;
                require(folder.getUsableSpace() >= DISK_RESERVE &&
                        size - partial <= folder.getUsableSpace() - DISK_RESERVE, "Insufficient local storage for catalog");
                stream(fileId, token, temp, size, md5, progress);
                try (SQLiteDatabase checked = openVerified(temp, true)) {
                    validateBinding(checked, sourceMD5, sourceBytes);
                    scalar(checked, "SELECT COUNT(*) FROM songs WHERE playable=1", null);
                }
                // Metadata may have changed during download. Keep the previous local
                // catalog if Drive now reports a different revision or moved the file.
                JSONObject latest = verifySource(token, sub, root, dbId, fileId, name);
                require(size == Long.parseLong(latest.optString("size", "0")) &&
                        md5.equalsIgnoreCase(latest.optString("md5Checksum", "")),
                        "Cloud catalog changed during download; retry synchronization");
                // Atomic same-filesystem rename. Old revision is not removed here.
                Os.rename(temp.getAbsolutePath(), target.getAbsolutePath());
                candidate = openVerified(target, false);
            }
            validateBinding(candidate, sourceMD5, sourceBytes);
            if (!sourceId.isEmpty()) {
                JSONObject latestOriginal = verifySource(token, sub, root, dbId, sourceId);
                require(sourceMD5.equalsIgnoreCase(latestOriginal.optString("md5Checksum")) && Long.toString(sourceBytes).equals(latestOriginal.optString("size")), "Original catalog changed during download");
            }
            long count = Long.parseLong(scalar(candidate, "SELECT COUNT(*) FROM songs WHERE playable=1", null));
            SQLiteDatabase previous = database;
            database = candidate;
            candidate = null;
            activeScope = owner;
            activeRevision = revision;
            activeFile = target;
            activeCount = count;
            if (previous != null) previous.close();
            return summary(cached);
        } finally {
            if (candidate != null) candidate.close();
        }
    }

    private JSONObject summary(boolean cached) throws Exception {
        JSONObject result = new JSONObject();
        result.put("revision", activeRevision);
        result.put("count", activeCount);
        result.put("fromDisk", cached);
        return result;
    }

    private void requireScope(String sub, String root, String revision) throws Exception {
        require(database != null && database.isOpen() && scope(sub, root).equals(activeScope) &&
                activeRevision.equals(revision), "Catalog session changed");
    }

    private static String normalize(String value) {
        return Normalizer.normalize(value == null ? "" : value, Normalizer.Form.NFKC)
                .toLowerCase(Locale.ROOT).trim().replaceAll("\\s+", " ");
    }

    /** Bound query arguments, deterministic order, at most five payloads per request. */
    synchronized JSONObject search(String sub, String root, String revision, String raw, long offset) throws Exception {
        requireScope(sub, root, revision);
        require(raw != null && raw.length() <= 256 && offset >= 0, "Invalid catalog query");
        String term = normalize(raw);
        JSONObject result = new JSONObject();
        JSONArray songs = new JSONArray();
        if (term.isEmpty()) return result.put("total", 0).put("songs", songs);
        ArrayList<String> args = new ArrayList<>();
        StringBuilder where = new StringBuilder("playable=1");
        String combined = "(lower(code)||' '||lower(title)||' '||lower(artist))";
        for (String word : term.split(" ")) {
            where.append(" AND instr(").append(combined).append(",?)>0");
            args.add(word);
        }
        String[] countArgs = args.toArray(new String[0]);
        long total = Long.parseLong(scalar(database, "SELECT COUNT(*) FROM songs WHERE " + where, countArgs));
        String order = "CASE WHEN lower(code)=? THEN 0 WHEN lower(title)=? THEN 10 " +
                "WHEN instr(lower(title),?)=1 THEN 20 WHEN instr(lower(code),?)=1 THEN 30 " +
                "WHEN lower(artist)=? THEN 40 WHEN instr(lower(artist),?)=1 THEN 50 ELSE 60 END";
        for (int i = 0; i < 6; i++) args.add(term);
        args.add(Long.toString(offset));
        try (Cursor c = database.rawQuery("SELECT web_song_id,payload FROM songs WHERE " + where +
                " ORDER BY " + order + ",ordinal,id LIMIT " + PAGE_SIZE + " OFFSET ?", args.toArray(new String[0]))) {
            while (c.moveToNext()) {
                JSONObject song = new JSONObject(c.getString(1));
                require(c.getString(0).equals(song.optString("webSongId")), "Catalog song identity mismatch");
                songs.put(song);
            }
        }
        return result.put("total", total).put("songs", songs);
    }

    synchronized JSONObject lookup(String sub, String root, String revision, String id,
                                   String code, String title, String artist) throws Exception {
        requireScope(sub, root, revision);
        if (id != null && !id.isEmpty()) {
            JSONObject hit = firstSong("web_song_id=?", new String[]{id});
            if (hit != null) return hit;
        }
        if (code != null && !code.isEmpty()) {
            JSONObject hit = firstSong("code=? COLLATE NOCASE", new String[]{code});
            if (hit != null) return hit;
        }
        if (title != null && !title.isEmpty()) {
            if (artist != null && !artist.isEmpty())
                return firstSong("title=? COLLATE NOCASE AND artist=? COLLATE NOCASE", new String[]{title, artist});
            return firstSong("title=? COLLATE NOCASE", new String[]{title});
        }
        return null;
    }

    private JSONObject firstSong(String condition, String[] args) throws Exception {
        try (Cursor c = database.rawQuery("SELECT web_song_id,payload FROM songs WHERE playable=1 AND (" +
                condition + ") ORDER BY ordinal,id LIMIT 1", args)) {
            if (!c.moveToFirst()) return null;
            JSONObject song = new JSONObject(c.getString(1));
            require(c.getString(0).equals(song.optString("webSongId")), "Catalog song identity mismatch");
            return song;
        }
    }

    synchronized JSONObject randomSong(String sub, String root, String revision) throws Exception {
        requireScope(sub, root, revision);
        if (activeCount == 0) return null;
        long offset = (long) (Math.random() * activeCount);
        try (Cursor c = database.rawQuery("SELECT web_song_id,payload FROM songs WHERE playable=1 ORDER BY ordinal,id LIMIT 1 OFFSET ?",
                new String[]{Long.toString(offset)})) {
            if (!c.moveToFirst()) return null;
            JSONObject song = new JSONObject(c.getString(1));
            require(c.getString(0).equals(song.optString("webSongId")), "Catalog song identity mismatch");
            return song;
        }
    }

    synchronized void cleanupObsolete() {
        if (activeFile == null) return;
        File[] files = activeFile.getParentFile().listFiles();
        if (files != null) for (File item : files) {
            if (!item.equals(activeFile) && item.isFile() &&
                    (item.getName().endsWith(".sqlite3") || item.getName().endsWith(".part"))) item.delete();
        }
    }

    @Override public synchronized void close() {
        if (database != null) database.close();
        database = null;
        activeScope = "";
        activeRevision = "";
        activeCount = 0;
        activeFile = null;
    }
}
