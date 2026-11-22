"""Reglas puras de proveedores y reclamaciones (sin base de datos).

Trazabilidad: RF-23, RF-24, RF-26, RN-09, RN-12.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from shared.respuestas import ErrorApi

# Una tasa calculada con pocas unidades no dice nada del proveedor (RN-09).
MIN_UNIDADES = 20
UMBRAL_ATENCION = 1.25
UMBRAL_CRITICO = 2.0
MAX_MONTO = Decimal("10000000")
MAX_DEVOLUCIONES = 100

ESTADOS = ("abierta", "enviada", "en_analisis", "respondida", "cerrada")
TRANSICIONES = {
    "abierta": {"enviada", "cerrada"},
    "enviada": {"en_analisis", "respondida", "cerrada"},
    "en_analisis": {"respondida", "cerrada"},
    "respondida": {"en_analisis", "cerrada"},
    "cerrada": set(),
}
RESOLUCIONES = ("aceptada", "parcial", "rechazada", "retirada")
# Solo se puede aceptar o rechazar lo que el proveedor ya respondio.
RESOLUCIONES_CON_RESPUESTA = ("aceptada", "parcial", "rechazada")


def tasa(devueltas, vendidas):
    vendidas = float(vendidas or 0)
    if vendidas <= 0:
        return None
    return round(float(devueltas or 0) * 100.0 / vendidas, 2)


def semaforo(tasa_pct, promedio_pct, unidades_vendidas):
    """Clasifica por cuantas veces supera el promedio de todos los proveedores.

    Orienta a quien revisa; no es un juicio sobre el proveedor (RN-09).
    """
    if tasa_pct is None or not promedio_pct or (unidades_vendidas or 0) < MIN_UNIDADES:
        return "sin_datos"
    veces = tasa_pct / promedio_pct
    if veces >= UMBRAL_CRITICO:
        return "critico"
    if veces >= UMBRAL_ATENCION:
        return "atencion"
    return "normal"


def entero_positivo(valor, campo):
    try:
        if isinstance(valor, bool):
            raise ValueError
        numero = int(valor)
        if numero <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ErrorApi(400, "validacion", f"{campo} debe ser un entero positivo.")
    return numero


def monto(valor, campo, requerido=False):
    """Decimal con a lo mas dos decimales; nunca float, para no arrastrar error binario."""
    if valor is None or valor == "":
        if requerido:
            raise ErrorApi(400, "validacion", f"{campo} es obligatorio.")
        return None
    try:
        if isinstance(valor, bool):
            raise InvalidOperation
        cifra = Decimal(str(valor).strip())
        if not cifra.is_finite() or cifra < 0 or cifra > MAX_MONTO \
                or cifra != cifra.quantize(Decimal("0.01")):
            raise InvalidOperation
    except InvalidOperation:
        raise ErrorApi(400, "validacion",
                       f"{campo} debe ser un monto entre 0 y {MAX_MONTO} con dos decimales como maximo.")
    return cifra.quantize(Decimal("0.01"))


def _texto(datos, campo, maximo, minimo=1, requerido=True):
    valor = datos.get(campo)
    if valor is None or valor == "":
        return (None, {"campo": campo, "problema": "obligatorio"}) if requerido else (None, None)
    if not isinstance(valor, str) or not minimo <= len(valor.strip()) <= maximo:
        return None, {"campo": campo, "problema": f"entre {minimo} y {maximo} caracteres"}
    return valor.strip(), None


def validar_reclamacion(datos, hoy=None):
    hoy = hoy or date.today()
    if not isinstance(datos, dict):
        raise ErrorApi(400, "validacion", "Se requiere un objeto.")
    permitidos = {"proveedor_id", "lote_id", "devolucion_ids", "asunto", "descripcion",
                  "monto_reclamado", "fecha_limite_respuesta"}
    errores, limpio = [], {}
    extra = set(datos) - permitidos
    if extra:
        errores.append({"campo": ",".join(sorted(extra)), "problema": "campo no permitido"})
    for campo, maximo, minimo in (("asunto", 150, 5), ("descripcion", 2000, 10)):
        valor, error = _texto(datos, campo, maximo, minimo)
        limpio[campo] = valor
        if error:
            errores.append(error)
    for campo, requerido in (("proveedor_id", True), ("lote_id", False)):
        if datos.get(campo) in (None, ""):
            limpio[campo] = None
            if requerido:
                errores.append({"campo": campo, "problema": "obligatorio"})
            continue
        try:
            limpio[campo] = entero_positivo(datos[campo], campo)
        except ErrorApi:
            errores.append({"campo": campo, "problema": "entero positivo requerido"})
    ids = datos.get("devolucion_ids")
    if ids in (None, ""):  # una lista XML vacia llega como cadena vacia
        ids = []
    if not isinstance(ids, list) or len(ids) > MAX_DEVOLUCIONES:
        errores.append({"campo": "devolucion_ids", "problema": f"lista de hasta {MAX_DEVOLUCIONES} ids"})
    else:
        try:
            limpio["devolucion_ids"] = sorted({entero_positivo(i, "devolucion_ids") for i in ids})
        except ErrorApi:
            errores.append({"campo": "devolucion_ids", "problema": "enteros positivos"})
    try:
        limpio["monto_reclamado"] = monto(datos.get("monto_reclamado"), "monto_reclamado")
    except ErrorApi as exc:
        errores.append({"campo": "monto_reclamado", "problema": exc.mensaje})
    limite = datos.get("fecha_limite_respuesta")
    limpio["fecha_limite_respuesta"] = None
    if limite not in (None, ""):
        try:
            fecha = date.fromisoformat(str(limite))
            if fecha < hoy:
                raise ValueError
            limpio["fecha_limite_respuesta"] = fecha
        except ValueError:
            errores.append({"campo": "fecha_limite_respuesta",
                            "problema": "fecha AAAA-MM-DD que no sea pasada"})
    if not errores and limpio["lote_id"] is None and not limpio.get("devolucion_ids"):
        errores.append({"campo": "lote_id", "problema": "indica un lote o al menos una devolucion"})
    if errores:
        raise ErrorApi(400, "validacion", "Campos invalidos.", errores)
    return limpio


def validar_seguimiento(datos, reclamacion):
    """Cambio de estado de una reclamacion; devuelve lo que se debe guardar.

    reclamacion trae estado y monto_reclamado actuales. Las reglas evitan, por
    ejemplo, cerrar como aceptada una reclamacion que el proveedor nunca
    respondio, o recuperar mas de lo reclamado.
    """
    if not isinstance(datos, dict):
        raise ErrorApi(400, "validacion", "Se requiere un objeto.")
    extra = set(datos) - {"estado", "comentario", "resolucion", "monto_recuperado"}
    if extra:
        raise ErrorApi(400, "validacion", "Campos invalidos.",
                       [{"campo": ",".join(sorted(extra)), "problema": "campo no permitido"}])
    nuevo = datos.get("estado")
    if nuevo not in ESTADOS:
        raise ErrorApi(400, "validacion", "estado debe ser: " + ", ".join(ESTADOS[1:]) + ".")
    actual = reclamacion["estado"]
    if nuevo not in TRANSICIONES[actual]:
        raise ErrorApi(409, "transicion_invalida",
                       f"No se puede pasar de {actual} a {nuevo}.")
    cierra = nuevo == "cerrada"
    comentario, error = _texto(datos, "comentario", 500, 5, requerido=cierra)
    if error:
        raise ErrorApi(400, "validacion", "Campos invalidos.", [error])
    resolucion = datos.get("resolucion")
    recuperado = datos.get("monto_recuperado")
    if not cierra:
        if resolucion not in (None, "") or recuperado not in (None, ""):
            raise ErrorApi(400, "validacion",
                           "resolucion y monto_recuperado solo aplican al cerrar.")
        return nuevo, comentario, None, None
    if resolucion not in RESOLUCIONES:
        raise ErrorApi(400, "validacion", "resolucion debe ser: " + ", ".join(RESOLUCIONES) + ".")
    if resolucion in RESOLUCIONES_CON_RESPUESTA and actual != "respondida":
        raise ErrorApi(409, "sin_respuesta",
                       f"Solo se cierra como {resolucion} despues de que el proveedor responda.")
    if resolucion in ("rechazada", "retirada"):
        if recuperado not in (None, ""):
            raise ErrorApi(400, "validacion", "No hay monto recuperado si fue rechazada o retirada.")
        return nuevo, comentario, resolucion, Decimal("0.00")
    cifra = monto(recuperado, "monto_recuperado", requerido=True)
    if resolucion == "parcial" and cifra == 0:
        raise ErrorApi(400, "validacion", "Una resolucion parcial recupera algo; usa rechazada.")
    reclamado = reclamacion.get("monto_reclamado")
    if reclamado is not None and cifra > reclamado:
        raise ErrorApi(409, "monto_excedido", "No se puede recuperar mas de lo reclamado.")
    return nuevo, comentario, resolucion, cifra
