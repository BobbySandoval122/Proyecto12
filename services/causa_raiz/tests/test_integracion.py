"""Integracion real de causa-raiz contra la VM (PostgreSQL, Redis y auth reales).

    docker compose run --rm -e INTEGRACION=1 -e PASSWORD_DEMO=... causa-raiz \
        python -m pytest -v tests/test_integracion.py

Crea su propio lote con ventas y devoluciones fechadas hacia atras (para que la
medicion de eficacia tenga cohortes maduras) y lo borra todo al terminar.
Recorre los 9 pasos del flujo del profe, incluido el cierre por un supervisor
con reconfirmacion de contrasena.
Trazabilidad: RF-23, RF-24, RN-09, RN-12, RN-13, RNF-09, RNF-28.
"""
import json
import os
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

import psycopg2
import psycopg2.extras

AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8000")
SERVICIO_URL = os.environ.get("CAUSA_RAIZ_URL", "http://causa-raiz:8000")
BASE = "/api/v1/causa-raiz"
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


def _http(base, metodo, ruta, cuerpo=None, token=None, extra=None):
    cabeceras = {"Content-Type": "application/json", **(extra or {})}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(
        base + ruta, method=metodo, headers=cabeceras,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(peticion, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        crudo = exc.read()
        try:
            return exc.code, json.loads(crudo)
        except ValueError:
            return exc.code, None


def _login(rol):
    fila = _sql("""SELECT u.id, u.email FROM usuarios u JOIN roles r ON r.id = u.rol_id
                    WHERE r.nombre = %s AND u.estado = 'activo' AND u.eliminado_en IS NULL
                    ORDER BY u.id LIMIT 1""", (rol,), uno=True)
    if not fila:
        raise unittest.SkipTest(f"No hay usuario activo con rol {rol} (corre seed_demo)")
    codigo, cuerpo = _http(AUTH_URL, "POST", "/api/v1/auth/login",
                           {"email": fila["email"], "password": os.environ["PASSWORD_DEMO"]})
    if codigo != 200:
        raise AssertionError(f"login de {rol} respondio {codigo}")
    return fila["id"], cuerpo["access_token"]


@SKIP
class IntegracionCausaRaiz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_id, cls.admin = _login("Administrador")
        cls.analista_id, cls.analista = _login("Analista de Devoluciones")
        cls.supervisor_id, cls.supervisor = _login("Supervisor")
        cls.cliente_id, cls.cliente = _login("Cliente")
        cls.coordinador_id, _ = _login("Coordinador de Logistica")
        cls.investigaciones, cls.lotes_extra, cls.hoy = [], [], date.today()
        producto = _sql("SELECT id, proveedor_id FROM productos ORDER BY id LIMIT 1", uno=True)
        tienda = _sql("SELECT id FROM tiendas ORDER BY id LIMIT 1", uno=True)["id"]
        motivo = _sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1", uno=True)["id"]
        cls.lote = _sql("""INSERT INTO lotes (producto_id, proveedor_id, numero_lote)
                           VALUES (%s,%s,'L-TEST-CAUSA') RETURNING id""",
                        (producto["id"], producto["proveedor_id"]), uno=True)["id"]
        cls.ventas, cls.devoluciones, cls.detalles = [], [], []

        def venta(dias_atras, devueltas_por_caso, casos):
            v = _sql("""INSERT INTO ventas (folio_venta, cliente_id, tienda_id, fecha_venta)
                        VALUES (%s,%s,%s,%s) RETURNING id""",
                     (f"VTA-CRTEST-{dias_atras}", cls.cliente_id, tienda,
                      cls.hoy - timedelta(days=dias_atras)), uno=True)["id"]
            cls.ventas.append(v)
            d = _sql("""INSERT INTO venta_detalle (venta_id, lote_id, cantidad, precio_unitario)
                        VALUES (%s,%s,50,10) RETURNING id""", (v, cls.lote), uno=True)["id"]
            cls.detalles.append(d)
            for _ in range(casos):
                cls.devoluciones.append(_sql(
                    """INSERT INTO devoluciones (venta_detalle_id, motivo_id, descripcion_problema,
                           cantidad_devuelta, estado) VALUES (%s,%s,'Prueba de causa raiz.',%s,'solicitada')
                       RETURNING id""", (d, motivo, devueltas_por_caso), uno=True)["id"])
        # Antes de implementar (hace 60 dias): 50 vendidas, 15 devueltas = 30 %.
        venta(100, 5, 3)
        # Despues (la accion se implementa hace 60 dias; estas ventas ya maduraron): 10 %.
        venta(50, 5, 1)

    @classmethod
    def tearDownClass(cls):
        for iid in cls.investigaciones:
            _sql("DELETE FROM mediciones_eficacia WHERE accion_id IN (SELECT id FROM acciones_capa WHERE investigacion_id=%s)", (iid,))
            _sql("DELETE FROM acciones_capa WHERE investigacion_id=%s", (iid,))
            _sql("DELETE FROM evidencias_investigacion WHERE investigacion_id=%s", (iid,))
            _sql("DELETE FROM hipotesis WHERE investigacion_id=%s AND padre_id IS NOT NULL", (iid,))
            _sql("DELETE FROM hipotesis WHERE investigacion_id=%s", (iid,))
            _sql("DELETE FROM seguimiento_investigacion WHERE investigacion_id=%s", (iid,))
            _sql("DELETE FROM investigaciones WHERE id=%s", (iid,))
        _sql("DELETE FROM alertas_patron WHERE dimension='lote' AND referencia_id=%s", (cls.lote,))
        _sql("DELETE FROM devoluciones WHERE id = ANY(%s)", (cls.devoluciones,))
        _sql("DELETE FROM venta_detalle WHERE id = ANY(%s)", (cls.detalles,))
        _sql("DELETE FROM ventas WHERE id = ANY(%s)", (cls.ventas,))
        _sql("DELETE FROM lotes WHERE id=%s", (cls.lote,))
        for extra in cls.lotes_extra:
            _sql("DELETE FROM lotes WHERE id=%s", (extra,))

    def call(self, metodo, ruta, cuerpo=None, token=None, extra=None):
        return _http(SERVICIO_URL, metodo, BASE + ruta, cuerpo, token or self.analista, extra)

    def _alerta_nueva(self):
        """La deteccion puede haber abierto ya una alerta para este lote; se parte de cero."""
        _sql("DELETE FROM alertas_patron WHERE dimension='lote' AND referencia_id=%s", (self.lote,))
        return _sql("""INSERT INTO alertas_patron (dimension, referencia_id, etiqueta, unidades_vendidas,
                           unidades_devueltas, casos, tasa_pct, tasa_promedio_pct, veces_promedio)
                       VALUES ('lote', %s, 'L-TEST-CAUSA', 100, 20, 4, 20, 5, 4) RETURNING id""",
                    (self.lote,), uno=True)["id"]

    def test_seguridad(self):
        self.assertEqual(_http(SERVICIO_URL, "GET", BASE + "/investigaciones")[0], 401)
        for ruta in ("/investigaciones", "/alertas"):
            self.assertEqual(self.call("GET", ruta, token=self.cliente)[0], 403, ruta)
        self.assertEqual(self.call("POST", "/alertas/detectar", {}, self.cliente)[0], 403)
        # Un analista no cierra investigaciones: es del Supervisor.
        self.assertEqual(self.call("POST", "/investigaciones/1/cierre", {"comentario": "Intento de cierre"})[0], 403)

    def test_deteccion_y_alerta(self):
        codigo, r = self.call("POST", "/alertas/detectar", {})
        self.assertEqual(codigo, 200)
        self.assertIn("alertas_nuevas", r)
        # Repetirla no duplica las alertas abiertas.
        codigo, r2 = self.call("POST", "/alertas/detectar", {})
        self.assertEqual((codigo, r2["alertas_nuevas"]), (200, 0))
        # Una alerta propuesta puede descartarse con explicacion, y solo una vez.
        alerta = self._alerta_nueva()
        self.assertEqual(self.call("POST", f"/alertas/{alerta}/descartar", {"comentario": "corto"})[0], 400)
        self.assertEqual(self.call("POST", f"/alertas/{alerta}/descartar",
                                   {"comentario": "Fue un lote de prueba interna"})[0], 200)
        self.assertEqual(self.call("POST", f"/alertas/{alerta}/descartar",
                                   {"comentario": "Fue un lote de prueba interna"})[0], 409)

    def test_flujo_completo_de_nueve_pasos(self):
        # Pasos 2-3: una alerta propone; una persona abre la investigacion.
        alerta = self._alerta_nueva()
        codigo, inv = self.call("POST", f"/alertas/{alerta}/investigar",
                                {"titulo": "Lote de prueba tibio", "descripcion": "Devoluciones recurrentes del lote"})
        self.assertEqual(codigo, 201)
        iid = inv["id"]
        self.investigaciones.append(iid)
        self.assertEqual(inv["linea_base"]["unidades_vendidas"], 100)
        self.assertEqual(inv["linea_base"]["tasa_pct"], 20.0)
        self.assertEqual(_sql("SELECT estado FROM alertas_patron WHERE id=%s", (alerta,), uno=True)["estado"],
                         "investigando")
        # Un objeto no puede tener dos investigaciones sin cerrar.
        self.assertEqual(self.call("POST", "/investigaciones", {"dimension": "lote", "referencia_id": self.lote,
                                   "titulo": "Otra investigacion", "descripcion": "Duplicada a proposito"})[0], 409)
        # No se salta pasos: concluir sin verificar.
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/conclusion",
                                   {"conclusion": "inconclusa", "justificacion": "Sin verificacion previa"})[0], 409)
        # Paso 3: evidencia. Una devolucion de otro objeto no sirve.
        ajena = _sql("""SELECT d.id FROM devoluciones d JOIN venta_detalle vd ON vd.id = d.venta_detalle_id
                         WHERE vd.lote_id <> %s ORDER BY d.id LIMIT 1""", (self.lote,), uno=True)
        if ajena:
            self.assertEqual(self.call("POST", f"/investigaciones/{iid}/evidencias",
                {"tipo": "devolucion", "devolucion_id": ajena["id"], "descripcion": "Caso de otro lote"})[0], 409)
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/evidencias",
            {"tipo": "devolucion", "devolucion_id": self.devoluciones[0], "descripcion": "Producto llego tibio"})[0], 201)
        # Paso 4: cinco porques (la sexta continuacion no cabe) e Ishikawa.
        padre, ids = None, []
        for nivel in range(1, 6):
            cuerpo = {"tipo": "cinco_porques", "descripcion": f"Porque numero {nivel} del problema"}
            if padre:
                cuerpo["padre_id"] = padre
            codigo, h = self.call("POST", f"/investigaciones/{iid}/hipotesis", cuerpo)
            self.assertEqual((codigo, h["nivel"]), (201, nivel))
            padre = h["id"]
            ids.append(padre)
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/hipotesis",
            {"tipo": "cinco_porques", "padre_id": padre, "descripcion": "Un sexto porque que no cabe"})[0], 409)
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/hipotesis",
            {"tipo": "cinco_porques", "padre_id": ids[0], "descripcion": "Una rama del primer porque"})[0], 409)
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/hipotesis",
            {"tipo": "ishikawa", "categoria_ishikawa": "medio_ambiente",
             "descripcion": "Temperatura del camion durante el traslado"})[0], 201)
        # Paso 5: verificar. Confirmar sin hipotesis verificada se rechaza.
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/verificacion", {})[1]["estado"], "en_verificacion")
        confirmar = {"conclusion": "causa_confirmada", "causa_raiz": "Falla de refrigeracion del camion",
                     "justificacion": "Los registros de temperatura lo demuestran"}
        codigo, err = self.call("POST", f"/investigaciones/{iid}/conclusion", confirmar)
        self.assertEqual((codigo, err["error"]["tipo"]), (409, "sin_hipotesis_verificada"))
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/hipotesis/{ids[-1]}/verificacion",
            {"resultado": "verificada", "resultado_verificacion": "El registro de temperatura lo confirma"})[0], 200)
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/hipotesis/{ids[-1]}/verificacion",
            {"resultado": "descartada", "resultado_verificacion": "Intento de cambiar el resultado"})[0], 409)
        # Paso 6: causa confirmada. Ya no se agrega evidencia.
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/conclusion", confirmar)[0], 200)
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/evidencias",
            {"tipo": "nota", "descripcion": "Evidencia tardia que no debe entrar"})[0], 409)
        # Paso 7: CAPA con responsable y fecha. El cliente no puede ser responsable.
        manana = (self.hoy + timedelta(days=30)).isoformat()
        capa = {"tipo": "correctiva", "descripcion": "Cambiar el contrato de transporte refrigerado",
                "responsable_id": self.coordinador_id, "fecha_compromiso": manana}
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/acciones",
                                   {**capa, "responsable_id": self.cliente_id})[0], 409)
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/acciones", {**capa, "fecha_compromiso": "2020-01-01"})[0], 400)
        codigo, a = self.call("POST", f"/investigaciones/{iid}/acciones", capa)
        self.assertEqual(codigo, 201)
        aid = a["id"]
        self.assertEqual(self.call("GET", f"/investigaciones/{iid}")[1]["estado"], "en_accion")
        # Medir antes de implementar no tiene sentido.
        self.assertEqual(self.call("POST", f"/acciones/{aid}/mediciones", {})[0], 409)
        self.assertEqual(self.call("POST", f"/acciones/{aid}/estado", {"estado": "implementada"})[0], 409)
        self.assertEqual(self.call("POST", f"/acciones/{aid}/estado", {"estado": "en_curso"})[0], 200)
        # Cerrar con la accion pendiente tampoco.
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/cierre", {"comentario": "Cierre prematuro de prueba"},
                                   self.supervisor)[0], 409)
        implementada = (self.hoy - timedelta(days=60)).isoformat()
        self.assertEqual(self.call("POST", f"/acciones/{aid}/estado",
                                   {"estado": "implementada", "fecha_implementacion": implementada})[0], 200)
        # Paso 8: medir. 30 % antes, 10 % despues: reduccion de 66.67 %, efectiva.
        codigo, m = self.call("POST", f"/acciones/{aid}/mediciones", {})
        self.assertEqual(codigo, 201)
        self.assertEqual((m["antes"]["unidades_vendidas"], m["antes"]["unidades_devueltas"]), (50, 15))
        self.assertEqual((m["despues"]["unidades_vendidas"], m["despues"]["unidades_devueltas"]), (50, 5))
        self.assertEqual((m["antes"]["tasa_pct"], m["despues"]["tasa_pct"]), (30.0, 10.0))
        self.assertEqual((m["reduccion_pct"], m["veredicto"]), (66.67, "efectiva"))
        self.assertEqual(self.call("GET", f"/investigaciones/{iid}")[1]["estado"], "en_medicion")
        # Una ventana que deja sin ventas a 'antes' no puede dar veredicto de eficacia.
        codigo, sd = self.call("POST", f"/acciones/{aid}/mediciones", {"ventana_antes_dias": 7})
        self.assertEqual((codigo, sd["veredicto"]), (201, "sin_datos"))
        self.assertEqual(self.call("POST", f"/acciones/{aid}/mediciones", {"ventana_antes_dias": 90})[1]["veredicto"], "efectiva")
        # Paso 9: lo cierra un supervisor distinto del analista, reconfirmando su contrasena.
        cierre = {"comentario": "Las acciones funcionaron y se midio la mejora"}
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/cierre", cierre, self.supervisor)[1]["error"]["tipo"],
                         "autorizacion_operacion_requerida")
        _, permiso = _http(AUTH_URL, "POST", "/api/v1/auth/autorizar-operacion",
                           {"operacion": "cerrar_investigacion", "recurso_id": str(iid),
                            "password": os.environ["PASSWORD_DEMO"]}, self.supervisor)
        codigo, cerrada = self.call("POST", f"/investigaciones/{iid}/cierre", cierre, self.supervisor,
                                    {"X-Autorizacion-Operacion": permiso["token_operacion"]})
        self.assertEqual((codigo, cerrada["veredicto_final"]), (200, "efectiva"))
        # Cerrada es definitiva; el permiso ya se uso.
        self.assertEqual(self.call("POST", f"/investigaciones/{iid}/cierre", cierre, self.supervisor,
                                   {"X-Autorizacion-Operacion": permiso["token_operacion"]})[0], 409)
        detalle = self.call("GET", f"/investigaciones/{iid}")[1]
        self.assertEqual([s["estado_nuevo"] for s in detalle["seguimiento"]],
                         ["abierta", "en_verificacion", "concluida", "en_accion", "en_medicion", "cerrada"])
        self.assertEqual(detalle["cerrada_por"], self.supervisor_id)

    def test_el_responsable_solo_ve_y_mueve_sus_acciones(self):
        # Un objeto no admite dos investigaciones abiertas (409): este caso usa su propio lote para no
        # chocar con la investigacion que abre el flujo de nueve pasos sobre self.lote.
        producto = _sql("SELECT id, proveedor_id FROM productos ORDER BY id LIMIT 1", uno=True)
        lote_b = _sql("""INSERT INTO lotes (producto_id, proveedor_id, numero_lote)
                         VALUES (%s,%s,'L-TEST-CAUSA-B') RETURNING id""",
                      (producto["id"], producto["proveedor_id"]), uno=True)["id"]
        self.lotes_extra.append(lote_b)
        codigo, inv = self.call("POST", "/investigaciones", {"dimension": "lote", "referencia_id": lote_b,
                                "titulo": "Acciones por responsable", "descripcion": "Prueba de permisos de CAPA"})
        self.assertEqual(codigo, 201)
        iid = inv["id"]
        self.investigaciones.append(iid)
        for cuerpo in ({"tipo": "libre", "descripcion": "Hipotesis para poder verificar"},):
            self.call("POST", f"/investigaciones/{iid}/hipotesis", cuerpo)
        self.call("POST", f"/investigaciones/{iid}/evidencias", {"tipo": "nota", "descripcion": "Nota de prueba"})
        self.call("POST", f"/investigaciones/{iid}/verificacion", {})
        hid = self.call("GET", f"/investigaciones/{iid}")[1]["hipotesis"][0]["id"]
        self.call("POST", f"/investigaciones/{iid}/hipotesis/{hid}/verificacion",
                  {"resultado": "verificada", "resultado_verificacion": "Verificada con datos de prueba"})
        self.call("POST", f"/investigaciones/{iid}/conclusion", {"conclusion": "causa_confirmada",
                  "causa_raiz": "Causa de prueba confirmada", "justificacion": "Evidencia de prueba suficiente"})
        _, a = self.call("POST", f"/investigaciones/{iid}/acciones", {
            "tipo": "preventiva", "descripcion": "Capacitar al personal de recepcion",
            "responsable_id": self.coordinador_id, "fecha_compromiso": (self.hoy + timedelta(days=10)).isoformat()})
        # El analista (operador) la ve; un cliente ni siquiera sabe que existe.
        self.assertEqual(self.call("GET", f"/acciones/{a['id']}")[0], 200)
        self.assertEqual(self.call("GET", f"/acciones/{a['id']}", token=self.cliente)[0], 403)
        _, otro = _login("Inspector")
        self.assertEqual(self.call("GET", f"/acciones/{a['id']}", token=otro)[0], 404)
        self.assertEqual(self.call("POST", f"/acciones/{a['id']}/estado", {"estado": "en_curso"}, otro)[0], 404)
        # Cancelar una accion exige explicar por que.
        self.assertEqual(self.call("POST", f"/acciones/{a['id']}/estado", {"estado": "cancelada"})[0], 400)
        self.assertEqual(self.call("POST", f"/acciones/{a['id']}/estado",
                                   {"estado": "cancelada", "comentario": "Ya no aplica en esta prueba"})[0], 200)


if __name__ == "__main__":
    unittest.main()
