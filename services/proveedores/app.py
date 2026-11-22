"""Proveedores, reclamaciones e indicadores de calidad (dominio 13 del tercer parcial).

- Consulta de proveedores con lo que surten e indicadores de calidad: tasa de
  devolucion (unidades devueltas entre vendidas, igual que el panel de causas),
  inspecciones no aptas, costo de sus devoluciones, reclamaciones y tiempo de
  respuesta. Un semaforo orienta la revision; no es un juicio (RN-09).
- Reclamaciones formales con folio, estados controlados, linea de tiempo
  inmutable y cierre con resolucion y monto recuperado.
- El alta y edicion del catalogo de proveedores sigue en ventas-catalogos (8006);
  aqui no se duplica.

Trazabilidad: RF-23, RF-24, RF-26, RF-30, RN-09, RN-12, RN-13, RNF-09, RNF-11.
"""
import os
from datetime import date

from flask import Blueprint, Flask, g, request

import reglas
from shared import docs, respuestas
from shared.infra import (cerrar_conexion, consultar, ejecutar,
                          registrar_bitacora, salud_postgres, salud_redis)
from shared.paginacion import leer_paginacion, paginar
from shared.respuestas import ErrorApi, leer_cuerpo, responder
from shared.seguridad import (ADMINISTRADOR, ANALISTA, ENCARGADO_REEMBOLSOS, SUPERVISOR,
                              requiere_jwt)

NOMBRE = "proveedores"
CONTRATOS = os.path.join(os.path.dirname(__file__), "contratos")
api = Blueprint("proveedores", __name__, url_prefix="/api/v1/proveedores")

LECTORES = (ADMINISTRADOR, ANALISTA, SUPERVISOR, ENCARGADO_REEMBOLSOS)
ESCRITORES = (ADMINISTRADOR, ANALISTA, SUPERVISOR)


def _fecha(nombre):
    valor = request.args.get(nombre)
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErrorApi(400, "validacion", f"{nombre} debe tener formato AAAA-MM-DD.")


def _rango():
    desde, hasta = _fecha("desde"), _fecha("hasta")
    if desde and hasta and hasta < desde:
        raise ErrorApi(400, "validacion", "hasta no puede ser menor que desde.")
    return desde, hasta


def _condicion(columna, desde, hasta):
    """Filtro de fechas con parametros ligados; columna sale del codigo, no del usuario."""
    cond, params = "", []
    if desde:
        cond += f" AND {columna} >= %s"
        params.append(desde)
    if hasta:
        cond += f" AND {columna} < (%s::date + INTERVAL '1 day')"
        params.append(hasta)
    return cond, params


def indicadores(desde=None, hasta=None):
    """Indicadores de todos los proveedores y el promedio contra el que se comparan.

    Se calculan todos juntos porque el semaforo compara cada uno con el
    promedio general; son pocas filas.
    """
    c_dev, p_dev = _condicion("fecha_solicitud", desde, hasta)
    c_ven, p_ven = _condicion("v.fecha_venta", desde, hasta)
    c_ins, p_ins = _condicion("d.fecha_solicitud", desde, hasta)
    filas = consultar(f"""
        WITH dev AS (
            SELECT venta_detalle_id, SUM(cantidad_devuelta) AS u, COUNT(*) AS c
              FROM devoluciones WHERE eliminado_en IS NULL{c_dev} GROUP BY venta_detalle_id),
        base AS (
            SELECT l.proveedor_id, SUM(vd.cantidad) AS vendidas,
                   COALESCE(SUM(dev.u),0) AS devueltas, COALESCE(SUM(dev.c),0) AS casos
              FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
              JOIN lotes l ON l.id = vd.lote_id LEFT JOIN dev ON dev.venta_detalle_id = vd.id
             WHERE v.eliminado_en IS NULL{c_ven} GROUP BY l.proveedor_id),
        insp AS (
            SELECT l.proveedor_id, COUNT(ir.id) AS inspeccionadas,
                   COUNT(*) FILTER (WHERE ir.apto_para_inventario = FALSE) AS no_aptas
              FROM inspecciones_ref ir
              JOIN devoluciones d ON d.id = ir.devolucion_id AND d.eliminado_en IS NULL
              JOIN venta_detalle vd ON vd.id = d.venta_detalle_id
              JOIN lotes l ON l.id = vd.lote_id
             WHERE TRUE{c_ins} GROUP BY l.proveedor_id),
        costo AS (
            SELECT l.proveedor_id, SUM(vc.costo_total) AS total
              FROM vista_costo_devolucion vc
              JOIN devoluciones d ON d.id = vc.devolucion_id AND d.eliminado_en IS NULL
              JOIN venta_detalle vd ON vd.id = d.venta_detalle_id
              JOIN lotes l ON l.id = vd.lote_id
             WHERE TRUE{c_ins} GROUP BY l.proveedor_id),
        resp AS (
            SELECT proveedor_id, AVG(EXTRACT(EPOCH FROM (respondida - enviada)) / 86400.0) AS dias
              FROM (SELECT r.proveedor_id,
                           (SELECT MIN(fecha) FROM seguimiento_reclamacion
                             WHERE reclamacion_id = r.id AND estado_nuevo = 'enviada') AS enviada,
                           (SELECT MIN(fecha) FROM seguimiento_reclamacion
                             WHERE reclamacion_id = r.id AND estado_nuevo = 'respondida') AS respondida
                      FROM reclamaciones_proveedor r) t
             WHERE enviada IS NOT NULL AND respondida IS NOT NULL GROUP BY proveedor_id),
        rec AS (
            SELECT proveedor_id, COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE estado <> 'cerrada') AS abiertas,
                   COALESCE(SUM(monto_reclamado),0) AS reclamado,
                   COALESCE(SUM(monto_recuperado),0) AS recuperado
              FROM reclamaciones_proveedor GROUP BY proveedor_id)
        SELECT pr.id, pr.nombre, pr.activo,
               COALESCE(base.vendidas,0) AS unidades_vendidas,
               COALESCE(base.devueltas,0) AS unidades_devueltas,
               COALESCE(base.casos,0) AS devoluciones,
               COALESCE(insp.inspeccionadas,0) AS inspeccionadas, COALESCE(insp.no_aptas,0) AS no_aptas,
               COALESCE(costo.total,0) AS costo_devoluciones,
               COALESCE(rec.total,0) AS reclamaciones, COALESCE(rec.abiertas,0) AS reclamaciones_abiertas,
               COALESCE(rec.reclamado,0) AS monto_reclamado, COALESCE(rec.recuperado,0) AS monto_recuperado,
               ROUND(resp.dias::numeric, 1) AS dias_respuesta_promedio
          FROM proveedores pr
          LEFT JOIN base ON base.proveedor_id = pr.id LEFT JOIN insp ON insp.proveedor_id = pr.id
          LEFT JOIN costo ON costo.proveedor_id = pr.id LEFT JOIN rec ON rec.proveedor_id = pr.id
          LEFT JOIN resp ON resp.proveedor_id = pr.id
         ORDER BY pr.id
    """, tuple(p_dev + p_ven + p_ins + p_ins))
    promedio = reglas.tasa(sum(f["unidades_devueltas"] for f in filas),
                           sum(f["unidades_vendidas"] for f in filas))
    for f in filas:
        f["tasa_pct"] = reglas.tasa(f["unidades_devueltas"], f["unidades_vendidas"])
        f["veces_promedio"] = (round(f["tasa_pct"] / promedio, 2)
                               if f["tasa_pct"] is not None and promedio else None)
        f["semaforo"] = reglas.semaforo(f["tasa_pct"], promedio, f["unidades_vendidas"])
        f["tasa_no_apto_pct"] = reglas.tasa(f["no_aptas"], f["inspeccionadas"])
    return filas, promedio


def _proveedor_o_404(pid):
    fila = consultar("SELECT id, nombre, contacto, activo FROM proveedores WHERE id=%s", (pid,), uno=True)
    if not fila:
        raise ErrorApi(404, "no_encontrado", "Proveedor inexistente.")
    return fila


# --------------------------------------------------------------------------- #
# Proveedores e indicadores
# --------------------------------------------------------------------------- #
@api.get("")
@requiere_jwt(*LECTORES)
def listado():
    pag = leer_paginacion()
    desde, hasta = _rango()
    filas, promedio = indicadores(desde, hasta)
    if request.args.get("solo_activos", "true").lower() == "true":
        filas = [f for f in filas if f["activo"]]
    q = (request.args.get("q") or "").strip().lower()
    if len(q) > 100:
        raise ErrorApi(400, "validacion", "La busqueda no puede superar 100 caracteres.")
    if q:
        filas = [f for f in filas if q in f["nombre"].lower()]
    filas.sort(key=lambda f: (f["tasa_pct"] is None, -(f["tasa_pct"] or 0), f["id"]))
    pagina = filas[pag.desplazamiento:pag.desplazamiento + pag.limite]
    resultado = paginar(pagina, len(filas), pag)
    resultado["tasa_promedio_pct"] = promedio
    return responder(resultado, raiz="proveedores")


@api.get("/<int:pid>")
@requiere_jwt(*LECTORES)
def detalle(pid):
    proveedor = _proveedor_o_404(pid)
    desde, hasta = _rango()
    filas, promedio = indicadores(desde, hasta)
    proveedor["indicadores"] = next(f for f in filas if f["id"] == pid)
    proveedor["tasa_promedio_pct"] = promedio
    proveedor["productos"] = _productos(pid)
    proveedor["reclamaciones_recientes"] = consultar("""
        SELECT id, folio, asunto, estado, resolucion, fecha_creacion
          FROM reclamaciones_proveedor WHERE proveedor_id=%s
         ORDER BY fecha_creacion DESC, id DESC LIMIT 5""", (pid,))
    proveedor["aviso"] = "Indicadores para revision humana; no determinan responsabilidad (RN-09)."
    return responder(proveedor, raiz="proveedor")


def _productos(pid):
    return consultar("""
        SELECT p.id, p.sku, p.nombre, p.clasificacion_temperatura, p.activo,
               p.proveedor_id = %s AS proveedor_principal,
               COUNT(l.id) FILTER (WHERE l.proveedor_id = %s) AS lotes
          FROM productos p LEFT JOIN lotes l ON l.producto_id = p.id
         WHERE p.proveedor_id = %s OR l.proveedor_id = %s
         GROUP BY p.id ORDER BY p.nombre""", (pid, pid, pid, pid))


@api.get("/<int:pid>/productos")
@requiere_jwt(*LECTORES)
def productos(pid):
    _proveedor_o_404(pid)
    filas = _productos(pid)
    return responder({"datos": filas, "total": len(filas)}, raiz="productos")


@api.get("/<int:pid>/indicadores")
@requiere_jwt(*LECTORES)
def indicadores_proveedor(pid):
    _proveedor_o_404(pid)
    desde, hasta = _rango()
    filas, promedio = indicadores(desde, hasta)
    resultado = next(f for f in filas if f["id"] == pid)
    resultado["tasa_promedio_pct"] = promedio
    resultado["muestra_minima_unidades"] = reglas.MIN_UNIDADES
    resultado["interpretacion"] = "Patrones para revision humana; no confirman causalidad (RN-09)."
    return responder(resultado, raiz="indicadores")


# --------------------------------------------------------------------------- #
# Reclamaciones
# --------------------------------------------------------------------------- #
SQL_RECLAMACION = """
SELECT r.id, r.folio, r.proveedor_id, pr.nombre AS proveedor, r.lote_id, l.numero_lote,
       r.asunto, r.descripcion, r.estado, r.resolucion, r.monto_reclamado, r.monto_recuperado,
       r.fecha_limite_respuesta, r.fecha_creacion, r.fecha_cierre,
       (r.fecha_limite_respuesta < CURRENT_DATE
        AND r.estado IN ('enviada', 'en_analisis')) AS vencida
  FROM reclamaciones_proveedor r JOIN proveedores pr ON pr.id = r.proveedor_id
  LEFT JOIN lotes l ON l.id = r.lote_id
"""


def _validar_origen(limpio):
    """El lote y las devoluciones deben ser realmente del proveedor reclamado."""
    pid = limpio["proveedor_id"]
    _proveedor_o_404(pid)
    if limpio["lote_id"] is not None:
        lote = consultar("SELECT proveedor_id FROM lotes WHERE id=%s", (limpio["lote_id"],), uno=True)
        if not lote:
            raise ErrorApi(404, "no_encontrado", "Lote inexistente.")
        if lote["proveedor_id"] != pid:
            raise ErrorApi(409, "lote_ajeno", "El lote pertenece a otro proveedor.")
    ids = limpio["devolucion_ids"]
    if not ids:
        return
    # FOR UPDATE: dos reclamaciones simultaneas no pueden tomar la misma devolucion.
    filas = consultar("""
        SELECT d.id, l.id AS lote_id, l.proveedor_id
          FROM devoluciones d JOIN venta_detalle vd ON vd.id = d.venta_detalle_id
          JOIN lotes l ON l.id = vd.lote_id
         WHERE d.id = ANY(%s) AND d.eliminado_en IS NULL FOR UPDATE OF d""", (ids,))
    encontradas = {f["id"]: f for f in filas}
    faltan = [i for i in ids if i not in encontradas]
    if faltan:
        raise ErrorApi(404, "no_encontrado", "Devoluciones inexistentes.",
                       [{"campo": "devolucion_ids", "problema": str(i)} for i in faltan[:20]])
    ajenas = [i for i, f in encontradas.items() if f["proveedor_id"] != pid]
    if ajenas:
        raise ErrorApi(409, "devolucion_ajena", "Hay devoluciones de lotes de otro proveedor.",
                       [{"campo": "devolucion_ids", "problema": str(i)} for i in ajenas[:20]])
    if limpio["lote_id"] is not None:
        otro_lote = [i for i, f in encontradas.items() if f["lote_id"] != limpio["lote_id"]]
        if otro_lote:
            raise ErrorApi(409, "devolucion_otro_lote", "Hay devoluciones de un lote distinto al indicado.",
                           [{"campo": "devolucion_ids", "problema": str(i)} for i in otro_lote[:20]])
    ya = consultar("""
        SELECT DISTINCT rd.devolucion_id FROM reclamacion_devoluciones rd
          JOIN reclamaciones_proveedor r ON r.id = rd.reclamacion_id
         WHERE rd.devolucion_id = ANY(%s) AND r.estado <> 'cerrada'""", (ids,))
    if ya:
        raise ErrorApi(409, "devolucion_reclamada",
                       "Hay devoluciones que ya estan en una reclamacion abierta.",
                       [{"campo": "devolucion_ids", "problema": str(f["devolucion_id"])} for f in ya[:20]])


@api.post("/reclamaciones")
@requiere_jwt(*ESCRITORES)
def crear_reclamacion():
    limpio = reglas.validar_reclamacion(
        leer_cuerpo(xsd=os.path.join(CONTRATOS, "reclamacion.xsd")))
    _validar_origen(limpio)
    fila = ejecutar("""
        INSERT INTO reclamaciones_proveedor (proveedor_id, lote_id, asunto, descripcion,
            monto_reclamado, fecha_limite_respuesta, creada_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id, folio""",
        (limpio["proveedor_id"], limpio["lote_id"], limpio["asunto"], limpio["descripcion"],
         limpio["monto_reclamado"], limpio["fecha_limite_respuesta"], g.usuario["id"]),
        devolver=True)
    for did in limpio["devolucion_ids"]:
        ejecutar("INSERT INTO reclamacion_devoluciones (reclamacion_id, devolucion_id) VALUES (%s,%s)",
                 (fila["id"], did))
    ejecutar("""INSERT INTO seguimiento_reclamacion (reclamacion_id, estado_anterior, estado_nuevo,
                    comentario, usuario_id) VALUES (%s,NULL,'abierta','Reclamacion creada',%s)""",
             (fila["id"], g.usuario["id"]))
    registrar_bitacora("alta_reclamacion", "reclamaciones_proveedor", fila["id"],
                       f"{fila['folio']} con {len(limpio['devolucion_ids'])} devoluciones")
    return responder({"id": fila["id"], "folio": fila["folio"], "estado": "abierta"}, 201,
                     "reclamacion", {"Location": f"/api/v1/proveedores/reclamaciones/{fila['id']}"})


@api.get("/reclamaciones")
@requiere_jwt(*LECTORES)
def reclamaciones():
    pag = leer_paginacion()
    condiciones, params = ["TRUE"], []
    estado = request.args.get("estado")
    if estado:
        if estado not in reglas.ESTADOS:
            raise ErrorApi(400, "validacion", "estado desconocido.")
        condiciones.append("r.estado = %s")
        params.append(estado)
    for campo in ("proveedor_id", "lote_id"):
        if request.args.get(campo):
            condiciones.append(f"r.{campo} = %s")
            params.append(reglas.entero_positivo(request.args[campo], campo))
    if request.args.get("vencidas", "false").lower() == "true":
        condiciones.append("r.fecha_limite_respuesta < CURRENT_DATE "
                           "AND r.estado IN ('enviada', 'en_analisis')")
    where = " AND ".join(condiciones)
    total = consultar(f"SELECT COUNT(*) AS n FROM reclamaciones_proveedor r WHERE {where}",
                      tuple(params), uno=True)["n"]
    filas = consultar(f"{SQL_RECLAMACION} WHERE {where} ORDER BY r.fecha_creacion DESC, r.id DESC "
                      "LIMIT %s OFFSET %s", tuple(params) + (pag.limite, pag.desplazamiento))
    for f in filas:
        f.pop("descripcion")
    return responder(paginar(filas, total, pag), raiz="reclamaciones")


@api.get("/reclamaciones/<int:rid>")
@requiere_jwt(*LECTORES)
def detalle_reclamacion(rid):
    fila = consultar(SQL_RECLAMACION + " WHERE r.id = %s", (rid,), uno=True)
    if not fila:
        raise ErrorApi(404, "no_encontrado", "Reclamacion inexistente.")
    fila["devoluciones"] = consultar("""
        SELECT d.id, d.folio_devolucion, d.estado, d.cantidad_devuelta
          FROM reclamacion_devoluciones rd JOIN devoluciones d ON d.id = rd.devolucion_id
         WHERE rd.reclamacion_id = %s ORDER BY d.id""", (rid,))
    fila["seguimiento"] = consultar("""
        SELECT s.estado_anterior, s.estado_nuevo, s.comentario, s.fecha, u.nombre AS usuario
          FROM seguimiento_reclamacion s JOIN usuarios u ON u.id = s.usuario_id
         WHERE s.reclamacion_id = %s ORDER BY s.fecha, s.id""", (rid,))
    return responder(fila, raiz="reclamacion")


@api.post("/reclamaciones/<int:rid>/seguimiento")
@requiere_jwt(*ESCRITORES)
def seguimiento(rid):
    datos = leer_cuerpo(xsd=os.path.join(CONTRATOS, "seguimiento.xsd"))
    # FOR UPDATE: dos cambios simultaneos de estado no pueden pisarse.
    actual = consultar("SELECT * FROM reclamaciones_proveedor WHERE id=%s FOR UPDATE", (rid,), uno=True)
    if not actual:
        raise ErrorApi(404, "no_encontrado", "Reclamacion inexistente.")
    nuevo, comentario, resolucion, recuperado = reglas.validar_seguimiento(datos, actual)
    cierra = nuevo == "cerrada"
    ejecutar("""UPDATE reclamaciones_proveedor
                   SET estado=%s, resolucion=%s, monto_recuperado=COALESCE(%s, monto_recuperado),
                       fecha_cierre=CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
                 WHERE id=%s""", (nuevo, resolucion, recuperado, cierra, rid))
    ejecutar("""INSERT INTO seguimiento_reclamacion (reclamacion_id, estado_anterior, estado_nuevo,
                    comentario, usuario_id) VALUES (%s,%s,%s,%s,%s)""",
             (rid, actual["estado"], nuevo, comentario, g.usuario["id"]))
    registrar_bitacora("seguimiento_reclamacion", "reclamaciones_proveedor", rid,
                       f"{actual['folio']}: {actual['estado']} -> {nuevo}")
    return responder({"id": rid, "folio": actual["folio"], "estado": nuevo,
                      "resolucion": resolucion,
                      "monto_recuperado": recuperado if cierra else actual["monto_recuperado"]},
                     raiz="reclamacion")


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    respuestas.registrar(app, NOMBRE)
    app.teardown_appcontext(cerrar_conexion)
    app.register_blueprint(api)
    docs.registrar(app, os.path.join(os.path.dirname(__file__), "openapi.yaml"))

    @app.get("/health")
    def health():
        deps = {"postgresql": salud_postgres(), "redis": salud_redis()}
        ok = all(x["ok"] for x in deps.values())
        return responder({"servicio": NOMBRE, "version": "v1",
                          "estado": "ok" if ok else "degradado", "dependencias": deps},
                         200 if ok else 503)
    return app
