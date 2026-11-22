package mx.orvia.campo.data

import org.json.JSONArray
import org.json.JSONObject
import java.time.OffsetDateTime
import java.util.UUID

/** Roles EXACTOS de shared/seguridad.py en Orvia-Oficial, commit 5690365. */
object Roles {
    const val CLIENTE = "Cliente"
    const val RECOLECTOR = "Recolector"
    const val OPERADOR = "Operador de Almacen"
    const val SUPERVISOR = "Supervisor"
    const val COORDINADOR = "Coordinador de Logistica"
    const val CENTRO = "Encargado del Centro de Devoluciones"
    const val ADMIN = "Administrador"
}

data class Session(
    val id: Int,
    val name: String,
    val email: String,
    val role: String,
    val accessToken: String,
    val refreshToken: String
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id).put("name", name).put("email", email).put("role", role)
        .put("access", accessToken).put("refresh", refreshToken)
    companion object {
        fun fromJson(x: JSONObject) = Session(x.getInt("id"), x.getString("name"),
            x.optString("email"), x.getString("role"), x.getString("access"), x.getString("refresh"))
    }
}

data class Sale(val id: Int, val folio: String, val date: String, val total: String)
data class SaleLine(val id: Int, val product: String, val lot: String, val available: Int, val quantity: Int)
data class Reason(val id: Int, val name: String)
data class ReturnItem(val id: Int, val folio: String, val product: String, val status: String,
                      val date: String, val lot: String)
data class PhotoData(val name: String, val bytes: ByteArray, val sha256: String)

data class PendingOperation(
    val id: String,
    val type: String,
    val capturedAt: String,
    val data: JSONObject,
    val status: String = "pendiente",
    val detail: String = ""
) {
    fun wireJson(): JSONObject = JSONObject()
        .put("id_operacion", id).put("tipo", type).put("capturado_en", capturedAt).put("datos", data)

    fun toJson(): JSONObject = wireJson().put("status_local", status).put("detalle_local", detail)

    companion object {
        fun create(type: String, data: JSONObject) = PendingOperation(
            UUID.randomUUID().toString(), type, OffsetDateTime.now().toString(), data)
        fun fromJson(x: JSONObject) = PendingOperation(
            x.getString("id_operacion"), x.getString("tipo"), x.getString("capturado_en"),
            x.getJSONObject("datos"), x.optString("status_local", "pendiente"),
            x.optString("detalle_local"))
    }
}

fun JSONArray.items(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONObject.list(field: String): List<JSONObject> = optJSONArray(field)?.items().orEmpty()
