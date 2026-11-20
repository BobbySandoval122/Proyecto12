"""Integracion real de integraciones y monitoreo sobre PostgreSQL y MongoDB.

Sin dobles: tokens del servicio auth real, peticiones al contenedor y efectos
verificados en las bases. Lo que crea la prueba se borra al terminar. Solo
corre en la VM:

    docker compose run --rm -e INTEGRACION=1 integraciones-monitoreo python -m pytest -v tests/test_integracion.py

Trazabilidad: RNF-28, RF-05, RF-06, RF-13, RF-32, RNF-22, RNF-23, dominios 21 y 22.
"""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import date

import psycopg2
import psycopg2.extras

import monitor
from shared import mongo

AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8000")
URL = os.environ.get("INTEGRACIONES_URL", "http://integraciones-monitoreo:8000")
FANTASMA = "fantasma-prueba"


def _sql(sentencia, params=(), uno=False):
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        dbname=os.environ.get("POSTGRES_DB", "devoluciones"),
        user=os.environ.get("POSTGRES_USER", "devoluciones_app"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sentencia, params)
            if cur.description is None:
                return None
            return cur.fetchone() if uno else cur.fetchall()
    finally:
        conn.close()


def _http(metodo, ruta, cuerpo=None, token=None, base=URL, xml=None, cabeceras=None):
    h = {"Content-Type": "application/xml" if xml else "application/json",
         "Accept": "application/xml" if xml else "application/json", **(cabeceras or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    datos = xml.encode() if xml else (json.dumps(cuerpo).encode() if cuerpo is not None else None)
    peticion = urllib.request.Request(base + ruta, method=metodo, headers=h, data=datos)
    try:
        with urllib.request.urlopen(peticion, timeout=30) as resp:
            crudo = resp.read()
            return resp.status, (crudo if h["Accept"] == "application/xml" else json.loads(crudo or b"null"))
    except urllib.error.HTTPError as exc:
        crudo = exc.read()
        try:
            return exc.code, json.loads(crudo)
        except ValueError:
            return exc.code, crudo


def _login_rol(rol):
    fila = _sql("""SELECT u.email FROM usuarios u JOIN roles r ON r.id = u.rol_id
                    WHERE r.nombre = %s AND u.estado = 'activo' AND u.eliminado_en IS NULL
                      AND RIGHT(u.email, 8) = '@demo.mx' ORDER BY u.id LIMIT 1""", (rol,), uno=True)
    if not fila:
        raise unittest.SkipTest(f"No hay usuario demo con rol {rol} (corre seed_demo)")
    codigo, cuerpo = _http("POST", "/api/v1/auth/login",
                           {"email": fila["email"], "password": os.environ["PASSWORD_DEMO"]}, base=AUTH_URL)
    if codigo != 200:
        raise AssertionError(f"login de {rol} respondio {codigo}")
    return cuerpo["access_token"], fila["email"]


SKIP = unittest.skipUnless(os.environ.get("INTEGRACION") == "1",
                           "Solo en la VM: INTEGRACION=1 y el entorno levantado")


@SKIP
class IntegracionIntegracionesMonitoreo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sufijo = uuid.uuid4().hex[:8].upper()
        cls.admin, _ = _login_rol("Administrador")
        cls.supervisor, _ = _login_rol("Supervisor")
        cls.coordinador, _ = _login_rol("Coordinador de Logistica")
        cls.cliente, cls.email_cliente = _login_rol("Cliente")
        cls.tienda = _sql("SELECT id FROM tiendas WHERE activo ORDER BY id LIMIT 1", uno=True)["id"]
        cls.lote = _sql("""SELECT p.sku, l.numero_lote FROM lotes l JOIN productos p ON p.id = l.producto_id
                            WHERE l.activo AND p.activo ORDER BY l.id LIMIT 1""", uno=True)
        cls.externos, cls.devoluciones = [], []

    @classmethod
    def tearDownClass(cls):
        ventas = _sql("""SELECT id_interno FROM integraciones_ids
                          WHERE sistema = 'pos' AND tipo_entidad = 'venta' AND id_externo LIKE %s""",
                      (f"%{cls.sufijo}%",))
        _sql("DELETE FROM integraciones_ids WHERE id_externo LIKE %s", (f"%{cls.sufijo}%",))
        if cls.devoluciones:
            ids = tuple(cls.devoluciones)
            _sql("DELETE FROM recolecciones WHERE devolucion_id IN %s", (ids,))
            _sql("DELETE FROM devoluciones WHERE id IN %s", (ids,))
        for v in ventas:
            _sql("DELETE FROM venta_detalle WHERE venta_id = %s", (v["id_interno"],))
            _sql("DELETE FROM ventas WHERE id = %s", (v["id_interno"],))
        db = mongo.get_mongo()
        db.alertas_operativas.delete_many({"recurso": FANTASMA})
        db.monitoreo_chequeos.delete_many({"servicios.servicio": FANTASMA})
        for token in (cls.admin, cls.supervisor, cls.coordinador, cls.cliente):
            _http("POST", "/api/v1/auth/logout", token=token, base=AUTH_URL)

    def _venta(self, ticket, tienda=None):
        return {"id_externo": ticket, "tienda_externa": tienda or f"T-{self.sufijo}",
                "cliente_email": self.email_cliente, "fecha_venta": date.today().isoformat(),
                "lineas": [{"sku": self.lote["sku"], "numero_lote": self.lote["numero_lote"],
                            "cantidad": 3, "precio_unitario": 45.5}]}

    def _conciliar_tienda(self):
        return _http("POST", "/api/v1/integraciones/conciliaciones",
                     {"sistema": "pos", "tipo_entidad": "tienda", "id_externo": f"T-{self.sufijo}",
                      "id_interno": self.tienda}, token=self.admin,
                     cabeceras={"X-Correlation-ID": f"prueba-{self.sufijo}"})

    # ------------------------------------------------------------------ #
    # Integraciones
    # ------------------------------------------------------------------ #
    def test_1_venta_del_pos_sin_conciliar_y_luego_importada_una_vez(self):
        ticket = f"TK-{self.sufijo}-1"
        codigo, cuerpo = _http("POST", "/api/v1/integraciones/ventas", self._venta(ticket), token=self.admin)
        self.assertEqual((codigo, cuerpo["error"]["tipo"]), (422, "sin_conciliar"))
        self.assertIn(self._conciliar_tienda()[0], (200, 201))
        codigo, primera = _http("POST", "/api/v1/integraciones/ventas", self._venta(ticket), token=self.admin)
        self.assertEqual(codigo, 201, primera)
        codigo, segunda = _http("POST", "/api/v1/integraciones/ventas", self._venta(ticket), token=self.admin)
        self.assertEqual((codigo, segunda["repetida"], segunda["venta_id"]), (200, True, primera["venta_id"]))
        self.assertEqual(_sql("SELECT count(*) AS n FROM ventas WHERE folio_venta = %s",
                              (f"POS-{ticket}",), uno=True)["n"], 1)
        detalle = _sql("SELECT cantidad, precio_unitario FROM venta_detalle WHERE venta_id = %s",
                       (primera["venta_id"],))
        self.assertEqual([(d["cantidad"], float(d["precio_unitario"])) for d in detalle], [(3, 45.5)])

    def test_2_dos_envios_simultaneos_del_mismo_ticket(self):
        self._conciliar_tienda()
        ticket = f"TK-{self.sufijo}-2"
        respuestas = []
        hilos = [threading.Thread(target=lambda: respuestas.append(
            _http("POST", "/api/v1/integraciones/ventas", self._venta(ticket), token=self.admin)))
            for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(sorted(c for c, _ in respuestas), [200, 201])
        self.assertEqual(_sql("SELECT count(*) AS n FROM ventas WHERE folio_venta = %s",
                              (f"POS-{ticket}",), uno=True)["n"], 1)

    def test_3_venta_en_xml_y_exportacion_para_erp(self):
        self._conciliar_tienda()
        ticket = f"TK-{self.sufijo}-3"
        xml = f"""<?xml version="1.0" encoding="UTF-8"?><venta><id_externo>{ticket}</id_externo>
<tienda_externa>T-{self.sufijo}</tienda_externa><cliente_email>{self.email_cliente}</cliente_email>
<fecha_venta>{date.today().isoformat()}</fecha_venta><lineas><item><sku>{self.lote['sku']}</sku>
<numero_lote>{self.lote['numero_lote']}</numero_lote><cantidad>2</cantidad>
<precio_unitario>19.90</precio_unitario></item></lineas></venta>"""
        codigo, cuerpo = _http("POST", "/api/v1/integraciones/ventas", token=self.admin, xml=xml)
        self.assertEqual(codigo, 201, cuerpo)
        venta_id = _sql("SELECT id_interno FROM integraciones_ids WHERE sistema='pos' AND tipo_entidad='venta' "
                        "AND id_externo = %s", (ticket,), uno=True)["id_interno"]
        linea = _sql("SELECT id FROM venta_detalle WHERE venta_id = %s", (venta_id,), uno=True)["id"]
        motivo = _sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1", uno=True)["id"]
        dev = _sql("""INSERT INTO devoluciones (venta_detalle_id, motivo_id, descripcion_problema, cantidad_devuelta)
                      VALUES (%s, %s, 'Prueba de exportacion al ERP.', 1) RETURNING id""",
                   (linea, motivo), uno=True)["id"]
        self.devoluciones.append(dev)
        hoy = date.today().isoformat()
        codigo, cuerpo = _http("GET", f"/api/v1/integraciones/exportaciones/devoluciones?desde={hoy}&hasta={hoy}"
                                      "&por_pagina=100", token=self.admin)
        self.assertEqual(codigo, 200)
        fila = next(f for f in cuerpo["datos"] if f["devolucion_id"] == dev)
        self.assertEqual((fila["venta_id_pos"], fila["sku"]), (ticket, self.lote["sku"]))
        codigo, crudo = _http("GET", f"/api/v1/integraciones/exportaciones/devoluciones?desde={hoy}",
                              token=self.admin, cabeceras={"Accept": "application/xml"})
        self.assertEqual(codigo, 200)
        self.assertIn(b"<exportacion>", crudo)
        codigo, _ = _http("GET", "/api/v1/integraciones/exportaciones/devoluciones", token=self.cliente)
        self.assertEqual(codigo, 403)

    def test_4_evento_del_transportista_sin_duplicar(self):
        venta = _sql("SELECT vd.id FROM venta_detalle vd ORDER BY vd.id LIMIT 1", uno=True)["id"]
        motivo = _sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1", uno=True)["id"]
        dev = _sql("""INSERT INTO devoluciones (venta_detalle_id, motivo_id, descripcion_problema,
                                                cantidad_devuelta, estado)
                      VALUES (%s, %s, 'Prueba de transportista.', 1, 'en_recoleccion') RETURNING id""",
                   (venta, motivo), uno=True)["id"]
        self.devoluciones.append(dev)
        rec = _sql("""INSERT INTO recolecciones (devolucion_id, fecha_programada, lugar, estado)
                      VALUES (%s, CURRENT_DATE, 'Prueba', 'asignada') RETURNING id""", (dev,), uno=True)["id"]
        guia = f"GUIA-{self.sufijo}"
        evento = {"guia": guia, "estado": "en_transito"}
        codigo, cuerpo = _http("POST", "/api/v1/integraciones/transportistas/eventos", evento, token=self.coordinador)
        self.assertEqual((codigo, cuerpo["error"]["tipo"]), (422, "sin_conciliar"))
        codigo, _ = _http("POST", "/api/v1/integraciones/conciliaciones",
                          {"sistema": "transportista", "tipo_entidad": "recoleccion", "id_externo": guia,
                           "id_interno": rec}, token=self.admin)
        self.assertEqual(codigo, 201)
        codigo, cuerpo = _http("POST", "/api/v1/integraciones/transportistas/eventos", evento, token=self.coordinador)
        self.assertEqual((codigo, cuerpo["cambio"]), (200, True))
        codigo, cuerpo = _http("POST", "/api/v1/integraciones/transportistas/eventos", evento, token=self.coordinador)
        self.assertEqual((codigo, cuerpo["cambio"]), (200, False))
        _http("POST", "/api/v1/integraciones/transportistas/eventos", {"guia": guia, "estado": "completada"},
              token=self.coordinador)
        codigo, cuerpo = _http("POST", "/api/v1/integraciones/transportistas/eventos",
                               {"guia": guia, "estado": "fallida"}, token=self.coordinador)
        self.assertEqual((codigo, cuerpo["error"]["tipo"]), (409, "transicion_invalida"))
        self.assertEqual(_sql("SELECT estado FROM recolecciones WHERE id = %s", (rec,), uno=True)["estado"],
                         "completada")

    def test_5_conciliacion_distinta_se_rechaza(self):
        self._conciliar_tienda()
        otra = _sql("SELECT id FROM tiendas WHERE id <> %s ORDER BY id LIMIT 1", (self.tienda,), uno=True)
        if not otra:
            self.skipTest("Solo hay una tienda")
        codigo, cuerpo = _http("POST", "/api/v1/integraciones/conciliaciones",
                               {"sistema": "pos", "tipo_entidad": "tienda", "id_externo": f"T-{self.sufijo}",
                                "id_interno": otra["id"]}, token=self.admin)
        self.assertEqual((codigo, cuerpo["error"]["tipo"]), (409, "conciliacion_distinta"))
        codigo, cuerpo = _http("GET", f"/api/v1/integraciones/conciliaciones/pos/tienda/T-{self.sufijo}",
                               token=self.admin)
        self.assertEqual((codigo, cuerpo["id_interno"]), (200, self.tienda))

    # ------------------------------------------------------------------ #
    # Monitoreo
    # ------------------------------------------------------------------ #
    def test_6_estado_de_toda_la_plataforma(self):
        codigo, cuerpo = _http("GET", "/api/v1/monitoreo/estado", token=self.supervisor)
        self.assertEqual(codigo, 200, cuerpo)
        nombres = {s["servicio"] for s in cuerpo["servicios"]}
        self.assertTrue({"auth", "devoluciones", "sincronizacion", "web"} <= nombres)
        self.assertTrue(all(b["ok"] for b in cuerpo["bases"].values()), cuerpo["bases"])
        auth = next(s for s in cuerpo["servicios"] if s["servicio"] == "auth")
        self.assertEqual(auth["estado"], "ok")
        self.assertIsInstance(auth["ms"], int)
        self.assertIn("conflicto_24h", cuerpo["colas"]["operaciones_offline"])

    def test_7_alerta_se_abre_y_se_resuelve_sola(self):
        db = mongo.get_mongo()
        monitor.chequear({FANTASMA: "http://fantasma-prueba-no-existe:8000"})
        monitor.chequear({FANTASMA: "http://fantasma-prueba-no-existe:8000"})
        activa = db.alertas_operativas.find_one({"recurso": FANTASMA, "estado": "activa"})
        self.assertIsNotNone(activa)
        self.assertEqual((activa["tipo"], activa["severidad"], activa["veces"]), ("servicio_caido", "alta", 2))
        codigo, cuerpo = _http("GET", "/api/v1/monitoreo/alertas?estado=activa&por_pagina=100", token=self.admin)
        self.assertIn(FANTASMA, {a["recurso"] for a in cuerpo["datos"]})
        # El "servicio" vuelve: la alerta se cierra sin intervencion.
        monitor.chequear({FANTASMA: "http://auth:8000"})
        self.assertIsNone(db.alertas_operativas.find_one({"recurso": FANTASMA, "estado": "activa"}))
        self.assertIsNotNone(db.alertas_operativas.find_one({"recurso": FANTASMA, "estado": "resuelta"}))
        codigo, cuerpo = _http("GET", "/api/v1/monitoreo/disponibilidad?horas=1", token=self.admin)
        fantasma = next(s for s in cuerpo["servicios"] if s["servicio"] == FANTASMA)
        self.assertEqual((fantasma["chequeos"], fantasma["caido"], fantasma["ok"]), (3, 2, 1))

    def test_8_traza_distribuida(self):
        self._conciliar_tienda()
        codigo, cuerpo = _http("GET", f"/api/v1/monitoreo/traza/prueba-{self.sufijo}", token=self.admin)
        self.assertEqual(codigo, 200, cuerpo)
        self.assertIn("conciliacion_registrada", [p["accion"] for p in cuerpo["pasos"]])
        codigo, _ = _http("GET", "/api/v1/monitoreo/traza/no-existe-nada-123", token=self.admin)
        self.assertEqual(codigo, 404)


if __name__ == "__main__":
    unittest.main()
