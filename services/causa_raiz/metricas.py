"""Consultas de tasas por cohorte de venta, para alertas y medicion de eficacia.

Una cohorte es lo VENDIDO en un periodo y lo que de ello se devolvio, sin
importar cuando se devolvio. Asi una devolucion que llega semanas despues se
cuenta con su venta, no con el mes en que se registro.

Las columnas SQL salen de listas blancas de este modulo, nunca de la peticion.
Trazabilidad: RF-23, RF-24, RN-09, RN-16.
"""
import reglas
from shared.infra import consultar

# Columna que identifica al objeto en el cruce venta_detalle -> ventas -> lotes.
COLUMNAS = {"lote": "vd.lote_id", "proveedor": "l.proveedor_id",
            "tienda": "v.tienda_id", "producto": "l.producto_id"}
ETIQUETAS = {
    "lote": "l.numero_lote || ' (' || p.nombre || ')'",
    "proveedor": "pr.nombre", "tienda": "t.nombre", "producto": "p.nombre",
}
DESTINO_ETIQUETA = {
    "lote": "SELECT l.numero_lote || ' (' || p.nombre || ')' AS e FROM lotes l "
            "JOIN productos p ON p.id = l.producto_id WHERE l.id = %s",
    "proveedor": "SELECT nombre AS e FROM proveedores WHERE id = %s",
    "tienda": "SELECT nombre AS e FROM tiendas WHERE id = %s",
    "producto": "SELECT nombre AS e FROM productos WHERE id = %s",
}

CRUCE = """
  FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
  JOIN tiendas t ON t.id = v.tienda_id
  JOIN lotes l ON l.id = vd.lote_id
  JOIN productos p ON p.id = l.producto_id
  JOIN proveedores pr ON pr.id = l.proveedor_id
  LEFT JOIN (SELECT venta_detalle_id, SUM(cantidad_devuelta) AS u, COUNT(*) AS c
               FROM devoluciones WHERE eliminado_en IS NULL
              GROUP BY venta_detalle_id) dev ON dev.venta_detalle_id = vd.id
 WHERE v.eliminado_en IS NULL
"""


def etiqueta(dimension, referencia_id):
    """Nombre legible del objeto, o None si no existe (valida la referencia)."""
    fila = consultar(DESTINO_ETIQUETA[dimension], (referencia_id,), uno=True)
    return fila["e"] if fila else None


def cohorte(dimension, referencia_id, desde=None, hasta=None):
    """Unidades vendidas y devueltas de un objeto; desde y hasta incluyen el dia."""
    condiciones, params = "", [referencia_id]
    if desde:
        condiciones += " AND v.fecha_venta >= %s"
        params.append(desde)
    if hasta:
        condiciones += " AND v.fecha_venta <= %s"
        params.append(hasta)
    fila = consultar(
        f"SELECT COALESCE(SUM(vd.cantidad),0) AS vendidas, COALESCE(SUM(dev.u),0) AS devueltas, "
        f"COALESCE(SUM(dev.c),0) AS casos {CRUCE} AND {COLUMNAS[dimension]} = %s{condiciones}",
        tuple(params), uno=True)
    return {"unidades_vendidas": int(fila["vendidas"]),
            "unidades_devueltas": int(fila["devueltas"]), "casos": int(fila["casos"])}


def linea_base(dimension, referencia_id, hoy):
    """Foto de la tasa al abrir la investigacion, para contrastar despues."""
    c = cohorte(dimension, referencia_id)
    return {**c, "tasa_pct": reglas.tasa(c["unidades_devueltas"], c["unidades_vendidas"]),
            "fecha_corte": hoy.isoformat()}


def plazo_maximo():
    """Dias del plazo de devolucion mas largo (RN-16); una venta tarda eso en 'madurar'."""
    fila = consultar("SELECT MAX(dias_plazo) AS d FROM politicas_devolucion", uno=True)
    return int(fila["d"]) if fila and fila["d"] else reglas.PLAZO_PREDETERMINADO


def detectar():
    """Objetos cuyo patron amerita una alerta, sin los que ya se investigan.

    Devuelve (candidatos, tasa_promedio_global).
    """
    promedio = None
    candidatos = []
    activos = {(f["dimension"], f["referencia_id"]) for f in consultar(
        "SELECT dimension, referencia_id FROM investigaciones WHERE estado <> 'cerrada'")}
    for dimension in reglas.DIMENSIONES:
        col, etiq = COLUMNAS[dimension], ETIQUETAS[dimension]
        filas = consultar(
            f"SELECT {col} AS id, {etiq} AS etiqueta, SUM(vd.cantidad) AS vendidas, "
            f"COALESCE(SUM(dev.u),0) AS devueltas, COALESCE(SUM(dev.c),0) AS casos "
            f"{CRUCE} GROUP BY {col}, {etiq}")
        if promedio is None:  # el promedio global es el mismo en cualquier dimension
            promedio = reglas.tasa(sum(f["devueltas"] for f in filas), sum(f["vendidas"] for f in filas))
        for f in filas:
            if (dimension, f["id"]) in activos:
                continue
            veces = reglas.evaluar_alerta(int(f["vendidas"]), int(f["devueltas"]), int(f["casos"]), promedio)
            if veces is not None:
                candidatos.append({"dimension": dimension, "referencia_id": f["id"],
                                   "etiqueta": f["etiqueta"], "unidades_vendidas": int(f["vendidas"]),
                                   "unidades_devueltas": int(f["devueltas"]), "casos": int(f["casos"]),
                                   "tasa_pct": reglas.tasa(f["devueltas"], f["vendidas"]),
                                   "tasa_promedio_pct": promedio, "veces_promedio": veces})
    candidatos.sort(key=lambda c: (-c["veces_promedio"], c["dimension"], c["referencia_id"]))
    return candidatos, promedio


def devolucion_pertenece(devolucion_id, dimension, referencia_id):
    """True si la devolucion es del objeto investigado (evita evidencia ajena)."""
    return bool(consultar(
        f"SELECT 1 FROM devoluciones d JOIN venta_detalle vd ON vd.id = d.venta_detalle_id "
        f"JOIN ventas v ON v.id = vd.venta_id JOIN lotes l ON l.id = vd.lote_id "
        f"WHERE d.id = %s AND d.eliminado_en IS NULL AND {COLUMNAS[dimension]} = %s",
        (devolucion_id, referencia_id), uno=True))
