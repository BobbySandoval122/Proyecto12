package mx.orvia.campo.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Sesion y cola cifradas con una clave AES-GCM creada en Android Keystore. */
class SecureStore(context: Context) {
    private val prefs = context.getSharedPreferences("orvia_private", Context.MODE_PRIVATE)
    private val alias = "mx.orvia.campo.storage.v1"
    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).build())
        return generator.generateKey()
    }
    @Synchronized fun save(name: String, value: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val payload = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString(name, Base64.encodeToString(payload, Base64.NO_WRAP)).commit())
    }
    @Synchronized fun load(name: String): String? {
        val raw = prefs.getString(name, null) ?: return null
        return try {
            val payload = Base64.decode(raw, Base64.NO_WRAP)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, payload.copyOfRange(0, 12)))
            String(cipher.doFinal(payload.copyOfRange(12, payload.size)), Charsets.UTF_8)
        } catch (_: Exception) { null }
    }
    @Synchronized fun remove(name: String) { prefs.edit().remove(name).commit() }
    fun loadQueueFor(userId: Int): List<PendingOperation> = try {
        val array = JSONArray(load("queue_$userId") ?: "[]")
        array.items().map { PendingOperation.fromJson(it) }
    } catch (_: Exception) { emptyList() }
    fun saveQueueFor(userId: Int, items: List<PendingOperation>) {
        val array = JSONArray()
        items.forEach { array.put(it.toJson()) }
        save("queue_$userId", array.toString())
    }
    fun saveSession(session: Session) = save("session", session.toJson().toString())
    fun loadSession(): Session? = try { load("session")?.let { Session.fromJson(JSONObject(it)) } }
        catch (_: Exception) { null }
    fun getHost(): String = prefs.getString("host", "http://10.0.2.2") ?: "http://10.0.2.2"
    fun setHost(host: String) { check(prefs.edit().putString("host", host).commit()) }
}
