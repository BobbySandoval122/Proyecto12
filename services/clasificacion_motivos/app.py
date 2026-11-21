"""Clasificacion de motivos (dominio 10 del tercer parcial).

Motivos y submotivos agrupados por origen de la falla (producto, empaque,
transporte, error comercial, mal uso), con versiones y revision humana:

- Cada cambio de un submotivo crea una version nueva; las anteriores se
  conservan, asi se sabe con que criterio se clasifico un caso.
- La sugerencia por palabras clave es SOLO una propuesta. Queda pendiente hasta
  que una persona la confirme, corrija o descarte, y este servicio nunca
  modifica la devolucion (RN-11). Quien contradice la sugerencia explica por que.
- Los clientes pueden pedir una sugerencia de texto para llenar su solicitud,
  pero no leen el catalogo interno ni sus palabras clave.

Trazabilidad: RF-22, RF-30, RN-09, RN-11, RN-12, RNF-09, RNF-11.
"""
import json
import os

from flask import Blueprint, Flask, g, request

import reglas
from shared import docs, respuestas
from shared.infra import (cerrar_conexion, consultar, ejecutar, limitar,
                          registrar_bitacora, salud_postgres, salud_redis)
from shared.paginacion import leer_paginacion, paginar
from shared.respuestas import ErrorApi, leer_cuerpo, responder
from shared.seguridad import (ADMINISTRADOR, ANALISTA, COORDINADOR, ENCARGADO_CENTRO,
                              INSPECTOR, OPERADOR_ALMACEN, SUPERVISOR, requiere_jwt)

NOMBRE = "clasificacion-motivos"
CONTRATOS = os.path.join(os.path.dirname(__file__), "contratos")
api = Blueprint("motivos", __name__, url_prefix="/api/v1/motivos")

LECTORES = (ADMINISTRADOR, ANALISTA, SUPERVISOR, INSPECTOR, ENCARGADO_CENTRO,
            COORDINADOR, OPERADOR_ALMACEN)
EDITORES = (ADMINISTRADOR, SUPERVISOR)
REVISORES = (ANALISTA, SUPERVISOR, ADMINISTRADOR)

SQL_SUBMOTIVO = """
SELECT s.id, s.codigo, s.nombre, s.descripcion, s.palabras_clave, s.version, s.activo,
       s.motivo_id, m.nombre AS motivo, c.id AS categoria_id, c.codigo AS categoria_codigo,
       c.nombre AS categoria
  FROM submotivos s JOIN categorias_motivo c ON c.id = s.categoria_id
  LEFT JOIN motivos m ON m.id = s.motivo_id
"""

SQL_CLASIFICACION = """
SELECT cm.id, cm.devolucion_id, d.folio_devolucion, cm.estado, cm.puntaje, cm.coincidencias,
       cm.submotivo_sugerido_id, ss.nombre AS submotivo_sugerido, cm.version_sugerida,
       cm.submotivo_final_id, sf.nombre AS submotivo_final, cm.version_final,
       sf.motivo_id AS motivo_id_final, cm.comentario, cm.fecha_creacion,
       cm.fecha_revision, ur.nombre AS revisado_por
  FROM clasificaciones_motivo cm
  JOIN devoluciones d ON d.id = cm.devolucion_id
  LEFT JOIN submotivos ss ON ss.id = cm.submotivo_sugerido_id
  LEFT JOIN submotivos sf ON sf.id = cm.submotivo_final_id
  LEFT JOIN usuarios ur ON ur.id = cm.revisado_por
"""


def _submotivos_activos():
    return consultar(SQL_SUBMOTIVO + " WHERE s.activo")


def _exigir_referencias(limpio):
    if not consultar("SELECT 1 FROM categorias_motivo WHERE id=%s", (limpio["categoria_id"],), uno=True):
        raise ErrorApi(409, "referencia_invalida", "La categoria no existe.")
    if limpio["motivo_id"] is not None and not consultar(
            "SELECT 1 FROM motivos WHERE id=%s AND activo=TRUE", (limpio["motivo_id"],), uno=True):
        raise ErrorApi(409, "referencia_invalida", "El motivo no existe o esta inactivo.")


def _guardar_version(sid, version, fila, motivo_cambio):
    ejecutar("""INSERT INTO submotivos_versiones (submotivo_id, version, nombre, descripcion,
                    palabras_clave, motivo_id, activo, cambiado_por, motivo_cambio)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (sid, version, fila["nombre"], fila["descripcion"], fila["palabras_clave"],
              fila["motivo_id"], fila["activo"], g.usuario["id"], motivo_cambio))


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #
@api.get("/categorias")
@requiere_jwt(*LECTORES)
def categorias():
    filas = consultar("""
        SELECT c.id, c.codigo, c.nombre, c.descripcion,
               COUNT(s.id) FILTER (WHERE s.activo) AS submotivos_activos
          FROM categorias_motivo c LEFT JOIN submotivos s ON s.categoria_id = c.id
         GROUP BY c.id ORDER BY c.id""")
    return responder({"datos": filas, "total": len(filas)}, raiz="categorias")


@api.get("/submotivos")
@requiere_jwt(*LECTORES)
def listado():
    pag = leer_paginacion()
    condiciones, params = ["TRUE"], []
    if request.args.get("solo_activos", "true").lower() == "true":
        condiciones.append("s.activo")
    categoria = request.args.get("categoria_id")
    if categoria:
        condiciones.append("s.categoria_id = %s")
        params.append(reglas.entero_positivo(categoria, "categoria_id"))
    where = " AND ".join(condiciones)
    total = consultar(f"SELECT COUNT(*) AS n FROM submotivos s WHERE {where}",
                      tuple(params), uno=True)["n"]
    filas = consultar(f"{SQL_SUBMOTIVO} WHERE {where} ORDER BY c.id, s.id LIMIT %s OFFSET %s",
                      tuple(params) + (pag.limite, pag.desplazamiento))
    return responder(paginar(filas, total, pag), raiz="submotivos")


@api.get("/submotivos/<int:sid>")
@requiere_jwt(*LECTORES)
def detalle(sid):
    fila = consultar(SQL_SUBMOTIVO + " WHERE s.id = %s", (sid,), uno=True)
    if not fila:
        raise ErrorApi(404, "no_encontrado", "Submotivo inexistente.")
    fila["versiones"] = consultar("""
        SELECT sv.version, sv.nombre, sv.descripcion, sv.palabras_clave, sv.activo,
               sv.motivo_cambio, sv.fecha, u.nombre AS cambiado_por
          FROM submotivos_versiones sv LEFT JOIN usuarios u ON u.id = sv.cambiado_por
         WHERE sv.submotivo_id = %s ORDER BY sv.version DESC""", (sid,))
    return responder(fila, raiz="submotivo")


@api.post("/submotivos")
@requiere_jwt(*EDITORES)
def crear():
    limpio = reglas.validar_submotivo(
        leer_cuerpo(xsd=os.path.join(CONTRATOS, "submotivo.xsd")), alta=True)
    _exigir_referencias(limpio)
    if consultar("SELECT 1 FROM submotivos WHERE codigo=%s", (limpio["codigo"],), uno=True):
        raise ErrorApi(409, "codigo_duplicado", "Ya existe un submotivo con ese codigo.")
    fila = ejecutar("""INSERT INTO submotivos (categoria_id, motivo_id, codigo, nombre, descripcion,
                           palabras_clave) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (limpio["categoria_id"], limpio["motivo_id"], limpio["codigo"], limpio["nombre"],
                     limpio["descripcion"], limpio["palabras_clave"]), devolver=True)
    _guardar_version(fila["id"], 1, {**limpio, "activo": True}, "Alta del submotivo")
    registrar_bitacora("alta_submotivo", "submotivos", fila["id"], f"Submotivo {limpio['codigo']}")
    return responder({"id": fila["id"], "version": 1}, 201, "submotivo",
                     {"Location": f"/api/v1/motivos/submotivos/{fila['id']}"})


@api.put("/submotivos/<int:sid>")
@requiere_jwt(*EDITORES)
def editar(sid):
    limpio = reglas.validar_submotivo(
        leer_cuerpo(xsd=os.path.join(CONTRATOS, "submotivo.xsd")), alta=False)
    _exigir_referencias(limpio)
    # FOR UPDATE: dos ediciones simultaneas no pueden crear la misma version.
    actual = consultar("SELECT * FROM submotivos WHERE id=%s FOR UPDATE", (sid,), uno=True)
    if not actual:
        raise ErrorApi(404, "no_encontrado", "Submotivo inexistente.")
    if all(limpio[c] == actual[c] for c in
           ("categoria_id", "motivo_id", "nombre", "descripcion", "palabras_clave")):
        return responder({"id": sid, "version": actual["version"], "sin_cambios": True},
                         raiz="submotivo")
    version = actual["version"] + 1
    ejecutar("""UPDATE submotivos SET categoria_id=%s, motivo_id=%s, nombre=%s, descripcion=%s,
                    palabras_clave=%s, version=%s WHERE id=%s""",
             (limpio["categoria_id"], limpio["motivo_id"], limpio["nombre"], limpio["descripcion"],
              limpio["palabras_clave"], version, sid))
    _guardar_version(sid, version, {**limpio, "activo": actual["activo"]}, limpio["motivo_cambio"])
    registrar_bitacora("edicion_submotivo", "submotivos", sid, f"Version {version}")
    return responder({"id": sid, "version": version}, raiz="submotivo")


@api.patch("/submotivos/<int:sid>/estado")
@requiere_jwt(*EDITORES)
def estado(sid):
    activo, motivo = reglas.validar_activo(
        leer_cuerpo(xsd=os.path.join(CONTRATOS, "estado.xsd")))
    actual = consultar("SELECT * FROM submotivos WHERE id=%s FOR UPDATE", (sid,), uno=True)
    if not actual:
        raise ErrorApi(404, "no_encontrado", "Submotivo inexistente.")
    if actual["activo"] == activo:
        return responder({"id": sid, "version": actual["version"], "sin_cambios": True},
                         raiz="submotivo")
    version = actual["version"] + 1
    ejecutar("UPDATE submotivos SET activo=%s, version=%s WHERE id=%s", (activo, version, sid))
    _guardar_version(sid, version, {**actual, "activo": activo}, motivo)
    registrar_bitacora("submotivo_activado" if activo else "submotivo_desactivado",
                       "submotivos", sid, f"Version {version}")
    return responder({"id": sid, "version": version, "activo": activo}, raiz="submotivo")


# --------------------------------------------------------------------------- #
# Sugerencia y revision humana
# --------------------------------------------------------------------------- #
@api.post("/sugerencias")
@requiere_jwt()
def sugerir_texto():
    """Sugerencia para un texto libre (ej. el formulario del cliente). No guarda nada."""
    limitar("sugerir_motivo", 30, 60, sujeto=str(g.usuario["id"]))
    datos = leer_cuerpo(xsd=os.path.join(CONTRATOS, "sugerencia.xsd"))
    descripcion = reglas.validar_descripcion((datos or {}).get("descripcion"))
    sugerencias = reglas.puntuar(descripcion, _submotivos_activos())
    # Sin palabras clave internas: un cliente no necesita saber como se calcula.
    for s in sugerencias:
        s.pop("coincidencias")
    return responder({"sugerencias": sugerencias, "requiere_confirmacion": True,
                      "explicacion": "La sugerencia orienta; una persona confirma el motivo."},
                     raiz="sugerencias")


@api.post("/clasificaciones")
@requiere_jwt(*REVISORES)
def crear_clasificacion():
    """Propone un submotivo para una devolucion y lo deja pendiente de revision."""
    datos = leer_cuerpo(xsd=os.path.join(CONTRATOS, "clasificacion.xsd"))
    devolucion_id = reglas.entero_positivo((datos or {}).get("devolucion_id"), "devolucion_id")
    dev = consultar("SELECT id, descripcion_problema FROM devoluciones "
                    "WHERE id=%s AND eliminado_en IS NULL", (devolucion_id,), uno=True)
    if not dev:
        raise ErrorApi(404, "no_encontrado", "Devolucion inexistente.")
    if consultar("SELECT 1 FROM clasificaciones_motivo WHERE devolucion_id=%s AND estado='pendiente'",
                 (devolucion_id,), uno=True):
        raise ErrorApi(409, "clasificacion_pendiente",
                       "Esta devolucion ya tiene una sugerencia pendiente de revision.")
    ranking = reglas.puntuar(dev["descripcion_problema"], _submotivos_activos())
    mejor = ranking[0] if ranking else None
    fila = ejecutar("""INSERT INTO clasificaciones_motivo (devolucion_id, submotivo_sugerido_id,
                           version_sugerida, puntaje, coincidencias, creado_por)
                       VALUES (%s,%s,%s,%s,%s::jsonb,%s) RETURNING id""",
                    (devolucion_id, mejor["submotivo_id"] if mejor else None,
                     mejor["version"] if mejor else None, mejor["puntaje"] if mejor else 0,
                     json.dumps(mejor["coincidencias"] if mejor else []), g.usuario["id"]),
                    devolver=True)
    registrar_bitacora("sugerencia_motivo", "devoluciones", devolucion_id,
                       f"Clasificacion {fila['id']} pendiente de revision")
    return responder({"id": fila["id"], "estado": "pendiente", "sugerencias": ranking,
                      "requiere_revision_humana": True,
                      "aviso": "No se modifico la devolucion (RN-11)."},
                     201, "clasificacion")


@api.get("/clasificaciones")
@requiere_jwt(*REVISORES)
def clasificaciones():
    pag = leer_paginacion()
    condiciones, params = ["TRUE"], []
    estado_ = request.args.get("estado")
    if estado_:
        if estado_ not in ("pendiente", "confirmada", "corregida", "descartada"):
            raise ErrorApi(400, "validacion", "estado desconocido.")
        condiciones.append("cm.estado = %s")
        params.append(estado_)
    if request.args.get("devolucion_id"):
        condiciones.append("cm.devolucion_id = %s")
        params.append(reglas.entero_positivo(request.args["devolucion_id"], "devolucion_id"))
    where = " AND ".join(condiciones)
    total = consultar(f"SELECT COUNT(*) AS n FROM clasificaciones_motivo cm WHERE {where}",
                      tuple(params), uno=True)["n"]
    filas = consultar(f"{SQL_CLASIFICACION} WHERE {where} "
                      "ORDER BY cm.fecha_creacion DESC, cm.id DESC LIMIT %s OFFSET %s",
                      tuple(params) + (pag.limite, pag.desplazamiento))
    return responder(paginar(filas, total, pag), raiz="clasificaciones")


@api.post("/clasificaciones/<int:cid>/revision")
@requiere_jwt(*REVISORES)
def revisar(cid):
    decision, submotivo_id, comentario = reglas.validar_revision(
        leer_cuerpo(xsd=os.path.join(CONTRATOS, "revision.xsd")))
    # FOR UPDATE: dos revisores no pueden resolver la misma sugerencia a la vez.
    fila = consultar("SELECT * FROM clasificaciones_motivo WHERE id=%s FOR UPDATE", (cid,), uno=True)
    if not fila:
        raise ErrorApi(404, "no_encontrado", "Clasificacion inexistente.")
    if fila["estado"] != "pendiente":
        raise ErrorApi(409, "ya_revisada", f"La clasificacion ya fue {fila['estado']}.")

    final_id = None
    if decision == "confirmar":
        if fila["submotivo_sugerido_id"] is None:
            raise ErrorApi(400, "sin_sugerencia",
                           "No hay sugerencia que confirmar; usa decision corregir.")
        final_id, nuevo_estado = fila["submotivo_sugerido_id"], "confirmada"
    elif decision == "corregir":
        final_id, nuevo_estado = submotivo_id, "corregida"
    else:
        nuevo_estado = "descartada"
    version_final = None
    if final_id is not None:
        elegido = consultar("SELECT version, activo FROM submotivos WHERE id=%s", (final_id,), uno=True)
        if not elegido or not elegido["activo"]:
            raise ErrorApi(409, "referencia_invalida", "El submotivo no existe o esta inactivo.")
        version_final = elegido["version"]
    ejecutar("""UPDATE clasificaciones_motivo
                   SET estado=%s, submotivo_final_id=%s, version_final=%s, comentario=%s,
                       revisado_por=%s, fecha_revision=CURRENT_TIMESTAMP
                 WHERE id=%s""",
             (nuevo_estado, final_id, version_final, comentario, g.usuario["id"], cid))
    registrar_bitacora("revision_motivo", "devoluciones", fila["devolucion_id"],
                       f"Clasificacion {cid}: {nuevo_estado}")
    resultado = consultar(SQL_CLASIFICACION + " WHERE cm.id = %s", (cid,), uno=True)
    resultado["aplicado_a_devolucion"] = False
    resultado["aviso"] = ("La revision no modifica la devolucion; "
                          "cambiar su motivo es una accion aparte (RN-11).")
    return responder(resultado, raiz="clasificacion")


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
