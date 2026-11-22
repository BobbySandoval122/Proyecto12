"""Lotes, series y trazabilidad (dominio 9 del tercer parcial, dentro de 8006).

De cada producto se puede saber su lote, serie, proveedor, tienda, venta y
recorrido (recoleccion, ruta, transportista, recepcion, inspeccion, disposicion).
Tambien entrega las TASAS de devolucion (unidades devueltas entre unidades
vendidas) por proveedor, tienda, producto, lote y ruta, que es la base del
analisis causal (RF-23, RF-24).

Todo es de LECTURA salvo el alta de series. Los datos orientan una
investigacion; no determinan una causa (RN-09). Los clientes no consultan
trazabilidad: expone proveedores y costos internos (RN-13, RN-15).

Trazabilidad: RF-05, RF-23, RF-24, RN-09, RN-10, RN-13, RNF-11.
"""
import os
from datetime import date

from flask import Blueprint, g, request

import reglas
from shared.infra import consultar, ejecutar, registrar_bitacora
from shared.paginacion import leer_paginacion, paginar
from shared.respuestas import ErrorApi, leer_cuerpo, responder
from shared.seguridad import (ADMINISTRADOR, ANALISTA, COORDINADOR, ENCARGADO_CENTRO,
                              INSPECTOR, OPERADOR_ALMACEN, SUPERVISOR, requiere_jwt)

CONTRATOS = os.path.join(os.path.dirname(__file__), "contratos")
api_trazabilidad = Blueprint("trazabilidad", __name__, url_prefix="/api/v1/trazabilidad")

LECTORES = (ADMINISTRADOR, ANALISTA, INSPECTOR, ENCARGADO_CENTRO, COORDINADOR,
            OPERADOR_ALMACEN, SUPERVISOR)
MAX_DEVOLUCIONES = 100
MAX_SERIES_MUESTRA = 50

# key/etiqueta salen SOLO de esta lista blanca: nunca de la peticion (RNF-11).
DIMENSIONES_VENTA = {
    "proveedor": ("pr.id", "pr.nombre"),
    "tienda": ("t.id", "t.nombre"),
    "producto": ("p.id", "p.nombre"),
    "lote": ("l.id", "l.numero_lote || ' (' || p.nombre || ')'"),
}

# Misma cadena que usa el panel y el recorrido de una devolucion.
SQL_RECORRIDO = """
SELECT d.id AS devolucion_id, d.folio_devolucion, d.estado, d.fecha_solicitud,
       d.cantidad_devuelta, m.nombre AS motivo, t.nombre AS tienda,
       v.folio_venta, l.numero_lote,
       ru.origen || ' -> ' || ru.destino AS ruta, tr.nombre AS transportista,
       rec.estado AS estado_recoleccion, rcp.fecha_recepcion,
       ir.resultado_general AS resultado_inspeccion, ir.apto_para_inventario,
       dis.destino AS destino_disposicion
  FROM devoluciones d
  JOIN motivos m ON m.id = d.motivo_id
  JOIN venta_detalle vd ON vd.id = d.venta_detalle_id
  JOIN ventas v ON v.id = vd.venta_id
  JOIN tiendas t ON t.id = v.tienda_id
  JOIN lotes l ON l.id = vd.lote_id
  LEFT JOIN recolecciones rec ON rec.devolucion_id = d.id
  LEFT JOIN rutas ru ON ru.id = rec.ruta_id
  LEFT JOIN transportistas tr ON tr.id = rec.transportista_id
  LEFT JOIN recepciones rcp ON rcp.devolucion_id = d.id
  LEFT JOIN inspecciones_ref ir ON ir.devolucion_id = d.id
  LEFT JOIN disposiciones dis ON dis.devolucion_id = d.id
 WHERE d.eliminado_en IS NULL AND {filtro}
 ORDER BY d.fecha_solicitud DESC, d.id DESC LIMIT %s
"""


def _fecha(nombre):
    valor = request.args.get(nombre)
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErrorApi(400, "validacion", f"{nombre} debe tener formato AAAA-MM-DD.")


def _recorridos(filtro, params):
    filas = consultar(SQL_RECORRIDO.format(filtro=filtro),
                      tuple(params) + (MAX_DEVOLUCIONES,))
    for f in filas:
        f["recorrido"] = {"ruta": f.pop("ruta"), "transportista": f.pop("transportista"),
                          "estado_recoleccion": f.pop("estado_recoleccion"),
                          "fecha_recepcion": f.pop("fecha_recepcion"),
                          "resultado_inspeccion": f.pop("resultado_inspeccion"),
                          "apto_para_inventario": f.pop("apto_para_inventario"),
                          "destino_disposicion": f.pop("destino_disposicion")}
    return filas


def _resumen_lote(lote_id):
    fila = consultar("""
        SELECT COALESCE(SUM(vd.cantidad),0) AS vendidas,
               COALESCE(SUM(dev.u),0) AS devueltas, COALESCE(SUM(dev.c),0) AS casos
          FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
          LEFT JOIN (SELECT venta_detalle_id, SUM(cantidad_devuelta) u, COUNT(*) c
                       FROM devoluciones WHERE eliminado_en IS NULL
                      GROUP BY venta_detalle_id) dev ON dev.venta_detalle_id = vd.id
         WHERE vd.lote_id = %s AND v.eliminado_en IS NULL
    """, (lote_id,), uno=True)
    global_ = _tasa_global()
    t = reglas.tasa(fila["devueltas"], fila["vendidas"])
    return {"unidades_vendidas": int(fila["vendidas"]),
            "unidades_devueltas": int(fila["devueltas"]),
            "devoluciones": int(fila["casos"]), "tasa_pct": t,
            "tasa_global_pct": global_,
            "veces_promedio": round(t / global_, 2) if t is not None and global_ else None}


def _tasa_global():
    fila = consultar("""
        SELECT COALESCE(SUM(vd.cantidad),0) AS vendidas,
               (SELECT COALESCE(SUM(cantidad_devuelta),0) FROM devoluciones
                 WHERE eliminado_en IS NULL) AS devueltas
          FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
         WHERE v.eliminado_en IS NULL
    """, uno=True)
    return reglas.tasa(fila["devueltas"], fila["vendidas"])


@api_trazabilidad.get("/lotes")
@requiere_jwt(*LECTORES)
def lotes():
    """Lotes con su tasa, para encontrar los que tienen problemas recurrentes."""
    pag = leer_paginacion()
    condiciones, params = ["TRUE"], []
    q = (request.args.get("q") or "").strip()
    if len(q) > 100:
        raise ErrorApi(400, "validacion", "La busqueda no puede superar 100 caracteres.")
    if q:
        condiciones.append("(l.numero_lote ILIKE %s OR p.nombre ILIKE %s)")
        params += ["%" + q + "%"] * 2
    for campo, columna in (("proveedor_id", "l.proveedor_id"), ("producto_id", "l.producto_id")):
        valor = request.args.get(campo)
        if valor:
            if not valor.isdigit():
                raise ErrorApi(400, "validacion", f"{campo} debe ser un entero.")
            condiciones.append(f"{columna} = %s")
            params.append(int(valor))
    solo = request.args.get("solo_con_devoluciones", "false").lower() == "true"
    where = " AND ".join(condiciones)
    base = f"""
      FROM lotes l JOIN productos p ON p.id = l.producto_id
      JOIN proveedores pr ON pr.id = l.proveedor_id
      LEFT JOIN (SELECT vd.lote_id, SUM(vd.cantidad) vendidas
                   FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
                  WHERE v.eliminado_en IS NULL GROUP BY vd.lote_id) ve ON ve.lote_id = l.id
      LEFT JOIN (SELECT vd.lote_id, SUM(d.cantidad_devuelta) devueltas, COUNT(*) casos
                   FROM devoluciones d JOIN venta_detalle vd ON vd.id = d.venta_detalle_id
                  WHERE d.eliminado_en IS NULL GROUP BY vd.lote_id) de ON de.lote_id = l.id
     WHERE {where}{' AND COALESCE(de.casos,0) > 0' if solo else ''}
    """
    total = consultar(f"SELECT COUNT(*) AS n {base}", tuple(params), uno=True)["n"]
    filas = consultar(f"""
        SELECT l.id, l.numero_lote, p.id AS producto_id, p.nombre AS producto,
               p.clasificacion_temperatura, pr.id AS proveedor_id, pr.nombre AS proveedor,
               COALESCE(ve.vendidas,0) AS unidades_vendidas,
               COALESCE(de.devueltas,0) AS unidades_devueltas,
               COALESCE(de.casos,0) AS devoluciones
        {base}
        ORDER BY COALESCE(de.devueltas,0) * 1.0 / NULLIF(ve.vendidas,0) DESC NULLS LAST, l.id
        LIMIT %s OFFSET %s
    """, tuple(params) + (pag.limite, pag.desplazamiento))
    for f in filas:
        f["tasa_pct"] = reglas.tasa(f["unidades_devueltas"], f["unidades_vendidas"])
    return responder(paginar(filas, total, pag), raiz="lotes")


@api_trazabilidad.get("/lotes/<int:lote_id>")
@requiere_jwt(*LECTORES)
def trazabilidad_lote(lote_id):
    lote = consultar("""
        SELECT l.id, l.numero_lote, l.fecha_fabricacion, l.fecha_caducidad, l.activo,
               p.id AS producto_id, p.sku, p.nombre AS producto, p.clasificacion_temperatura,
               pr.id AS proveedor_id, pr.nombre AS proveedor
          FROM lotes l JOIN productos p ON p.id = l.producto_id
          JOIN proveedores pr ON pr.id = l.proveedor_id
         WHERE l.id = %s
    """, (lote_id,), uno=True)
    if not lote:
        raise ErrorApi(404, "no_encontrado", "Lote inexistente.")
    lote["resumen"] = _resumen_lote(lote_id)
    lote["tiendas"] = consultar("""
        SELECT t.id, t.nombre AS tienda, COUNT(DISTINCT v.id) AS ventas,
               SUM(vd.cantidad) AS unidades_vendidas,
               COALESCE(SUM(dev.u),0) AS unidades_devueltas
          FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
          JOIN tiendas t ON t.id = v.tienda_id
          LEFT JOIN (SELECT venta_detalle_id, SUM(cantidad_devuelta) u FROM devoluciones
                      WHERE eliminado_en IS NULL GROUP BY venta_detalle_id) dev
                 ON dev.venta_detalle_id = vd.id
         WHERE vd.lote_id = %s AND v.eliminado_en IS NULL
         GROUP BY t.id, t.nombre ORDER BY unidades_devueltas DESC, t.id
    """, (lote_id,))
    for t in lote["tiendas"]:
        t["tasa_pct"] = reglas.tasa(t["unidades_devueltas"], t["unidades_vendidas"])
    series = consultar("""
        SELECT s.numero_serie, s.venta_detalle_id IS NOT NULL AS vendida, v.folio_venta
          FROM series_producto s LEFT JOIN venta_detalle vd ON vd.id = s.venta_detalle_id
          LEFT JOIN ventas v ON v.id = vd.venta_id
         WHERE s.lote_id = %s AND s.activo ORDER BY s.numero_serie LIMIT %s
    """, (lote_id, MAX_SERIES_MUESTRA))
    total_series = consultar("SELECT COUNT(*) AS n FROM series_producto WHERE lote_id=%s",
                             (lote_id,), uno=True)["n"]
    lote["series"] = {"total": total_series, "muestra": series}
    lote["devoluciones"] = _recorridos("l.id = %s", (lote_id,))
    lote["aviso"] = "Patron para revision humana; no confirma causalidad (RN-09)."
    return responder(lote, raiz="lote")


@api_trazabilidad.get("/series/<numero_serie>")
@requiere_jwt(*LECTORES)
def trazabilidad_serie(numero_serie):
    if not reglas.PATRON_SERIE.match(numero_serie):
        raise ErrorApi(400, "validacion", "Numero de serie con formato invalido.")
    serie = consultar("""
        SELECT s.numero_serie, s.lote_id, s.venta_detalle_id, s.activo,
               l.numero_lote, p.id AS producto_id, p.sku, p.nombre AS producto,
               pr.id AS proveedor_id, pr.nombre AS proveedor
          FROM series_producto s JOIN lotes l ON l.id = s.lote_id
          JOIN productos p ON p.id = l.producto_id
          JOIN proveedores pr ON pr.id = l.proveedor_id
         WHERE s.numero_serie = %s
    """, (numero_serie,), uno=True)
    if not serie:
        raise ErrorApi(404, "no_encontrado", "Serie inexistente.")
    detalle_id = serie.pop("venta_detalle_id")
    serie["venta"] = None
    serie["devoluciones"] = []
    if detalle_id:
        serie["venta"] = consultar("""
            SELECT v.id AS venta_id, v.folio_venta, v.fecha_venta,
                   t.id AS tienda_id, t.nombre AS tienda
              FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
              JOIN tiendas t ON t.id = v.tienda_id WHERE vd.id = %s
        """, (detalle_id,), uno=True)
        serie["devoluciones"] = _recorridos("vd.id = %s", (detalle_id,))
    serie["estado"] = ("devuelta" if serie["devoluciones"]
                       else "vendida" if detalle_id else "en_almacen")
    return responder(serie, raiz="serie")


@api_trazabilidad.post("/lotes/<int:lote_id>/series")
@requiere_jwt(ADMINISTRADOR)
def alta_series(lote_id):
    """Idempotente: repetir el envio no duplica ni falla por series ya registradas."""
    datos = leer_cuerpo(xsd=os.path.join(CONTRATOS, "series.xsd"))
    series = reglas.validar_series(datos)
    if not consultar("SELECT id FROM lotes WHERE id=%s AND activo=TRUE", (lote_id,), uno=True):
        raise ErrorApi(404, "no_encontrado", "Lote inexistente o inactivo.")
    existentes = {f["numero_serie"]: f["lote_id"] for f in consultar(
        "SELECT numero_serie, lote_id FROM series_producto WHERE numero_serie = ANY(%s)",
        (series,))}
    ajenas = sorted(s for s, l in existentes.items() if l != lote_id)
    if ajenas:
        raise ErrorApi(409, "serie_duplicada",
                       "Hay series que ya pertenecen a otro lote.",
                       [{"campo": "series", "problema": s} for s in ajenas[:20]])
    nuevas = [s for s in series if s not in existentes]
    for s in nuevas:
        ejecutar("INSERT INTO series_producto (lote_id, numero_serie) VALUES (%s,%s)",
                 (lote_id, s))
    registrar_bitacora("alta_series", "lotes", lote_id, f"Series nuevas: {len(nuevas)}")
    return responder({"lote_id": lote_id, "registradas": len(nuevas),
                      "ya_existian": len(series) - len(nuevas)}, 201, "lote_series")


@api_trazabilidad.patch("/series/<numero_serie>/venta")
@requiere_jwt(ADMINISTRADOR, OPERADOR_ALMACEN)
def vincular_venta(numero_serie):
    """Liga una serie a la linea de venta donde salio; no mas series que unidades."""
    datos = leer_cuerpo(xsd=os.path.join(CONTRATOS, "serie_venta.xsd"))
    detalle_id = datos.get("venta_detalle_id")
    try:
        if isinstance(detalle_id, bool):
            raise ValueError
        detalle_id = int(detalle_id)
        if detalle_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ErrorApi(400, "validacion", "venta_detalle_id debe ser un entero positivo.")
    serie = consultar("SELECT lote_id, venta_detalle_id FROM series_producto "
                      "WHERE numero_serie=%s AND activo", (numero_serie,), uno=True)
    if not serie:
        raise ErrorApi(404, "no_encontrado", "Serie inexistente.")
    if serie["venta_detalle_id"] == detalle_id:
        return responder({"numero_serie": numero_serie, "venta_detalle_id": detalle_id,
                          "sin_cambios": True}, raiz="serie")
    if serie["venta_detalle_id"] is not None:
        raise ErrorApi(409, "serie_vendida", "La serie ya esta ligada a otra venta.")
    detalle = consultar("SELECT lote_id, cantidad FROM venta_detalle WHERE id=%s",
                        (detalle_id,), uno=True)
    if not detalle:
        raise ErrorApi(404, "no_encontrado", "Linea de venta inexistente.")
    if detalle["lote_id"] != serie["lote_id"]:
        raise ErrorApi(409, "lote_distinto", "La linea de venta es de otro lote.")
    ligadas = consultar("SELECT COUNT(*) AS n FROM series_producto WHERE venta_detalle_id=%s",
                        (detalle_id,), uno=True)["n"]
    if ligadas >= detalle["cantidad"]:
        raise ErrorApi(409, "sin_unidades", "La linea ya tiene tantas series como unidades.")
    ejecutar("UPDATE series_producto SET venta_detalle_id=%s WHERE numero_serie=%s",
             (detalle_id, numero_serie))
    registrar_bitacora("serie_vendida", "series_producto", None,
                       f"Serie {numero_serie} ligada a la linea {detalle_id}")
    return responder({"numero_serie": numero_serie, "venta_detalle_id": detalle_id},
                     raiz="serie")


@api_trazabilidad.get("/tasas")
@requiere_jwt(*LECTORES)
def tasas():
    """Tasa de devolucion por dimension.

    proveedor, tienda, producto y lote: unidades devueltas entre vendidas, igual
    que el panel de causas del web (mismo conteo, sin descartar rechazadas).
    ruta: no existe 'vendido por ruta'; se mide el dano, es decir, inspecciones
    no aptas entre recolecciones inspeccionadas que pasaron por esa ruta.
    """
    por = reglas.validar_dimension(request.args.get("por", "proveedor"))
    desde, hasta = _fecha("desde"), _fecha("hasta")
    if desde and hasta and hasta < desde:
        raise ErrorApi(400, "validacion", "hasta no puede ser menor que desde.")
    if por == "ruta":
        return responder(_tasas_ruta(desde, hasta), raiz="tasas")

    key, etiqueta = DIMENSIONES_VENTA[por]
    cond_dev, p_dev, cond_ven, p_ven = "", [], "", []
    if desde:
        cond_dev += " AND fecha_solicitud >= %s"
        p_dev.append(desde)
        cond_ven += " AND v.fecha_venta >= %s"
        p_ven.append(desde)
    if hasta:
        cond_dev += " AND fecha_solicitud < (%s::date + INTERVAL '1 day')"
        p_dev.append(hasta)
        cond_ven += " AND v.fecha_venta < (%s::date + INTERVAL '1 day')"
        p_ven.append(hasta)
    # key y etiqueta provienen de DIMENSIONES_VENTA, no del usuario.
    filas = consultar(f"""
        WITH dev AS (
            SELECT venta_detalle_id, SUM(cantidad_devuelta) AS u, COUNT(*) AS c
              FROM devoluciones WHERE eliminado_en IS NULL{cond_dev}
             GROUP BY venta_detalle_id)
        SELECT {key} AS id, {etiqueta} AS etiqueta,
               SUM(vd.cantidad) AS unidades_vendidas,
               COALESCE(SUM(dev.u),0) AS unidades_devueltas,
               COALESCE(SUM(dev.c),0) AS devoluciones
          FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
          JOIN tiendas t ON t.id = v.tienda_id
          JOIN lotes l ON l.id = vd.lote_id
          JOIN productos p ON p.id = l.producto_id
          JOIN proveedores pr ON pr.id = l.proveedor_id
          LEFT JOIN dev ON dev.venta_detalle_id = vd.id
         WHERE v.eliminado_en IS NULL{cond_ven}
         GROUP BY {key}, {etiqueta}
    """, tuple(p_dev + p_ven))
    vendidas = sum(f["unidades_vendidas"] for f in filas)
    devueltas = sum(f["unidades_devueltas"] for f in filas)
    promedio = reglas.tasa(devueltas, vendidas)
    for f in filas:
        f["tasa_pct"] = reglas.tasa(f["unidades_devueltas"], f["unidades_vendidas"])
        f["veces_promedio"] = (round(f["tasa_pct"] / promedio, 2)
                               if f["tasa_pct"] is not None and promedio else None)
    filas.sort(key=lambda f: (f["tasa_pct"] is None, -(f["tasa_pct"] or 0), f["id"]))
    return responder({"por": por, "medida": "unidades_devueltas/unidades_vendidas",
                      "tasa_promedio_pct": promedio, "datos": filas,
                      "interpretacion": "Patrones para revision humana; no confirman causalidad."},
                     raiz="tasas")


def _tasas_ruta(desde, hasta):
    cond, params = "", []
    if desde:
        cond += " AND d.fecha_solicitud >= %s"
        params.append(desde)
    if hasta:
        cond += " AND d.fecha_solicitud < (%s::date + INTERVAL '1 day')"
        params.append(hasta)
    filas = consultar(f"""
        SELECT ru.id, ru.origen || ' -> ' || ru.destino AS etiqueta,
               COUNT(rec.id) AS recolecciones, COUNT(ir.id) AS inspeccionadas,
               COUNT(*) FILTER (WHERE ir.apto_para_inventario = FALSE) AS con_dano
          FROM recolecciones rec JOIN rutas ru ON ru.id = rec.ruta_id
          JOIN devoluciones d ON d.id = rec.devolucion_id AND d.eliminado_en IS NULL
          LEFT JOIN inspecciones_ref ir ON ir.devolucion_id = d.id
         WHERE TRUE{cond} GROUP BY ru.id, ru.origen, ru.destino
    """, tuple(params))
    total_i = sum(f["inspeccionadas"] for f in filas)
    total_d = sum(f["con_dano"] for f in filas)
    promedio = reglas.tasa(total_d, total_i)
    for f in filas:
        f["tasa_pct"] = reglas.tasa(f["con_dano"], f["inspeccionadas"])
        f["veces_promedio"] = (round(f["tasa_pct"] / promedio, 2)
                               if f["tasa_pct"] is not None and promedio else None)
    filas.sort(key=lambda f: (f["tasa_pct"] is None, -(f["tasa_pct"] or 0), f["id"]))
    return {"por": "ruta", "medida": "inspecciones_no_aptas/inspecciones_realizadas",
            "tasa_promedio_pct": promedio, "datos": filas,
            "interpretacion": "Patrones para revision humana; no confirman causalidad."}
