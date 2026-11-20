"""Reglas puras de integraciones y monitoreo (dominios 21 y 22).

Sin base de datos ni Flask para probarlas con pruebas unitarias.
"""
import math
import re
from datetime import date

SISTEMAS = ("pos", "erp", "wms", "transportista", "financiero")
# Tabla de cada tipo de entidad que se puede conciliar. La escribe el codigo,
# nunca viene de la peticion (RNF-11).
TABLA_POR_TIPO = {
    "tienda": "tiendas", "venta": "ventas", "producto": "productos",
    "devolucion": "devoluciones", "recoleccion": "recolecciones",
}
ID_EXTERNO = re.compile(r"^[A-Za-z0-9_.:/-]{1,64}$")
MAX_LINEAS = 100

# Avance de una recoleccion que puede reportar el transportista (mismas
# transiciones que logistica).
TRANSICIONES_TRANSPORTISTA = {
    "asignada": ("en_transito", "fallida"),
    "en_transito": ("completada", "fallida"),
}

UMBRAL_MS = 1500          # respuesta mas lenta = alerta
MAX_CONFLICTOS_24H = 10   # conflictos de sincronizacion antes de alertar


# --------------------------------------------------------------------------- #
# Integraciones
# --------------------------------------------------------------------------- #
def id_externo_valido(valor):
    texto = str(valor or "").strip()
    return texto if ID_EXTERNO.fullmatch(texto) else None


def problemas_de_venta(datos, hoy):
    """Lista de problemas de una venta del POS; vacia si se puede importar.

    Valida forma, no existencia: si la tienda, el cliente o el lote existen lo
    decide la base despues.
    """
    problemas = []
    if not id_externo_valido(datos.get("id_externo")):
        problemas.append({"campo": "id_externo", "problema": "1 a 64 letras, numeros o _ . : / -"})
    if not id_externo_valido(datos.get("tienda_externa")):
        problemas.append({"campo": "tienda_externa", "problema": "1 a 64 letras, numeros o _ . : / -"})
    if "@" not in str(datos.get("cliente_email") or ""):
        problemas.append({"campo": "cliente_email", "problema": "correo invalido"})
    try:
        fecha = date.fromisoformat(str(datos.get("fecha_venta") or "").strip())
        if fecha > hoy:
            problemas.append({"campo": "fecha_venta", "problema": "no puede estar en el futuro"})
    except ValueError:
        problemas.append({"campo": "fecha_venta", "problema": "usa AAAA-MM-DD"})
    lineas = datos.get("lineas")
    if not isinstance(lineas, list) or not 1 <= len(lineas) <= MAX_LINEAS:
        problemas.append({"campo": "lineas", "problema": f"lista de 1 a {MAX_LINEAS} lineas"})
        return problemas
    for i, linea in enumerate(lineas):
        if not isinstance(linea, dict):
            problemas.append({"campo": f"lineas[{i}]", "problema": "debe ser objeto"})
            continue
        if not str(linea.get("sku") or "").strip() or not str(linea.get("numero_lote") or "").strip():
            problemas.append({"campo": f"lineas[{i}]", "problema": "sku y numero_lote obligatorios"})
        try:
            if isinstance(linea.get("cantidad"), bool) or int(linea.get("cantidad")) < 1:
                raise ValueError
        except (TypeError, ValueError):
            problemas.append({"campo": f"lineas[{i}].cantidad", "problema": "entero positivo"})
        try:
            precio = float(linea.get("precio_unitario"))
            if not math.isfinite(precio) or precio < 0:
                raise ValueError
        except (TypeError, ValueError):
            problemas.append({"campo": f"lineas[{i}].precio_unitario", "problema": "numero mayor o igual a 0"})
    return problemas


def folio_de_pos(id_externo):
    """Folio interno de una venta importada del POS (folio_venta es VARCHAR(50))."""
    return ("POS-" + id_externo)[:50]


# --------------------------------------------------------------------------- #
# Monitoreo
# --------------------------------------------------------------------------- #
def estado_servicio(codigo, cuerpo):
    """ok, degradado o caido segun la respuesta de /health."""
    estado = (cuerpo or {}).get("estado") if isinstance(cuerpo, dict) else None
    if codigo == 200 and estado in ("ok", None):
        return "ok"
    if codigo in (200, 503) and estado == "degradado":
        return "degradado"
    return "caido"


def alertas_detectadas(chequeo, umbral_ms=UMBRAL_MS, max_conflictos=MAX_CONFLICTOS_24H):
    """Alertas que dispara un chequeo. Cada una: tipo, recurso, severidad, mensaje."""
    alertas = []
    for s in chequeo.get("servicios", []):
        if s["estado"] == "caido":
            alertas.append({"tipo": "servicio_caido", "recurso": s["servicio"], "severidad": "alta",
                            "mensaje": f"{s['servicio']} no responde ({s.get('error') or s.get('codigo')})."})
        elif s["estado"] == "degradado":
            malas = [k for k, ok in (s.get("dependencias") or {}).items() if not ok]
            alertas.append({"tipo": "servicio_degradado", "recurso": s["servicio"], "severidad": "media",
                            "mensaje": f"{s['servicio']} degradado: falla {', '.join(malas) or 'una dependencia'}."})
        if s["estado"] != "caido" and s.get("ms") is not None and s["ms"] > umbral_ms:
            alertas.append({"tipo": "respuesta_lenta", "recurso": s["servicio"], "severidad": "media",
                            "mensaje": f"{s['servicio']} tardo {s['ms']} ms (umbral {umbral_ms} ms)."})
    for nombre, base in (chequeo.get("bases") or {}).items():
        if not base.get("ok"):
            alertas.append({"tipo": "base_no_disponible", "recurso": nombre, "severidad": "alta",
                            "mensaje": f"{nombre} no responde."})
    colas = chequeo.get("colas") or {}
    conflictos = (colas.get("operaciones_offline") or {}).get("conflicto_24h", 0)
    if conflictos > max_conflictos:
        alertas.append({"tipo": "conflictos_sincronizacion", "recurso": "operaciones_offline",
                        "severidad": "media",
                        "mensaje": f"{conflictos} conflictos de sincronizacion en 24 h (umbral {max_conflictos})."})
    return alertas


def recursos_revisados(chequeo):
    """Lo que se reviso en este chequeo: solo esas alertas se pueden resolver."""
    revisados = {s["servicio"] for s in chequeo.get("servicios", [])}
    revisados |= set((chequeo.get("bases") or {}).keys())
    if (chequeo.get("colas") or {}).get("operaciones_offline") is not None:
        revisados.add("operaciones_offline")
    return revisados


def percentil(valores, p):
    """Percentil por rango mas cercano; None si no hay valores."""
    if not valores:
        return None
    ordenados = sorted(valores)
    rango = max(1, math.ceil(p / 100 * len(ordenados)))
    return ordenados[rango - 1]


def disponibilidad(chequeos):
    """Resumen por servicio a partir de los chequeos guardados."""
    por_servicio = {}
    for chequeo in chequeos:
        for s in chequeo.get("servicios", []):
            d = por_servicio.setdefault(s["servicio"], {"chequeos": 0, "ok": 0, "degradado": 0,
                                                        "caido": 0, "tiempos": []})
            d["chequeos"] += 1
            d[s["estado"]] += 1
            if s["estado"] != "caido" and s.get("ms") is not None:
                d["tiempos"].append(s["ms"])
    resumen = []
    for nombre in sorted(por_servicio):
        d = por_servicio[nombre]
        tiempos = d.pop("tiempos")
        resumen.append({
            "servicio": nombre, **d,
            "disponibilidad_pct": round(100 * d["ok"] / d["chequeos"], 2),
            "ms_promedio": round(sum(tiempos) / len(tiempos)) if tiempos else None,
            "ms_p95": percentil(tiempos, 95),
        })
    return resumen
