"""Integracion real de proveedores contra la VM (PostgreSQL, Redis y auth reales).

    docker compose run --rm -e INTEGRACION=1 -e PASSWORD_DEMO=... proveedores \
        python -m pytest -v tests/test_integracion.py

Crea sus propias devoluciones y reclamaciones y las borra al terminar.
Trazabilidad: RF-24, RF-26, RN-09, RN-12, RN-13, RNF-09, RNF-28.
"""
import json
import os
import unittest
import urllib.error
import urllib.request

import psycopg2
import psycopg2.extras

AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8000")
SERVICIO_URL = os.environ.get("PROVEEDORES_URL", "http://proveedores:8000")
BASE = "/api/v1/proveedores"
SKIP = unittest.skipUnless(os.environ.get("INTEGRACION") == "1",
                           "Solo en la VM: INTEGRACION=1 y el entorno levantado")


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


def _http(base, metodo, ruta, cuerpo=None, token=None):
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(
        base + ruta, method=metodo, headers=cabeceras,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(peticion, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        crudo = exc.read()
        try:
            return exc.code, json.loads(crudo)
        except ValueError:
            return exc.code, None


def _login(rol):
    fila = _sql("""SELECT u.email FROM usuarios u JOIN roles r ON r.id = u.rol_id
                    WHERE r.nombre = %s AND u.estado = 'activo' AND u.eliminado_en IS NULL
                    ORDER BY u.id LIMIT 1""", (rol,), uno=True)
    if not fila:
        raise unittest.SkipTest(f"No hay usuario activo con rol {rol} (corre seed_demo)")
    codigo, cuerpo = _http(AUTH_URL, "POST", "/api/v1/auth/login",
                           {"email": fila["email"], "password": os.environ["PASSWORD_DEMO"]})
    if codigo != 200:
        raise AssertionError(f"login de {rol} respondio {codigo}")
    return cuerpo["access_token"]


@SKIP
class IntegracionProveedores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = _login("Administrador")
        cls.analista = _login("Analista de Devoluciones")
        cls.inspector = _login("Inspector")
        cls.cliente = _login("Cliente")
        cls.devoluciones, cls.reclamaciones = [], []
        # Un proveedor con una linea de venta y otro proveedor distinto.
        linea = _sql("""SELECT vd.id AS detalle, l.id AS lote, l.proveedor_id
                          FROM venta_detalle vd JOIN lotes l ON l.id = vd.lote_id
                         ORDER BY vd.id LIMIT 1""", uno=True)
        otro = _sql("SELECT id FROM proveedores WHERE id <> %s ORDER BY id LIMIT 1",
                    (linea["proveedor_id"],), uno=True)
        if not linea or not otro:
            raise unittest.SkipTest("Faltan ventas o proveedores (corre seed_demo)")
        cls.linea, cls.proveedor, cls.otro = linea["detalle"], linea["proveedor_id"], otro["id"]
        cls.lote = linea["lote"]

    @classmethod
    def tearDownClass(cls):
        if cls.reclamaciones:
            _sql("DELETE FROM seguimiento_reclamacion WHERE reclamacion_id = ANY(%s)", (cls.reclamaciones,))
            _sql("DELETE FROM reclamacion_devoluciones WHERE reclamacion_id = ANY(%s)", (cls.reclamaciones,))
            _sql("DELETE FROM reclamaciones_proveedor WHERE id = ANY(%s)", (cls.reclamaciones,))
        if cls.devoluciones:
            _sql("DELETE FROM devoluciones WHERE id = ANY(%s)", (cls.devoluciones,))

    def call(self, metodo, ruta, cuerpo=None, token=None):
        return _http(SERVICIO_URL, metodo, BASE + ruta, cuerpo, token or self.analista)

    def _devolucion(self):
        motivo = _sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1", uno=True)["id"]
        dev = _sql("""INSERT INTO devoluciones (venta_detalle_id, motivo_id, descripcion_problema,
                          cantidad_devuelta, estado)
                      VALUES (%s,%s,'Prueba de integracion de proveedores.',1,'solicitada') RETURNING id""",
                   (self.linea, motivo), uno=True)["id"]
        self.devoluciones.append(dev)
        return dev

    def _reclamacion(self, **extra):
        cuerpo = {"proveedor_id": self.proveedor, "asunto": "Prueba de integracion",
                  "descripcion": "Reclamacion creada por la prueba automatica",
                  "monto_reclamado": "1000.00", **extra}
        codigo, r = self.call("POST", "/reclamaciones", cuerpo)
        if codigo == 201:
            self.reclamaciones.append(r["id"])
        return codigo, r

    def test_seguridad(self):
        self.assertEqual(_http(SERVICIO_URL, "GET", BASE)[0], 401)
        for ruta in ("", "/reclamaciones", f"/{self.proveedor}/indicadores"):
            self.assertEqual(self.call("GET", ruta, token=self.cliente)[0], 403, ruta)
            self.assertEqual(self.call("GET", ruta, token=self.inspector)[0], 403, ruta)
        self.assertEqual(self.call("POST", "/reclamaciones", {}, self.cliente)[0], 403)

    def test_listado_e_indicadores(self):
        codigo, lista = self.call("GET", "")
        self.assertEqual(codigo, 200)
        self.assertIn("tasa_promedio_pct", lista)
        fila = lista["datos"][0]
        self.assertIn(fila["semaforo"], ("normal", "atencion", "critico", "sin_datos"))
        codigo, ind = self.call("GET", f"/{self.proveedor}/indicadores")
        self.assertEqual(codigo, 200)
        self.assertEqual(ind["tasa_pct"], round(ind["unidades_devueltas"] * 100.0
                                                / ind["unidades_vendidas"], 2))
        self.assertEqual(self.call("GET", f"/{self.proveedor}/productos")[0], 200)
        self.assertEqual(self.call("GET", "/999999")[0], 404)
        self.assertEqual(self.call("GET", f"/{self.proveedor}/indicadores?desde=2026-13-01")[0], 400)

    def test_reclamacion_exige_origen_y_que_sea_del_proveedor(self):
        self.assertEqual(self._reclamacion()[0], 400)  # sin lote ni devoluciones
        self.assertEqual(self._reclamacion(lote_id=self.lote, proveedor_id=self.otro)[0], 409)
        dev = self._devolucion()
        self.assertEqual(self._reclamacion(devolucion_ids=[dev], proveedor_id=self.otro)[0], 409)
        self.assertEqual(self._reclamacion(devolucion_ids=[999999])[0], 404)

    def test_ciclo_completo_con_cierre_aceptado(self):
        dev = self._devolucion()
        codigo, r = self._reclamacion(devolucion_ids=[dev], lote_id=self.lote)
        self.assertEqual(codigo, 201)
        self.assertTrue(r["folio"].startswith("RCL-"))
        rid = r["id"]
        # La misma devolucion no puede estar en dos reclamaciones abiertas.
        self.assertEqual(self._reclamacion(devolucion_ids=[dev])[0], 409)
        seg = f"/reclamaciones/{rid}/seguimiento"
        # No se puede aceptar algo que el proveedor no ha respondido.
        self.assertEqual(self.call("POST", seg, {"estado": "cerrada", "resolucion": "aceptada",
                                                 "monto_recuperado": "10", "comentario": "Intento"})[0], 409)
        self.assertEqual(self.call("POST", seg, {"estado": "respondida"})[0], 409)  # abierta -> respondida
        for estado in ("enviada", "respondida"):
            self.assertEqual(self.call("POST", seg, {"estado": estado})[0], 200)
        # No se recupera mas de lo reclamado.
        self.assertEqual(self.call("POST", seg, {"estado": "cerrada", "resolucion": "aceptada",
                                                 "monto_recuperado": "1000.01", "comentario": "Demasiado"})[0], 409)
        codigo, cierre = self.call("POST", seg, {"estado": "cerrada", "resolucion": "parcial",
                                                 "monto_recuperado": "600.00", "comentario": "Nota de credito"})
        self.assertEqual((codigo, cierre["estado"]), (200, "cerrada"))
        # Cerrada es definitiva.
        self.assertEqual(self.call("POST", seg, {"estado": "enviada"})[0], 409)
        _, det = self.call("GET", f"/reclamaciones/{rid}")
        self.assertEqual([s["estado_nuevo"] for s in det["seguimiento"]],
                         ["abierta", "enviada", "respondida", "cerrada"])
        self.assertEqual(float(det["monto_recuperado"]), 600.0)
        self.assertEqual(det["devoluciones"][0]["id"], dev)
        # Cerrada ya no bloquea la devolucion para una reclamacion nueva.
        self.assertEqual(self._reclamacion(devolucion_ids=[dev])[0], 201)

    def test_filtros_de_reclamaciones(self):
        self._reclamacion(lote_id=self.lote)
        codigo, lista = self.call("GET", f"/reclamaciones?proveedor_id={self.proveedor}&estado=abierta")
        self.assertEqual(codigo, 200)
        self.assertTrue(all(f["estado"] == "abierta" for f in lista["datos"]))
        self.assertEqual(self.call("GET", "/reclamaciones?estado=inventado")[0], 400)
        self.assertEqual(self.call("GET", "/reclamaciones?vencidas=true")[0], 200)


if __name__ == "__main__":
    unittest.main()
