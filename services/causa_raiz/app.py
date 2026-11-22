"""Causa raiz y acciones correctivas (dominios 11 y 12 del tercer parcial).

Flujo que pidio el profe, cada paso decidido por una persona:

 1. El sistema detecta un patron raro (ej. muchas devoluciones de un lote).
 2. Genera una alerta que PROPONE una investigacion; no la abre sola.
 3. Un analista la abre y junta evidencia.
 4. Escribe hipotesis (5 porques, Ishikawa).
 5. Las verifica con mas informacion.
 6. Marca causa confirmada o inconclusa. Confirmar exige evidencia y una
    hipotesis verificada.
 7. Crea acciones CAPA con responsable y fecha compromiso.
 8. Mide si funciono: tasa de lo vendido antes contra lo vendido despues,
    sin contar las ventas que aun pueden devolverse.
 9. Un supervisor, distinto del analista, la cierra tras reconfirmar su
    contrasena (operacion critica de auth).

Todo cambio queda en una linea de tiempo inmutable y en la bitacora. El
servicio apoya la decision; nunca determina una causa (RN-09, RN-11).

Trazabilidad: RF-23, RF-24, RF-30, RN-09, RN-11, RN-12, RN-13, RNF-09, RNF-11.
"""
import json
import os
from datetime import date

from flask import Blueprint, Flask, g, request

import metricas
import reglas
from shared import docs, respuestas
from shared.infra import (cerrar_conexion, consultar, ejecutar,
                          registrar_bitacora, salud_postgres, salud_redis)
from shared.paginacion import leer_paginacion, paginar
from shared.respuestas import ErrorApi, leer_cuerpo, responder
from shared.seguridad import (ADMINISTRADOR, ANALISTA, COORDINADOR, ENCARGADO_CENTRO,
                              ENCARGADO_REEMBOLSOS, INSPECTOR, OPERADOR_ALMACEN,
                              SUPERVISOR, exigir_autorizacion_operacion, requiere_jwt)

NOMBRE = "causa-raiz"
CONTRATOS = os.path.join(os.path.dirname(__file__), "contratos")
api = Blueprint("causa_raiz", __name__, url_prefix="/api/v1/causa-raiz")

OPERADORES = (ADMINISTRADOR, ANALISTA, SUPERVISOR)
INTERNOS = OPERADORES + (INSPECTOR, ENCARGADO_CENTRO, COORDINADOR, ENCARGADO_REEMBOLSOS, OPERADOR_ALMACEN)


def _xsd(nombre):
    return os.path.join(CONTRATOS, nombre)


def _seguimiento(iid, anterior, nuevo, comentario):
    ejecutar("""INSERT INTO seguimiento_investigacion (investigacion_id, estado_anterior,
                    estado_nuevo, comentario, usuario_id) VALUES (%s,%s,%s,%s,%s)""",
             (iid, anterior, nuevo, comentario, g.usuario["id"]))


def _investigacion(iid, bloquear=False):
    """FOR UPDATE serializa los cambios de una misma investigacion."""
    fila = consultar("SELECT * FROM investigaciones WHERE id=%s" + (" FOR UPDATE" if bloquear else ""),
                     (iid,), uno=True)
    if not fila:
        raise ErrorApi(404, "no_encontrado", "Investigacion inexistente.")
    return fila


def _mover(inv, nuevo, comentario, **campos):
    reglas.exigir_transicion(inv["estado"], nuevo)
    sets = ["estado=%s"] + [f"{c}=%s" for c in campos]
    ejecutar(f"UPDATE investigaciones SET {', '.join(sets)} WHERE id=%s",
             (nuevo, *campos.values(), inv["id"]))
    _seguimiento(inv["id"], inv["estado"], nuevo, comentario)


def _exigir_abierta_para_trabajo(inv):
    if inv["estado"] not in ("abierta", "en_verificacion"):
        raise ErrorApi(409, "investigacion_no_editable",
                       f"No se agregan hipotesis ni evidencias en una investigacion {inv['estado']}.")


def _crear_investigacion(limpio, alerta_id, origen):
    if consultar("SELECT 1 FROM investigaciones WHERE dimension=%s AND referencia_id=%s AND estado<>'cerrada'",
                 (limpio["dimension"], limpio["referencia_id"]), uno=True):
        raise ErrorApi(409, "investigacion_activa", "Ese objeto ya tiene una investigacion sin cerrar.")
    base = {**metricas.linea_base(limpio["dimension"], limpio["referencia_id"], date.today()),
            "origen": origen}
    fila = ejecutar("""
        INSERT INTO investigaciones (alerta_id, dimension, referencia_id, etiqueta, titulo,
            descripcion, analista_id, linea_base)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING id, folio""",
        (alerta_id, limpio["dimension"], limpio["referencia_id"], limpio["etiqueta"], limpio["titulo"],
         limpio["descripcion"], g.usuario["id"], json.dumps(base)), devolver=True)
    _seguimiento(fila["id"], None, "abierta", "Investigacion abierta")
    registrar_bitacora("alta_investigacion", "investigaciones", fila["id"],
                       f"{fila['folio']} sobre {limpio['dimension']} {limpio['referencia_id']}")
    return fila, base


# --------------------------------------------------------------------------- #
# Alertas (pasos 1 y 2)
# --------------------------------------------------------------------------- #
@api.post("/alertas/detectar")
@requiere_jwt(*OPERADORES)
def detectar():
    """Busca patrones y deja alertas; repetirlo actualiza las abiertas, no las duplica."""
    candidatos, promedio = metricas.detectar()
    nuevas = actualizadas = 0
    for c in candidatos:
        fila = ejecutar("""
            INSERT INTO alertas_patron (dimension, referencia_id, etiqueta, unidades_vendidas,
                unidades_devueltas, casos, tasa_pct, tasa_promedio_pct, veces_promedio)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (dimension, referencia_id) WHERE estado = 'abierta' DO UPDATE SET
                unidades_vendidas = EXCLUDED.unidades_vendidas,
                unidades_devueltas = EXCLUDED.unidades_devueltas, casos = EXCLUDED.casos,
                tasa_pct = EXCLUDED.tasa_pct, tasa_promedio_pct = EXCLUDED.tasa_promedio_pct,
                veces_promedio = EXCLUDED.veces_promedio, fecha_actualizacion = CURRENT_TIMESTAMP
            RETURNING (xmax = 0) AS nueva""",
            (c["dimension"], c["referencia_id"], c["etiqueta"], c["unidades_vendidas"],
             c["unidades_devueltas"], c["casos"], c["tasa_pct"], c["tasa_promedio_pct"],
             c["veces_promedio"]), devolver=True)
        nuevas += 1 if fila["nueva"] else 0
        actualizadas += 0 if fila["nueva"] else 1
    registrar_bitacora("deteccion_patrones", "alertas_patron", None,
                       f"Alertas nuevas: {nuevas}, actualizadas: {actualizadas}")
    return responder({"alertas_nuevas": nuevas, "alertas_actualizadas": actualizadas,
                      "tasa_promedio_pct": promedio,
                      "criterio": {"veces_promedio_minimo": reglas.VECES_ALERTA,
                                   "unidades_minimas": reglas.MIN_UNIDADES,
                                   "casos_minimos": reglas.MIN_CASOS},
                      "aviso": "Las alertas proponen investigar; no abren investigaciones ni determinan causas."},
                     raiz="deteccion")


@api.get("/alertas")
@requiere_jwt(*OPERADORES)
def alertas():
    pag = leer_paginacion()
    condiciones, params = ["TRUE"], []
    for campo, validos in (("estado", ("abierta", "investigando", "descartada")),
                           ("dimension", reglas.DIMENSIONES)):
        valor = request.args.get(campo)
        if valor:
            if valor not in validos:
                raise ErrorApi(400, "validacion", f"{campo} desconocido.")
            condiciones.append(f"a.{campo} = %s")
            params.append(valor)
    where = " AND ".join(condiciones)
    total = consultar(f"SELECT COUNT(*) AS n FROM alertas_patron a WHERE {where}",
                      tuple(params), uno=True)["n"]
    filas = consultar(f"""SELECT a.* FROM alertas_patron a WHERE {where}
                          ORDER BY a.veces_promedio DESC, a.id LIMIT %s OFFSET %s""",
                      tuple(params) + (pag.limite, pag.desplazamiento))
    return responder(paginar(filas, total, pag), raiz="alertas")


@api.post("/alertas/<int:aid>/descartar")
@requiere_jwt(*OPERADORES)
def descartar_alerta(aid):
    comentario = reglas.validar_descartar(leer_cuerpo(xsd=_xsd("descartar.xsd")))
    alerta = consultar("SELECT * FROM alertas_patron WHERE id=%s FOR UPDATE", (aid,), uno=True)
    if not alerta:
        raise ErrorApi(404, "no_encontrado", "Alerta inexistente.")
    if alerta["estado"] != "abierta":
        raise ErrorApi(409, "alerta_resuelta", f"La alerta ya esta {alerta['estado']}.")
    ejecutar("UPDATE alertas_patron SET estado='descartada', comentario=%s, resuelta_por=%s WHERE id=%s",
             (comentario, g.usuario["id"], aid))
    registrar_bitacora("alerta_descartada", "alertas_patron", aid, f"{alerta['dimension']} {alerta['referencia_id']}")
    return responder({"id": aid, "estado": "descartada"}, raiz="alerta")


@api.post("/alertas/<int:aid>/investigar")
@requiere_jwt(*OPERADORES)
def investigar_alerta(aid):
    """Paso 3: una persona decide abrir la investigacion que la alerta propone."""
    datos = reglas.validar_investigacion(leer_cuerpo(xsd=_xsd("investigacion_alerta.xsd")), desde_alerta=True)
    alerta = consultar("SELECT * FROM alertas_patron WHERE id=%s FOR UPDATE", (aid,), uno=True)
    if not alerta:
        raise ErrorApi(404, "no_encontrado", "Alerta inexistente.")
    if alerta["estado"] != "abierta":
        raise ErrorApi(409, "alerta_resuelta", f"La alerta ya esta {alerta['estado']}.")
    fila, base = _crear_investigacion(
        {**datos, "dimension": alerta["dimension"], "referencia_id": alerta["referencia_id"],
         "etiqueta": alerta["etiqueta"]}, aid, "alerta")
    ejecutar("UPDATE alertas_patron SET estado='investigando', resuelta_por=%s WHERE id=%s",
             (g.usuario["id"], aid))
    return responder({"id": fila["id"], "folio": fila["folio"], "estado": "abierta", "linea_base": base},
                     201, "investigacion", {"Location": f"/api/v1/causa-raiz/investigaciones/{fila['id']}"})


# --------------------------------------------------------------------------- #
# Investigaciones
# --------------------------------------------------------------------------- #
@api.post("/investigaciones")
@requiere_jwt(*OPERADORES)
def crear_investigacion():
    datos = reglas.validar_investigacion(leer_cuerpo(xsd=_xsd("investigacion.xsd")))
    nombre = metricas.etiqueta(datos["dimension"], datos["referencia_id"])
    if nombre is None:
        raise ErrorApi(404, "no_encontrado", f"No existe {datos['dimension']} con ese id.")
    fila, base = _crear_investigacion({**datos, "etiqueta": nombre}, None, "manual")
    return responder({"id": fila["id"], "folio": fila["folio"], "estado": "abierta", "linea_base": base},
                     201, "investigacion", {"Location": f"/api/v1/causa-raiz/investigaciones/{fila['id']}"})


@api.get("/investigaciones")
@requiere_jwt(*OPERADORES)
def investigaciones():
    pag = leer_paginacion()
    condiciones, params = ["TRUE"], []
    for campo, validos in (("estado", reglas.ESTADOS), ("dimension", reglas.DIMENSIONES)):
        valor = request.args.get(campo)
        if valor:
            if valor not in validos:
                raise ErrorApi(400, "validacion", f"{campo} desconocido.")
            condiciones.append(f"i.{campo} = %s")
            params.append(valor)
    if request.args.get("analista_id"):
        condiciones.append("i.analista_id = %s")
        params.append(reglas.entero_positivo(request.args["analista_id"], "analista_id"))
    where = " AND ".join(condiciones)
    total = consultar(f"SELECT COUNT(*) AS n FROM investigaciones i WHERE {where}",
                      tuple(params), uno=True)["n"]
    filas = consultar(f"""
        SELECT i.id, i.folio, i.titulo, i.dimension, i.referencia_id, i.etiqueta, i.estado,
               i.conclusion, i.veredicto_final, i.analista_id, u.nombre AS analista,
               i.fecha_creacion, i.fecha_cierre,
               (SELECT COUNT(*) FROM hipotesis h WHERE h.investigacion_id = i.id) AS hipotesis,
               (SELECT COUNT(*) FROM evidencias_investigacion e WHERE e.investigacion_id = i.id) AS evidencias,
               (SELECT COUNT(*) FROM acciones_capa a WHERE a.investigacion_id = i.id
                   AND a.estado <> 'cancelada') AS acciones
          FROM investigaciones i JOIN usuarios u ON u.id = i.analista_id
         WHERE {where} ORDER BY i.fecha_creacion DESC, i.id DESC LIMIT %s OFFSET %s""",
                      tuple(params) + (pag.limite, pag.desplazamiento))
    return responder(paginar(filas, total, pag), raiz="investigaciones")


SQL_ACCIONES = """
SELECT a.id, a.folio, a.investigacion_id, a.tipo, a.descripcion, a.responsable_id,
       u.nombre AS responsable, a.fecha_compromiso, a.estado, a.meta_reduccion_pct,
       a.fecha_implementacion, a.comentario_cierre,
       (a.fecha_compromiso < CURRENT_DATE AND a.estado IN ('planificada', 'en_curso')) AS vencida,
       m.veredicto AS ultimo_veredicto, m.reduccion_pct AS ultima_reduccion_pct,
       m.fecha_medicion AS ultima_medicion
  FROM acciones_capa a JOIN usuarios u ON u.id = a.responsable_id
  LEFT JOIN LATERAL (SELECT veredicto, reduccion_pct, fecha_medicion FROM mediciones_eficacia
                      WHERE accion_id = a.id ORDER BY fecha_medicion DESC, id DESC LIMIT 1) m ON TRUE
"""


@api.get("/investigaciones/<int:iid>")
@requiere_jwt(*OPERADORES)
def detalle_investigacion(iid):
    inv = consultar("""SELECT i.*, u.nombre AS analista, c.nombre AS cerrada_por_nombre
                         FROM investigaciones i JOIN usuarios u ON u.id = i.analista_id
                         LEFT JOIN usuarios c ON c.id = i.cerrada_por WHERE i.id = %s""", (iid,), uno=True)
    if not inv:
        raise ErrorApi(404, "no_encontrado", "Investigacion inexistente.")
    inv["hipotesis"] = consultar("""
        SELECT h.id, h.tipo, h.nivel, h.padre_id, h.categoria_ishikawa, h.descripcion, h.estado,
               h.resultado_verificacion, h.fecha_verificacion, uv.nombre AS verificada_por
          FROM hipotesis h LEFT JOIN usuarios uv ON uv.id = h.verificada_por
         WHERE h.investigacion_id = %s ORDER BY h.tipo, h.nivel, h.id""", (iid,))
    inv["evidencias"] = consultar("""
        SELECT e.id, e.tipo, e.descripcion, e.hipotesis_id, e.devolucion_id, d.folio_devolucion,
               e.referencia_externa, e.fecha_creacion, u.nombre AS creada_por
          FROM evidencias_investigacion e JOIN usuarios u ON u.id = e.creada_por
          LEFT JOIN devoluciones d ON d.id = e.devolucion_id
         WHERE e.investigacion_id = %s ORDER BY e.id""", (iid,))
    inv["acciones"] = consultar(SQL_ACCIONES + " WHERE a.investigacion_id = %s ORDER BY a.id", (iid,))
    inv["seguimiento"] = consultar("""
        SELECT s.estado_anterior, s.estado_nuevo, s.comentario, s.fecha, u.nombre AS usuario
          FROM seguimiento_investigacion s JOIN usuarios u ON u.id = s.usuario_id
         WHERE s.investigacion_id = %s ORDER BY s.fecha, s.id""", (iid,))
    inv["aviso"] = "El analisis apoya la decision; la conclusion es humana (RN-09)."
    return responder(inv, raiz="investigacion")


@api.post("/investigaciones/<int:iid>/hipotesis")
@requiere_jwt(*OPERADORES)
def agregar_hipotesis(iid):
    datos = leer_cuerpo(xsd=_xsd("hipotesis.xsd"))
    inv = _investigacion(iid, bloquear=True)
    _exigir_abierta_para_trabajo(inv)
    existentes = consultar("SELECT id, tipo, nivel, padre_id FROM hipotesis WHERE investigacion_id=%s", (iid,))
    h = reglas.validar_hipotesis(datos, existentes)
    fila = ejecutar("""INSERT INTO hipotesis (investigacion_id, tipo, nivel, padre_id, categoria_ishikawa,
                           descripcion, creada_por) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (iid, h["tipo"], h["nivel"], h["padre_id"], h["categoria_ishikawa"],
                     h["descripcion"], g.usuario["id"]), devolver=True)
    registrar_bitacora("alta_hipotesis", "investigaciones", iid, f"{h['tipo']} nivel {h['nivel']}")
    return responder({"id": fila["id"], "tipo": h["tipo"], "nivel": h["nivel"]}, 201, "hipotesis")


@api.post("/investigaciones/<int:iid>/evidencias")
@requiere_jwt(*OPERADORES)
def agregar_evidencia(iid):
    datos = reglas.validar_evidencia(leer_cuerpo(xsd=_xsd("evidencia.xsd")))
    inv = _investigacion(iid, bloquear=True)
    _exigir_abierta_para_trabajo(inv)
    if datos["devolucion_id"] and not metricas.devolucion_pertenece(
            datos["devolucion_id"], inv["dimension"], inv["referencia_id"]):
        raise ErrorApi(409, "devolucion_ajena",
                       "La devolucion no pertenece al objeto que se investiga o no existe.")
    if datos["hipotesis_id"] and not consultar(
            "SELECT 1 FROM hipotesis WHERE id=%s AND investigacion_id=%s", (datos["hipotesis_id"], iid), uno=True):
        raise ErrorApi(409, "hipotesis_ajena", "La hipotesis no pertenece a esta investigacion.")
    fila = ejecutar("""INSERT INTO evidencias_investigacion (investigacion_id, hipotesis_id, devolucion_id,
                           tipo, descripcion, referencia_externa, creada_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (iid, datos["hipotesis_id"], datos["devolucion_id"], datos["tipo"], datos["descripcion"],
                     datos["referencia_externa"], g.usuario["id"]), devolver=True)
    registrar_bitacora("alta_evidencia", "investigaciones", iid, f"Evidencia {fila['id']} ({datos['tipo']})")
    return responder({"id": fila["id"], "tipo": datos["tipo"]}, 201, "evidencia")


@api.post("/investigaciones/<int:iid>/verificacion")
@requiere_jwt(*OPERADORES)
def iniciar_verificacion(iid):
    """Paso 5: pasa de juntar evidencia a verificar las hipotesis."""
    leer_cuerpo(xsd=_xsd("vacio.xsd"))
    inv = _investigacion(iid, bloquear=True)
    reglas.exigir_transicion(inv["estado"], "en_verificacion")
    if not consultar("SELECT 1 FROM hipotesis WHERE investigacion_id=%s", (iid,), uno=True):
        raise ErrorApi(409, "sin_hipotesis", "Escribe al menos una hipotesis antes de verificar.")
    _mover(inv, "en_verificacion", "Inicia la verificacion de hipotesis")
    registrar_bitacora("inicio_verificacion", "investigaciones", iid, inv["folio"])
    return responder({"id": iid, "estado": "en_verificacion"}, raiz="investigacion")


@api.post("/investigaciones/<int:iid>/hipotesis/<int:hid>/verificacion")
@requiere_jwt(*OPERADORES)
def verificar_hipotesis(iid, hid):
    resultado, texto = reglas.validar_verificacion(leer_cuerpo(xsd=_xsd("verificacion_hipotesis.xsd")))
    inv = _investigacion(iid, bloquear=True)
    if inv["estado"] != "en_verificacion":
        raise ErrorApi(409, "fuera_de_verificacion", "Las hipotesis se verifican en la etapa de verificacion.")
    h = consultar("SELECT id, estado FROM hipotesis WHERE id=%s AND investigacion_id=%s FOR UPDATE",
                  (hid, iid), uno=True)
    if not h:
        raise ErrorApi(404, "no_encontrado", "Hipotesis inexistente en esta investigacion.")
    if h["estado"] != "propuesta":
        raise ErrorApi(409, "ya_verificada", f"La hipotesis ya esta {h['estado']}.")
    ejecutar("""UPDATE hipotesis SET estado=%s, resultado_verificacion=%s, verificada_por=%s,
                    fecha_verificacion=CURRENT_TIMESTAMP WHERE id=%s""",
             (resultado, texto, g.usuario["id"], hid))
    registrar_bitacora("verificacion_hipotesis", "investigaciones", iid, f"Hipotesis {hid}: {resultado}")
    return responder({"id": hid, "estado": resultado}, raiz="hipotesis")


@api.post("/investigaciones/<int:iid>/conclusion")
@requiere_jwt(*OPERADORES)
def concluir(iid):
    """Paso 6: causa confirmada o inconclusa. Confirmar exige evidencia (RN-09)."""
    datos = leer_cuerpo(xsd=_xsd("conclusion.xsd"))
    inv = _investigacion(iid, bloquear=True)
    reglas.exigir_transicion(inv["estado"], "concluida")
    verificadas = consultar("SELECT COUNT(*) AS n FROM hipotesis WHERE investigacion_id=%s AND estado='verificada'",
                            (iid,), uno=True)["n"]
    evidencias = consultar("SELECT COUNT(*) AS n FROM evidencias_investigacion WHERE investigacion_id=%s",
                           (iid,), uno=True)["n"]
    conclusion, causa, justificacion = reglas.validar_conclusion(datos, verificadas, evidencias)
    ejecutar("""UPDATE investigaciones SET estado='concluida', conclusion=%s, causa_raiz=%s,
                    justificacion=%s, fecha_conclusion=CURRENT_TIMESTAMP WHERE id=%s""",
             (conclusion, causa, justificacion, iid))
    _seguimiento(iid, inv["estado"], "concluida", f"Conclusion: {conclusion}")
    registrar_bitacora("conclusion_investigacion", "investigaciones", iid, f"{inv['folio']}: {conclusion}")
    return responder({"id": iid, "estado": "concluida", "conclusion": conclusion}, raiz="investigacion")


@api.post("/investigaciones/<int:iid>/reabrir")
@requiere_jwt(*OPERADORES)
def reabrir(iid):
    """Una investigacion inconclusa vuelve a verificacion si hay mas informacion."""
    comentario = reglas.validar_cierre(leer_cuerpo(xsd=_xsd("cierre.xsd")))
    inv = _investigacion(iid, bloquear=True)
    if inv["estado"] != "concluida" or inv["conclusion"] != "inconclusa":
        raise ErrorApi(409, "no_reabrible", "Solo se reabre una investigacion concluida como inconclusa.")
    ejecutar("""UPDATE investigaciones SET estado='en_verificacion', conclusion=NULL, causa_raiz=NULL,
                    justificacion=NULL, fecha_conclusion=NULL WHERE id=%s""", (iid,))
    _seguimiento(iid, "concluida", "en_verificacion", f"Reabierta: {comentario}"[:500])
    registrar_bitacora("reapertura_investigacion", "investigaciones", iid, inv["folio"])
    return responder({"id": iid, "estado": "en_verificacion"}, raiz="investigacion")


@api.post("/investigaciones/<int:iid>/cierre")
@requiere_jwt(SUPERVISOR)
def cerrar(iid):
    """Paso 9: lo cierra un supervisor distinto del analista, reconfirmando su contrasena."""
    comentario = reglas.validar_cierre(leer_cuerpo(xsd=_xsd("cierre.xsd")))
    inv = _investigacion(iid, bloquear=True)
    reglas.exigir_transicion(inv["estado"], "cerrada")
    if inv["analista_id"] == g.usuario["id"]:
        raise ErrorApi(409, "cierre_independiente",
                       "Quien lleva la investigacion no puede cerrarla; lo hace otro supervisor.")
    acciones = consultar("""
        SELECT a.id, a.estado,
               (SELECT veredicto FROM mediciones_eficacia WHERE accion_id = a.id
                 ORDER BY fecha_medicion DESC, id DESC LIMIT 1) AS veredicto
          FROM acciones_capa a WHERE a.investigacion_id = %s AND a.estado <> 'cancelada'""", (iid,))
    if inv["estado"] == "concluida" and inv["conclusion"] != "inconclusa":
        raise ErrorApi(409, "requiere_acciones",
                       "Una causa confirmada se cierra despues de corregirla y medir la correccion.")
    if inv["estado"] == "en_accion" and acciones:
        raise ErrorApi(409, "requiere_medicion", "Mide la eficacia de las acciones antes de cerrar.")
    pendientes = [a["id"] for a in acciones if a["estado"] in ("planificada", "en_curso")]
    if pendientes:
        raise ErrorApi(409, "acciones_pendientes", "Hay acciones sin implementar o cancelar.",
                       [{"campo": "acciones", "problema": str(i)} for i in pendientes[:20]])
    sin_medir = [a["id"] for a in acciones if a["veredicto"] is None]
    if sin_medir:
        raise ErrorApi(409, "sin_medicion", "Hay acciones implementadas sin medir.",
                       [{"campo": "acciones", "problema": str(i)} for i in sin_medir[:20]])
    veredicto = reglas.veredicto_global([a["veredicto"] for a in acciones])
    # El permiso es de un solo uso: se consume al final, cuando ya solo falta guardar.
    exigir_autorizacion_operacion("cerrar_investigacion", iid)
    ejecutar("""UPDATE investigaciones SET estado='cerrada', cerrada_por=%s, comentario_cierre=%s,
                    veredicto_final=%s, fecha_cierre=CURRENT_TIMESTAMP WHERE id=%s""",
             (g.usuario["id"], comentario, veredicto, iid))
    _seguimiento(iid, inv["estado"], "cerrada", f"Cierre ({veredicto})")
    registrar_bitacora("cierre_investigacion", "investigaciones", iid, f"{inv['folio']}: {veredicto}")
    return responder({"id": iid, "estado": "cerrada", "veredicto_final": veredicto}, raiz="investigacion")


# --------------------------------------------------------------------------- #
# Acciones correctivas y preventivas (paso 7)
# --------------------------------------------------------------------------- #
@api.post("/investigaciones/<int:iid>/acciones")
@requiere_jwt(*OPERADORES)
def crear_accion(iid):
    datos = reglas.validar_capa(leer_cuerpo(xsd=_xsd("accion.xsd")))
    inv = _investigacion(iid, bloquear=True)
    if inv["estado"] not in ("concluida", "en_accion") or inv["conclusion"] != "causa_confirmada":
        raise ErrorApi(409, "sin_causa_confirmada",
                       "Las acciones se crean cuando la causa esta confirmada.")
    responsable = consultar("""SELECT u.id, r.nombre AS rol FROM usuarios u JOIN roles r ON r.id = u.rol_id
                                WHERE u.id=%s AND u.estado='activo' AND u.eliminado_en IS NULL""",
                            (datos["responsable_id"],), uno=True)
    if not responsable or responsable["rol"] not in INTERNOS:
        raise ErrorApi(409, "responsable_invalido", "El responsable debe ser personal interno activo.")
    fila = ejecutar("""INSERT INTO acciones_capa (investigacion_id, tipo, descripcion, responsable_id,
                           fecha_compromiso, meta_reduccion_pct, creada_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id, folio""",
                    (iid, datos["tipo"], datos["descripcion"], datos["responsable_id"],
                     datos["fecha_compromiso"], datos["meta_reduccion_pct"], g.usuario["id"]), devolver=True)
    if inv["estado"] == "concluida":
        _mover(inv, "en_accion", f"Se crea la accion {fila['folio']}")
    registrar_bitacora("alta_accion_capa", "investigaciones", iid, f"{fila['folio']} para usuario {datos['responsable_id']}")
    return responder({"id": fila["id"], "folio": fila["folio"], "estado": "planificada"}, 201, "accion",
                     {"Location": f"/api/v1/causa-raiz/acciones/{fila['id']}"})


def _es_operador():
    return g.usuario["rol"] in OPERADORES


@api.get("/acciones")
@requiere_jwt(*INTERNOS)
def acciones():
    """Cada responsable ve las suyas; los operadores ven todas."""
    pag = leer_paginacion()
    condiciones, params = ["TRUE"], []
    if not _es_operador():
        condiciones.append("a.responsable_id = %s")
        params.append(g.usuario["id"])
    elif request.args.get("responsable_id"):
        condiciones.append("a.responsable_id = %s")
        params.append(reglas.entero_positivo(request.args["responsable_id"], "responsable_id"))
    estado = request.args.get("estado")
    if estado:
        if estado not in reglas.TRANSICIONES_CAPA:
            raise ErrorApi(400, "validacion", "estado desconocido.")
        condiciones.append("a.estado = %s")
        params.append(estado)
    if request.args.get("investigacion_id"):
        condiciones.append("a.investigacion_id = %s")
        params.append(reglas.entero_positivo(request.args["investigacion_id"], "investigacion_id"))
    if request.args.get("vencidas", "false").lower() == "true":
        condiciones.append("a.fecha_compromiso < CURRENT_DATE AND a.estado IN ('planificada', 'en_curso')")
    where = " AND ".join(condiciones)
    total = consultar(f"SELECT COUNT(*) AS n FROM acciones_capa a WHERE {where}", tuple(params), uno=True)["n"]
    filas = consultar(f"{SQL_ACCIONES} WHERE {where} ORDER BY a.fecha_compromiso, a.id LIMIT %s OFFSET %s",
                      tuple(params) + (pag.limite, pag.desplazamiento))
    return responder(paginar(filas, total, pag), raiz="acciones")


def _accion(aid, bloquear=False):
    fila = consultar("SELECT * FROM acciones_capa WHERE id=%s" + (" FOR UPDATE" if bloquear else ""),
                     (aid,), uno=True)
    if not fila:
        raise ErrorApi(404, "no_encontrado", "Accion inexistente.")
    if not _es_operador() and fila["responsable_id"] != g.usuario["id"]:
        # 404 y no 403: no revela que la accion existe a quien no le corresponde (RN-13).
        raise ErrorApi(404, "no_encontrado", "Accion inexistente.")
    return fila


@api.get("/acciones/<int:aid>")
@requiere_jwt(*INTERNOS)
def detalle_accion(aid):
    _accion(aid)
    fila = consultar(SQL_ACCIONES + " WHERE a.id = %s", (aid,), uno=True)
    fila["mediciones"] = consultar("SELECT * FROM mediciones_eficacia WHERE accion_id=%s "
                                   "ORDER BY fecha_medicion DESC, id DESC", (aid,))
    return responder(fila, raiz="accion")


@api.post("/acciones/<int:aid>/estado")
@requiere_jwt(*INTERNOS)
def estado_accion(aid):
    """Avanza la accion: la mueve su responsable o un operador (RN-13)."""
    datos = leer_cuerpo(xsd=_xsd("estado_accion.xsd"))
    actual = _accion(aid, bloquear=True)
    nuevo, fecha, comentario = reglas.validar_estado_capa(datos, actual["estado"])
    ejecutar("""UPDATE acciones_capa SET estado=%s, fecha_implementacion=%s,
                    comentario_cierre=COALESCE(%s, comentario_cierre) WHERE id=%s""",
             (nuevo, fecha, comentario, aid))
    registrar_bitacora("estado_accion_capa", "acciones_capa", aid, f"{actual['folio']}: {actual['estado']} -> {nuevo}")
    return responder({"id": aid, "folio": actual["folio"], "estado": nuevo,
                      "fecha_implementacion": fecha}, raiz="accion")


# --------------------------------------------------------------------------- #
# Medicion de eficacia (paso 8)
# --------------------------------------------------------------------------- #
@api.post("/acciones/<int:aid>/mediciones")
@requiere_jwt(*OPERADORES)
def medir(aid):
    """Compara la tasa de lo vendido antes contra lo vendido despues de implementar.

    Las ventas de los ultimos dias aun pueden devolverse, asi que 'despues' se
    corta en hoy menos el plazo maximo de devolucion. Con poca muestra el
    veredicto es sin_datos, nunca efectiva.
    """
    ventana, hasta = reglas.validar_medicion(leer_cuerpo(xsd=_xsd("medicion.xsd")))
    accion = _accion(aid)
    inv = _investigacion(accion["investigacion_id"], bloquear=True)
    if accion["estado"] != "implementada":
        raise ErrorApi(409, "accion_no_implementada", "Solo se mide una accion ya implementada.")
    if inv["estado"] not in ("en_accion", "en_medicion"):
        raise ErrorApi(409, "investigacion_no_medible", f"La investigacion esta {inv['estado']}.")
    hoy = date.today()
    p = reglas.periodos_medicion(accion["fecha_implementacion"], hoy, metricas.plazo_maximo(), ventana, hasta)
    dim, ref = inv["dimension"], inv["referencia_id"]
    antes = metricas.cohorte(dim, ref, p["antes_desde"], p["antes_hasta"])
    despues = ({"unidades_vendidas": 0, "unidades_devueltas": 0, "casos": 0} if p["inmaduro"]
               else metricas.cohorte(dim, ref, p["despues_desde"], p["despues_hasta"]))
    r = reglas.calcular_medicion(antes["unidades_vendidas"], antes["unidades_devueltas"],
                                 despues["unidades_vendidas"], despues["unidades_devueltas"],
                                 accion["meta_reduccion_pct"], p["inmaduro"], p["madurez_hasta"])
    fila = ejecutar("""
        INSERT INTO mediciones_eficacia (accion_id, antes_desde, antes_hasta, despues_desde, despues_hasta,
            antes_vendidas, antes_devueltas, antes_tasa_pct, despues_vendidas, despues_devueltas,
            despues_tasa_pct, reduccion_pct, meta_reduccion_pct, veredicto, motivo_sin_datos, medido_por)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (aid, p["antes_desde"], p["antes_hasta"], p["despues_desde"], p["despues_hasta"],
         antes["unidades_vendidas"], antes["unidades_devueltas"], r["antes_tasa_pct"],
         despues["unidades_vendidas"], despues["unidades_devueltas"], r["despues_tasa_pct"],
         r["reduccion_pct"], accion["meta_reduccion_pct"], r["veredicto"], r["motivo_sin_datos"],
         g.usuario["id"]), devolver=True)
    if inv["estado"] == "en_accion":
        _mover(inv, "en_medicion", f"Primera medicion de {accion['folio']}: {r['veredicto']}")
    registrar_bitacora("medicion_eficacia", "acciones_capa", aid, f"{accion['folio']}: {r['veredicto']}")
    return responder({"id": fila["id"], "accion_id": aid,
                      "antes": {"desde": p["antes_desde"], "hasta": p["antes_hasta"], **antes,
                                "tasa_pct": r["antes_tasa_pct"]},
                      "despues": {"desde": p["despues_desde"], "hasta": p["despues_hasta"], **despues,
                                  "tasa_pct": r["despues_tasa_pct"]},
                      "reduccion_pct": r["reduccion_pct"], "meta_reduccion_pct": accion["meta_reduccion_pct"],
                      "veredicto": r["veredicto"], "motivo_sin_datos": r["motivo_sin_datos"],
                      "aviso": "Compara cohortes de venta; un buen resultado orienta, no prueba causalidad (RN-09)."},
                     201, "medicion")


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
