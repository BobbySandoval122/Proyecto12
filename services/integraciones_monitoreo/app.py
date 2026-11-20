"""Microservicio de integraciones y monitoreo (dominios 21 y 22, puerto 8021).

Integraciones (/api/v1/integraciones), con JSON o XML validado por XSD:
- Importa ventas del POS sin duplicarlas: el ticket del POS queda conciliado
  con la venta interna en integraciones_ids (migracion 018).
- Exporta devoluciones con reembolso y costo para ERP y sistemas financieros.
- Recibe el avance de una recoleccion desde el transportista.
- Administra la conciliacion de identificadores externos e internos.

Monitoreo (/api/v1/monitoreo):
- Salud de cada servicio, de PostgreSQL, Redis y MongoDB, y de la cola de
  sincronizacion; tiempos de respuesta, disponibilidad y alertas operativas.
- Traza distribuida: todo lo que paso con un X-Correlation-ID.

Trazabilidad: RF-05, RF-06, RF-13, RF-27, RF-30, RF-32, RN-12, RNF-11, RNF-22,
RNF-23, RNF-28.
"""
import os
import re
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, Flask, g, request

import monitor
import reglas
from shared import docs, mongo, respuestas
from shared.infra import (cerrar_conexion, consultar, ejecutar, registrar_bitacora,
                          salud_postgres, salud_redis)
from shared.paginacion import leer_paginacion, paginar
from shared.respuestas import ErrorApi, leer_cuerpo, responder
from shared.seguridad import (ADMINISTRADOR, ANALISTA, CLIENTE, COORDINADOR,
                              ENCARGADO_REEMBOLSOS, SUPERVISOR, requiere_jwt)

NOMBRE = "integraciones-monitoreo"
CONTRATOS = os.path.join(os.path.dirname(__file__), "contratos")
integraciones = Blueprint("integraciones", __name__, url_prefix="/api/v1/integraciones")
monitoreo = Blueprint("monitoreo", __name__, url_prefix="/api/v1/monitoreo")

MONITOREAN = (ADMINISTRADOR, SUPERVISOR)
EXPORTAN = (ADMINISTRADOR, ENCARGADO_REEMBOLSOS, ANALISTA)
CORRELATION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# --------------------------------------------------------------------------- #
# Conciliacion de identificadores
# --------------------------------------------------------------------------- #
def _sistema(valor):
    sistema = str(valor or "").strip().lower()
    if sistema not in reglas.SISTEMAS:
        raise ErrorApi(400, "validacion", f"sistema debe ser uno de {', '.join(reglas.SISTEMAS)}.")
    return sistema


def _tipo_entidad(valor):
    tipo = str(valor or "").strip().lower()
    if tipo not in reglas.TABLA_POR_TIPO:
        raise ErrorApi(400, "validacion",
                       f"tipo_entidad debe ser uno de {', '.join(reglas.TABLA_POR_TIPO)}.")
    return tipo


def _id_externo(valor, campo="id_externo"):
    texto = reglas.id_externo_valido(valor)
    if not texto:
        raise ErrorApi(400, "validacion", f"{campo}: 1 a 64 letras, numeros o _ . : / -")
    return texto


def _interno(sistema, tipo, id_externo):
    fila = consultar("""SELECT id_interno FROM integraciones_ids
                         WHERE sistema = %s AND tipo_entidad = %s AND id_externo = %s""",
                     (sistema, tipo, id_externo), uno=True)
    return fila["id_interno"] if fila else None


def _sin_conciliar(sistema, tipo, id_externo):
    return ErrorApi(422, "sin_conciliar",
                    f"El {tipo} '{id_externo}' de {sistema} no tiene equivalente interno. "
                    "Registralo en POST /api/v1/integraciones/conciliaciones.",
                    {"sistema": sistema, "tipo_entidad": tipo, "id_externo": id_externo})


@integraciones.post("/conciliaciones")
@requiere_jwt(ADMINISTRADOR)
def conciliar():
    """Registra que un id externo equivale a un registro interno."""
    datos = leer_cuerpo(os.path.join(CONTRATOS, "conciliacion.xsd"))
    sistema, tipo = _sistema(datos.get("sistema")), _tipo_entidad(datos.get("tipo_entidad"))
    id_externo = _id_externo(datos.get("id_externo"))
    try:
        id_interno = int(datos.get("id_interno"))
        if id_interno < 1 or isinstance(datos.get("id_interno"), bool):
            raise ValueError
    except (TypeError, ValueError):
        raise ErrorApi(400, "validacion", "id_interno debe ser entero positivo.")
    tabla = reglas.TABLA_POR_TIPO[tipo]
    if not consultar(f"SELECT id FROM {tabla} WHERE id = %s", (id_interno,), uno=True):
        raise ErrorApi(404, "no_encontrado", f"No existe {tipo} {id_interno}.")
    ejecutar("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{sistema}:{tipo}:{id_externo}",))
    actual = _interno(sistema, tipo, id_externo)
    cuerpo = {"sistema": sistema, "tipo_entidad": tipo, "id_externo": id_externo, "id_interno": id_interno}
    if actual == id_interno:
        return responder(dict(cuerpo, repetida=True), 200, "conciliacion")
    if actual is not None:
        raise ErrorApi(409, "conciliacion_distinta", "Ese id externo ya apunta a otro registro.",
                       {"id_interno_actual": actual})
    otro = consultar("""SELECT id_externo FROM integraciones_ids
                         WHERE sistema = %s AND tipo_entidad = %s AND id_interno = %s""",
                     (sistema, tipo, id_interno), uno=True)
    if otro:
        raise ErrorApi(409, "conciliacion_distinta", "Ese registro ya tiene otro id externo en ese sistema.",
                       {"id_externo_actual": otro["id_externo"]})
    ejecutar("""INSERT INTO integraciones_ids (sistema, tipo_entidad, id_externo, id_interno, creado_por)
                VALUES (%s, %s, %s, %s, %s)""", (sistema, tipo, id_externo, id_interno, g.usuario["id"]))
    registrar_bitacora("conciliacion_registrada", tabla, id_interno, f"{sistema}:{id_externo}")
    return responder(dict(cuerpo, repetida=False), 201, "conciliacion")


@integraciones.get("/conciliaciones")
@requiere_jwt(ADMINISTRADOR)
def listar_conciliaciones():
    condiciones, params = [], []
    if request.args.get("sistema"):
        condiciones.append("sistema = %s"); params.append(_sistema(request.args["sistema"]))
    if request.args.get("tipo_entidad"):
        condiciones.append("tipo_entidad = %s"); params.append(_tipo_entidad(request.args["tipo_entidad"]))
    where = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""
    pag = leer_paginacion()
    filas = consultar(f"""SELECT sistema, tipo_entidad, id_externo, id_interno, creado_en
                            FROM integraciones_ids{where}
                           ORDER BY creado_en DESC LIMIT %s OFFSET %s""",
                      (*params, pag.limite, pag.desplazamiento))
    total = consultar(f"SELECT count(*) AS n FROM integraciones_ids{where}", tuple(params), uno=True)["n"]
    return responder(paginar(filas, total, pag), 200, "conciliaciones")


@integraciones.get("/conciliaciones/<sistema>/<tipo_entidad>/<path:id_externo>")
@requiere_jwt(ADMINISTRADOR, *EXPORTAN)
def resolver_conciliacion(sistema, tipo_entidad, id_externo):
    sistema, tipo = _sistema(sistema), _tipo_entidad(tipo_entidad)
    id_externo = _id_externo(id_externo)
    interno = _interno(sistema, tipo, id_externo)
    if interno is None:
        raise _sin_conciliar(sistema, tipo, id_externo)
    return responder({"sistema": sistema, "tipo_entidad": tipo, "id_externo": id_externo,
                      "id_interno": interno}, 200, "conciliacion")


# --------------------------------------------------------------------------- #
# POS: importacion de ventas
# --------------------------------------------------------------------------- #
@integraciones.post("/ventas")
@requiere_jwt(ADMINISTRADOR)
def importar_venta():
    """Venta del POS. Idempotente: el mismo ticket dos veces es la misma venta."""
    datos = leer_cuerpo(os.path.join(CONTRATOS, "venta_pos.xsd"))
    problemas = reglas.problemas_de_venta(datos, date.today())
    if problemas:
        raise ErrorApi(400, "validacion", "La venta del POS no es valida.", problemas)
    id_externo = datos["id_externo"].strip()
    # Dos envios simultaneos del mismo ticket: el segundo espera aqui.
    ejecutar("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"pos:venta:{id_externo}",))
    existente = _interno("pos", "venta", id_externo)
    if existente is not None:
        venta = consultar("SELECT id, folio_venta FROM ventas WHERE id = %s", (existente,), uno=True)
        return responder({"venta_id": venta["id"], "folio_venta": venta["folio_venta"],
                          "id_externo": id_externo, "repetida": True}, 200, "venta")
    tienda_externa = datos["tienda_externa"].strip()
    tienda_id = _interno("pos", "tienda", tienda_externa)
    if tienda_id is None:
        raise _sin_conciliar("pos", "tienda", tienda_externa)
    cliente = consultar("""SELECT u.id FROM usuarios u JOIN roles r ON r.id = u.rol_id
                            WHERE lower(u.email) = lower(%s) AND r.nombre = %s
                              AND u.estado = 'activo' AND u.eliminado_en IS NULL""",
                        (str(datos["cliente_email"]).strip(), CLIENTE), uno=True)
    if not cliente:
        raise ErrorApi(422, "cliente_desconocido", "No hay un cliente activo con ese correo.")
    lineas, faltan = [], []
    for linea in datos["lineas"]:
        lote = consultar("""SELECT l.id FROM lotes l JOIN productos p ON p.id = l.producto_id
                             WHERE p.sku = %s AND l.numero_lote = %s AND l.activo AND p.activo""",
                         (str(linea["sku"]).strip(), str(linea["numero_lote"]).strip()), uno=True)
        if not lote:
            faltan.append({"sku": linea["sku"], "numero_lote": linea["numero_lote"]})
        else:
            lineas.append((lote["id"], int(linea["cantidad"]), round(float(linea["precio_unitario"]), 2)))
    if faltan:
        raise ErrorApi(422, "lote_desconocido", "Hay productos o lotes que no existen en el catalogo.", faltan)
    folio = reglas.folio_de_pos(id_externo)
    if consultar("SELECT id FROM ventas WHERE folio_venta = %s", (folio,), uno=True):
        raise ErrorApi(409, "folio_ocupado", f"Ya existe una venta con folio {folio} sin conciliar.")
    venta = ejecutar("""INSERT INTO ventas (folio_venta, cliente_id, tienda_id, fecha_venta)
                        VALUES (%s, %s, %s, %s) RETURNING id, folio_venta""",
                     (folio, cliente["id"], tienda_id, datos["fecha_venta"]), devolver=True)
    for lote_id, cantidad, precio in lineas:
        ejecutar("""INSERT INTO venta_detalle (venta_id, lote_id, cantidad, precio_unitario)
                    VALUES (%s, %s, %s, %s)""", (venta["id"], lote_id, cantidad, precio))
    ejecutar("""INSERT INTO integraciones_ids (sistema, tipo_entidad, id_externo, id_interno, creado_por)
                VALUES ('pos', 'venta', %s, %s, %s)""", (id_externo, venta["id"], g.usuario["id"]))
    registrar_bitacora("venta_importada", "ventas", venta["id"], f"POS {id_externo}, {len(lineas)} lineas")
    mongo.registrar_evento(NOMBRE, "venta_importada", {"venta_id": venta["id"], "id_externo": id_externo})
    return responder({"venta_id": venta["id"], "folio_venta": venta["folio_venta"],
                      "id_externo": id_externo, "lineas": len(lineas), "repetida": False}, 201, "venta",
                     {"Location": f"/api/v1/integraciones/conciliaciones/pos/venta/{id_externo}"})


# --------------------------------------------------------------------------- #
# ERP y sistemas financieros: exportacion de devoluciones
# --------------------------------------------------------------------------- #
def _fecha_param(nombre, defecto):
    texto = request.args.get(nombre)
    if not texto:
        return defecto
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise ErrorApi(400, "validacion", f"{nombre} debe usar AAAA-MM-DD.")


@integraciones.get("/exportaciones/devoluciones")
@requiere_jwt(*EXPORTAN)
def exportar_devoluciones():
    """Devoluciones con reembolso y costo total, con los ids del POS y del ERP
    para que el otro sistema concilie. JSON o XML segun Accept."""
    hoy = date.today()
    desde = _fecha_param("desde", hoy - timedelta(days=30))
    hasta = _fecha_param("hasta", hoy)
    if desde > hasta or (hasta - desde).days > 366:
        raise ErrorApi(400, "validacion", "Rango invalido: desde <= hasta y maximo 366 dias.")
    pag = leer_paginacion(50)
    where = """WHERE d.eliminado_en IS NULL
                 AND d.fecha_solicitud >= %s AND d.fecha_solicitud < %s + interval '1 day'"""
    filas = consultar(f"""
        SELECT d.id AS devolucion_id, d.folio_devolucion, d.estado, d.fecha_solicitud,
               d.cantidad_devuelta, v.folio_venta, v.fecha_venta, t.nombre AS tienda,
               p.sku, l.numero_lote, vd.precio_unitario,
               r.monto AS monto_reembolso, r.estado AS estado_reembolso,
               (SELECT COALESCE(SUM(c.monto), 0) FROM costos c WHERE c.devolucion_id = d.id) AS costo_total,
               pos.id_externo AS venta_id_pos, erp.id_externo AS devolucion_id_erp
          FROM devoluciones d
          JOIN venta_detalle vd ON vd.id = d.venta_detalle_id
          JOIN ventas v ON v.id = vd.venta_id
          JOIN tiendas t ON t.id = v.tienda_id
          JOIN lotes l ON l.id = vd.lote_id
          JOIN productos p ON p.id = l.producto_id
          LEFT JOIN reembolsos r ON r.devolucion_id = d.id
          LEFT JOIN integraciones_ids pos
                 ON pos.sistema = 'pos' AND pos.tipo_entidad = 'venta' AND pos.id_interno = v.id
          LEFT JOIN integraciones_ids erp
                 ON erp.sistema = 'erp' AND erp.tipo_entidad = 'devolucion' AND erp.id_interno = d.id
          {where}
         ORDER BY d.id LIMIT %s OFFSET %s""", (desde, hasta, pag.limite, pag.desplazamiento))
    total = consultar(f"SELECT count(*) AS n FROM devoluciones d {where}", (desde, hasta), uno=True)["n"]
    registrar_bitacora("exportacion_devoluciones", "devoluciones", None,
                       f"{desde} a {hasta}, pagina {pag.pagina}, {len(filas)} filas")
    cuerpo = paginar(filas, total, pag)
    cuerpo["periodo"] = {"desde": desde, "hasta": hasta}
    return responder(cuerpo, 200, "exportacion")


# --------------------------------------------------------------------------- #
# Transportistas: avance de la recoleccion
# --------------------------------------------------------------------------- #
@integraciones.post("/transportistas/eventos")
@requiere_jwt(ADMINISTRADOR, COORDINADOR)
def evento_transportista():
    """El transportista reporta el avance con SU numero de guia. Si el estado ya
    es el reportado, responde sin cambios: reenviar el evento no duplica nada."""
    datos = leer_cuerpo(os.path.join(CONTRATOS, "evento_transportista.xsd"))
    guia = _id_externo(datos.get("guia"), "guia")
    nuevo = str(datos.get("estado") or "").strip()
    if nuevo not in ("en_transito", "completada", "fallida"):
        raise ErrorApi(400, "validacion", "estado debe ser en_transito, completada o fallida.")
    recoleccion_id = _interno("transportista", "recoleccion", guia)
    if recoleccion_id is None:
        raise _sin_conciliar("transportista", "recoleccion", guia)
    fila = consultar("SELECT id, devolucion_id, estado FROM recolecciones WHERE id = %s FOR UPDATE",
                     (recoleccion_id,), uno=True)
    if fila["estado"] == nuevo:
        return responder({"recoleccion_id": recoleccion_id, "estado": nuevo, "cambio": False}, 200, "evento")
    if nuevo not in reglas.TRANSICIONES_TRANSPORTISTA.get(fila["estado"], ()):
        raise ErrorApi(409, "transicion_invalida", f"No se puede pasar de {fila['estado']} a {nuevo}.",
                       {"estado_actual": fila["estado"]})
    ejecutar("UPDATE recolecciones SET estado = %s WHERE id = %s", (nuevo, recoleccion_id))
    registrar_bitacora("estado_recoleccion", "devoluciones", fila["devolucion_id"],
                       f"Estado logistico: {nuevo} (transportista, guia {guia})")
    return responder({"recoleccion_id": recoleccion_id, "estado_anterior": fila["estado"],
                      "estado": nuevo, "cambio": True}, 200, "evento")


# --------------------------------------------------------------------------- #
# Monitoreo
# --------------------------------------------------------------------------- #
@monitoreo.get("/estado")
@requiere_jwt(*MONITOREAN)
def estado():
    """Revisa todo en este momento y actualiza las alertas."""
    return responder(monitor.chequear(), 200, "monitoreo")


def _horas():
    try:
        horas = int(request.args.get("horas", 24))
    except ValueError:
        horas = 0
    if not 1 <= horas <= 24 * monitor.DIAS_HISTORIAL:
        raise ErrorApi(400, "validacion", f"horas debe estar entre 1 y {24 * monitor.DIAS_HISTORIAL}.")
    return horas


@monitoreo.get("/disponibilidad")
@requiere_jwt(*MONITOREAN)
def disponibilidad():
    """Disponibilidad, tiempos (promedio y p95) y fallas por servicio."""
    horas = _horas()
    desde = datetime.now(timezone.utc) - timedelta(hours=horas)
    chequeos = list(mongo.get_mongo().monitoreo_chequeos.find(
        {"fecha": {"$gte": desde}}, {"servicios": 1, "_id": 0}))
    return responder({"horas": horas, "chequeos": len(chequeos),
                      "servicios": reglas.disponibilidad(chequeos)}, 200, "disponibilidad")


@monitoreo.get("/alertas")
@requiere_jwt(*MONITOREAN)
def alertas():
    filtro = {}
    estado_alerta = (request.args.get("estado") or "").strip()
    if estado_alerta:
        if estado_alerta not in ("activa", "resuelta"):
            raise ErrorApi(400, "validacion", "estado debe ser activa o resuelta.")
        filtro["estado"] = estado_alerta
    pag = leer_paginacion()
    coleccion = mongo.get_mongo().alertas_operativas
    docs_ = coleccion.find(filtro).sort("ultima_vez", -1).skip(pag.desplazamiento).limit(pag.limite)
    return responder(paginar(mongo.a_json(list(docs_)), coleccion.count_documents(filtro), pag),
                     200, "alertas")


def _instante(valor):
    """Fecha comparable venga de PostgreSQL (datetime) o de MongoDB (texto)."""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if not isinstance(valor, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


@monitoreo.get("/traza/<correlation_id>")
@requiere_jwt(*MONITOREAN)
def traza(correlation_id):
    """Trazabilidad distribuida: bitacora (PostgreSQL) y eventos (MongoDB) de
    todos los servicios que compartieron el mismo X-Correlation-ID."""
    if not CORRELATION.fullmatch(correlation_id):
        raise ErrorApi(400, "validacion", "correlation_id invalido.")
    bitacora = consultar("""SELECT b.fecha, b.accion, b.entidad, b.entidad_id, b.detalle,
                                   b.usuario_id, b.ip_origen
                              FROM bitacora b WHERE b.correlation_id = %s ORDER BY b.fecha, b.id""",
                         (correlation_id,))
    eventos = mongo.a_json(list(mongo.get_mongo().eventos.find(
        {"correlation_id": correlation_id}, {"_id": 0}).sort("fecha", 1)))
    pasos = [{"fecha": f["fecha"], "origen": "bitacora", "accion": f["accion"],
              "detalle": f"{f['entidad']} {f['entidad_id'] or ''}: {f['detalle'] or ''}".strip(),
              "usuario_id": f["usuario_id"]} for f in bitacora]
    pasos += [{"fecha": e.get("fecha"), "origen": f"evento {e.get('servicio')}", "accion": e.get("tipo"),
               "detalle": e.get("datos"), "usuario_id": e.get("usuario_id")} for e in eventos]
    pasos.sort(key=lambda p: _instante(p["fecha"]))
    if not pasos:
        raise ErrorApi(404, "no_encontrado", "No hay registros con ese correlation_id.")
    return responder({"correlation_id": correlation_id, "pasos": pasos,
                      "servicios": sorted({p["origen"] for p in pasos})}, 200, "traza")


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    respuestas.registrar(app, NOMBRE)
    app.teardown_appcontext(cerrar_conexion)
    app.register_blueprint(integraciones)
    app.register_blueprint(monitoreo)
    docs.registrar(app, os.path.join(os.path.dirname(__file__), "openapi.yaml"))

    @app.get("/health")
    def health():
        deps = {"postgresql": salud_postgres(), "redis": salud_redis(), "mongodb": mongo.salud_mongo()}
        ok = all(x["ok"] for x in deps.values())
        return responder({"servicio": NOMBRE, "version": "v1", "estado": "ok" if ok else "degradado",
                          "dependencias": deps}, 200 if ok else 503)

    intervalo = int(os.environ.get("MONITOREO_INTERVALO_SEG") or 0)
    if intervalo > 0:
        monitor.iniciar_en_segundo_plano(intervalo)
    return app
