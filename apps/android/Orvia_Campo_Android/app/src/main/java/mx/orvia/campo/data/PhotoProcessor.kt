package mx.orvia.campo.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.security.MessageDigest

/** Convierte fotos reales a JPEG de campo (<5MB), sin confiar en su extension. */
object PhotoProcessor {
    fun prepare(context: Context, uri: Uri): PhotoData {
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
        require(opts.outWidth > 0 && opts.outHeight > 0) { "La imagen seleccionada no es valida" }
        var sample = 1
        while (opts.outWidth / sample > 1800 || opts.outHeight / sample > 1800) sample *= 2
        val decode = BitmapFactory.Options().apply { inSampleSize = sample }
        val bitmap = context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, decode) }
            ?: error("No se pudo leer la fotografia")
        val rotated = bitmap // La orientacion EXIF debera probarse en dispositivos reales.
        val buffer = ByteArrayOutputStream()
        var quality = 86
        var bytes: ByteArray
        do {
            buffer.reset()
            check(rotated.compress(Bitmap.CompressFormat.JPEG, quality, buffer)) { "No se pudo comprimir la imagen" }
            bytes = buffer.toByteArray()
            quality -= 12
        } while (bytes.size > 4_800_000 && quality >= 38)
        if (rotated !== bitmap) rotated.recycle()
        bitmap.recycle()
        require(bytes.size <= 5 * 1024 * 1024) { "La foto es demasiado grande: elige otra." }
        val sha = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        return PhotoData("orvia_${System.currentTimeMillis()}.jpg", bytes, sha)
    }
}
