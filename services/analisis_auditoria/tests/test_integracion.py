"""Integracion real de analisis y auditoria: proyeccion a MongoDB, Pareto con cache en Redis y auditoria.

Sin dobles: el token sale del servicio auth real por HTTP, la peticion va al
contenedor de analisis-auditoria y el efecto se verifica en MongoDB, Redis y PostgreSQL. Las filas que crea
la prueba se borran al terminar, salvo las de la bitacora (es de solo agregar). Solo corre en la VM:

    docker compose run --rm -e INTEGRACION=1 analisis-auditoria python -m pytest -v tests/test_integracion.py

Trazabilidad: RNF-28, RF-23, RF-24, RF-25, RN-09, RN-11, RNF-23.
"""
import json
import os
import time
import unittest
from datetime import date, timedelta
import urllib.error
import urllib.request

import psycopg2
import psycopg2.extras

from shared import mongo
from shared.infra import get_redis

AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8000")
SERVICIO_URL = os.environ.get("ANALISIS_URL", "http://analisis-auditoria:8000")
PREFIJO = "/api/v1"


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
    """Peticion HTTP real; devuelve (codigo, cuerpo_json). No lanza por 4xx."""
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


def _email_de_rol(rol):
    fila = _sql("""SELECT u.email FROM usuarios u JOIN roles r ON r.id = u.rol_id
                    WHERE r.nombre = %s AND u.estado = 'activo' AND u.eliminado_en IS NULL
                    ORDER BY u.id LIMIT 1""", (rol,), uno=True)
    if not fila:
        raise unittest.SkipTest(f"No hay usuario activo con rol {rol} (corre seed_demo)")
    return fila["email"]


def _login(rol):
    """Login real; la contrasena viene de PASSWORD_DEMO, nunca del repositorio."""
    codigo, cuerpo = _http(AUTH_URL, "POST", "/api/v1/auth/login",
                           {"email": _email_de_rol(rol), "password": os.environ["PASSWORD_DEMO"]})
    if codigo != 200:
        raise AssertionError(f"login de {rol} respondio {codigo}")
    return cuerpo["access_token"]


def _logout(token):
    _http(AUTH_URL, "POST", "/api/v1/auth/logout", token=token)


def _linea_disponible(refrigerado=None):
    """Una linea de venta con al menos 1 unidad sin devolver."""
    filtro = "" if refrigerado is None else (
        "AND p.clasificacion_temperatura = " + ("'refrigerado'" if refrigerado else "'no_refrigerado'"))
    fila = _sql(f"""
        SELECT vd.id FROM venta_detalle vd
          JOIN ventas v ON v.id = vd.venta_id
          JOIN lotes l ON l.id = vd.lote_id JOIN productos p ON p.id = l.producto_id
         WHERE v.eliminado_en IS NULL {filtro}
           AND vd.cantidad - COALESCE((SELECT SUM(d.cantidad_devuelta) FROM devoluciones d
                WHERE d.venta_detalle_id = vd.id AND d.eliminado_en IS NULL
                  AND d.estado <> 'rechazada'), 0) >= 1
         ORDER BY vd.id LIMIT 1""", uno=True)
    if not fila:
        raise unittest.SkipTest("No hay una linea de venta con unidades por devolver")
    return fila["id"]


def _sembrar_devolucion(estado, refrigerado=None):
    """Inserta por SQL una devolucion en el estado pedido (el folio lo pone la
    base, RN-02). Asi cada servicio se prueba aislado de los demas."""
    motivo = _sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1", uno=True)["id"]
    return _sql("""INSERT INTO devoluciones (venta_detalle_id, motivo_id, descripcion_problema,
                                             cantidad_devuelta, estado)
                   VALUES (%s, %s, 'Prueba de integracion del servicio.', 1, %s)
                   RETURNING id, folio_devolucion""",
                (_linea_disponible(refrigerado), motivo, estado), uno=True)


def _borrar_devoluciones(ids):
    if not ids:
        return
    ids = tuple(ids)
    for paso in (
        "DELETE FROM notificaciones WHERE devolucion_id IN %s",
        "DELETE FROM evidencias WHERE devolucion_id IN %s",
        "DELETE FROM inventario_recuperado WHERE disposicion_id IN "
        "(SELECT id FROM disposiciones WHERE devolucion_id IN %s)",
        "DELETE FROM disposiciones WHERE devolucion_id IN %s",
        "DELETE FROM inspecciones_ref WHERE devolucion_id IN %s",
        "DELETE FROM recepciones WHERE devolucion_id IN %s",
        "DELETE FROM recolecciones WHERE devolucion_id IN %s",
        "DELETE FROM costos WHERE devolucion_id IN %s",
        "DELETE FROM reembolsos WHERE devolucion_id IN %s",
        "DELETE FROM devoluciones WHERE id IN %s",
    ):
        try:
            _sql(paso, (ids,))
        except Exception:  # noqa: BLE001 - limpieza de mejor esfuerzo
            pass

SKIP = unittest.skipUnless(os.environ.get("INTEGRACION") == "1",
                         "Solo en la VM: INTEGRACION=1 y el entorno levantado")


def _analisis_retirado():
    """El /health dice si el analisis obsoleto esta retirado (ANALISIS_HABILITADO=false)."""
    codigo, cuerpo = _http(SERVICIO_URL, "GET", "/health")
    return codigo == 200 and cuerpo.get("analisis") == "retirado"


@SKIP
class IntegracionAnalisis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analista = _login("Analista de Devoluciones")
        cls.cliente = _login("Cliente")

    @classmethod
    def tearDownClass(cls):
        _logout(cls.analista)
        _logout(cls.cliente)

    def _exigir_analisis_habilitado(self):
        if _analisis_retirado():
            self.skipTest("El analisis esta retirado (ANALISIS_HABILITADO=false); ver IntegracionCorte")

    def test_sincronizar_proyecta_postgres_en_mongo_sin_modificar_postgres(self):
        self._exigir_analisis_habilitado()
        antes = _sql("SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS m FROM devoluciones "
                     "WHERE eliminado_en IS NULL", uno=True)
        codigo, resp = _http(SERVICIO_URL, "POST", PREFIJO + "/analisis/sincronizar",
                             token=self.analista)
        self.assertEqual(codigo, 200, resp)
        self.assertEqual(resp["casos_sincronizados"], antes["n"])
        vigentes = mongo.get_mongo().resultados_analisis.count_documents(
            {"tipo_analisis": "snapshot_devolucion", "vigente": True})
        self.assertEqual(vigentes, antes["n"])
        despues = _sql("SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS m FROM devoluciones "
                       "WHERE eliminado_en IS NULL", uno=True)
        self.assertEqual(antes, despues)  # solo lectura sobre PostgreSQL

    def test_pareto_primero_calcula_y_luego_sale_del_cache_con_ttl(self):
        self._exigir_analisis_habilitado()
        codigo, _ = _http(SERVICIO_URL, "POST", PREFIJO + "/analisis/sincronizar", token=self.analista)
        self.assertEqual(codigo, 200)  # sube la version del cache: la primera lectura es miss
        ruta = PREFIJO + "/analisis/pareto?dimension=motivo&medida=frecuencia"
        _, primera = _http(SERVICIO_URL, "GET", ruta, token=self.analista)
        _, segunda = _http(SERVICIO_URL, "GET", ruta, token=self.analista)
        self.assertEqual(primera["cache"], "miss")
        self.assertEqual(segunda["cache"], "hit")
        self.assertEqual(primera["categorias"], segunda["categorias"])
        r = get_redis()
        claves = list(r.scan_iter("devoluciones:cache:causas:*"))
        self.assertTrue(claves)
        self.assertTrue(all(0 < r.ttl(k) <= 600 for k in claves))
        # El calculo se conserva en MongoDB para trazabilidad.
        self.assertTrue(mongo.get_mongo().resultados_analisis.find_one({"tipo_analisis": "pareto"}))
        if primera["categorias"]:
            acumulados = [c["porcentaje_acumulado"] for c in primera["categorias"]]
            self.assertEqual(acumulados, sorted(acumulados))
            self.assertAlmostEqual(acumulados[-1], 100.0, places=1)

    def test_clasificar_motivo_solo_sugiere(self):  # RN-11
        self._exigir_analisis_habilitado()
        antes = _sql("SELECT COUNT(*) AS n FROM devoluciones", uno=True)["n"]
        codigo, resp = _http(SERVICIO_URL, "POST", PREFIJO + "/analisis/clasificar-motivo",
                             {"descripcion": "El producto llego caducado y con mal olor"}, self.cliente)
        self.assertEqual(codigo, 200)
        self.assertTrue(resp["requiere_confirmacion"])
        self.assertEqual(antes, _sql("SELECT COUNT(*) AS n FROM devoluciones", uno=True)["n"])

    def test_auditoria_y_eventos_solo_para_analista_o_admin(self):
        codigo, cuerpo = _http(SERVICIO_URL, "GET", PREFIJO + "/auditoria?por_pagina=5",
                               token=self.analista)
        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo["paginacion"]["total"],
                         _sql("SELECT COUNT(*) AS n FROM bitacora", uno=True)["n"])
        codigo, _ = _http(SERVICIO_URL, "GET", PREFIJO + "/auditoria", token=self.cliente)
        self.assertEqual(codigo, 403)
        codigo, _ = _http(SERVICIO_URL, "GET", PREFIJO + "/analisis/eventos", token=self.cliente)
        # Con el analisis retirado la ruta ni siquiera pide token: responde 410.
        self.assertEqual(codigo, 410 if _analisis_retirado() else 403)


@SKIP
class IntegracionAuditoria(unittest.TestCase):
    """La auditoria separada y la proteccion de la bitacora (migracion 045).

    Deja unos pocos registros 'prueba_integracion_auditoria' en la bitacora: es
    justamente la propiedad que se prueba, no se pueden borrar. Nunca ejecuta
    TRUNCATE; se comprueba que el trigger exista y este activo.
    Trazabilidad: RF-30, RN-12, RN-13, RNF-23.
    """

    @classmethod
    def setUpClass(cls):
        cls.analista = _login("Analista de Devoluciones")
        cls.cliente = _login("Cliente")
        cls.entidad_id = int(time.time()) % 2000000000
        cls.fila = _sql("""INSERT INTO bitacora (accion, entidad, entidad_id, detalle, correlation_id)
                           VALUES ('prueba_integracion_auditoria', 'pruebas', %s, 'registro de prueba', 'cid-prueba-aud')
                           RETURNING id""", (cls.entidad_id,), uno=True)["id"]

    @classmethod
    def tearDownClass(cls):
        _logout(cls.analista)
        _logout(cls.cliente)

    def get(self, ruta, token=None):
        return _http(SERVICIO_URL, "GET", PREFIJO + ruta, token=token or self.analista)

    def test_la_base_no_deja_modificar_ni_borrar_la_bitacora(self):
        for sentencia in ("UPDATE bitacora SET detalle = 'alterado' WHERE id = %s",
                          "UPDATE bitacora SET accion = 'otra' WHERE id = %s",
                          "UPDATE bitacora SET usuario_id = 1 WHERE id = %s",
                          "DELETE FROM bitacora WHERE id = %s"):
            with self.assertRaises(psycopg2.Error, msg=sentencia) as err:
                _sql(sentencia, (self.fila,))
            self.assertIn("solo agregar", str(err.exception), sentencia)
        intacta = _sql("SELECT accion, detalle FROM bitacora WHERE id = %s", (self.fila,), uno=True)
        self.assertEqual((intacta["accion"], intacta["detalle"]), ("prueba_integracion_auditoria", "registro de prueba"))

    def test_borrar_a_una_persona_anonimiza_sin_romperse(self):
        """La unica excepcion: ON DELETE SET NULL de usuarios solo cambia usuario_id."""
        rol = _sql("SELECT id FROM roles ORDER BY id LIMIT 1", uno=True)["id"]
        usuario = _sql("""INSERT INTO usuarios (nombre, email, password_hash, rol_id)
                          VALUES ('Prueba auditoria', %s, 'x', %s) RETURNING id""",
                       (f"auditoria-{self.entidad_id}@prueba.mx", rol), uno=True)["id"]
        fila = _sql("""INSERT INTO bitacora (usuario_id, accion, entidad, detalle)
                       VALUES (%s, 'prueba_integracion_auditoria', 'pruebas', 'de una persona que se borra')
                       RETURNING id""", (usuario,), uno=True)["id"]
        _sql("DELETE FROM usuarios WHERE id = %s", (usuario,))
        despues = _sql("SELECT usuario_id, accion, detalle FROM bitacora WHERE id = %s", (fila,), uno=True)
        self.assertEqual((despues["usuario_id"], despues["accion"], despues["detalle"]),
                         (None, "prueba_integracion_auditoria", "de una persona que se borra"))

    def test_estado_dice_que_la_proteccion_esta_completa(self):
        triggers = {f["tgname"] for f in _sql("SELECT tgname FROM pg_trigger WHERE tgrelid = 'bitacora'::regclass "
                                              "AND NOT tgisinternal AND tgenabled IN ('O', 'A')")}
        self.assertLessEqual({"trg_bitacora_inmutable", "trg_bitacora_sin_truncate"}, triggers)
        codigo, e = self.get("/auditoria/estado")
        self.assertEqual(codigo, 200)
        self.assertTrue(e["proteccion"]["completa"])
        self.assertEqual(e["registros"], _sql("SELECT COUNT(*) AS n FROM bitacora", uno=True)["n"])
        self.assertEqual(self.get("/auditoria/estado", self.cliente)[0], 403)

    def test_filtros_nuevos_de_la_bitacora(self):
        base = f"/auditoria?accion=prueba_integracion_auditoria&entidad_id={self.entidad_id}"
        codigo, r = self.get(base)
        self.assertEqual((codigo, r["paginacion"]["total"]), (200, 1))
        self.assertEqual(r["datos"][0]["id"], self.fila)
        hoy = date.today()
        manana, ayer = hoy + timedelta(days=1), hoy - timedelta(days=1)
        self.assertEqual(self.get(f"{base}&desde={hoy}&hasta={hoy}")[1]["paginacion"]["total"], 1)     # el dia completo
        self.assertEqual(self.get(f"{base}&desde={manana}")[1]["paginacion"]["total"], 0)
        self.assertEqual(self.get(f"{base}&hasta={ayer}")[1]["paginacion"]["total"], 0)
        self.assertEqual(self.get(f"{base}&usuario_id=2147483647")[1]["paginacion"]["total"], 0)
        self.assertEqual(self.get("/auditoria?desde=ayer")[0], 400)
        self.assertEqual(self.get("/auditoria?entidad_id=abc")[0], 400)

    def test_inyeccion_en_un_filtro_no_hace_nada(self):
        antes = _sql("SELECT COUNT(*) AS n FROM bitacora", uno=True)["n"]
        codigo, r = self.get("/auditoria?accion=x%27%3B%20DROP%20TABLE%20bitacora--")
        self.assertEqual((codigo, r["paginacion"]["total"]), (200, 0))
        self.assertGreaterEqual(_sql("SELECT COUNT(*) AS n FROM bitacora", uno=True)["n"], antes)

    def test_eventos_en_la_ruta_de_auditoria_y_el_alias_obsoleto_coinciden(self):
        codigo, nuevo = self.get("/auditoria/eventos?por_pagina=5")
        self.assertEqual(codigo, 200)
        self.assertTrue(all("datos" not in e for e in nuevo["datos"]))                 # RNF-16
        peticion = urllib.request.Request(SERVICIO_URL + PREFIJO + "/analisis/eventos?por_pagina=5",
                                          headers={"Authorization": f"Bearer {self.analista}"})
        try:
            with urllib.request.urlopen(peticion, timeout=15) as resp:
                alias, cabeceras = json.loads(resp.read()), resp.headers
        except urllib.error.HTTPError as exc:
            if exc.code == 410:
                self.skipTest("El analisis esta retirado (ANALISIS_HABILITADO=false): el alias ya no existe")
            raise
        self.assertEqual(alias["paginacion"]["total"], nuevo["paginacion"]["total"])
        self.assertEqual(cabeceras["Deprecation"], "true")
        self.assertIn("/api/v1/auditoria/eventos", cabeceras["Link"])


@SKIP
class IntegracionCorte(unittest.TestCase):
    """El corte: con ANALISIS_HABILITADO=false las rutas de analisis responden 410 y la auditoria sigue.

    Se salta si el analisis aun esta habilitado. Trazabilidad: RN-12, RNF-23 y la correccion del profe
    de separar la auditoria del analisis (docs/MIGRACION_ANALISIS_8008.md, etapa 3).
    """
    RUTAS = (("POST", "/analisis/clasificar-motivo", "clasificacion-motivos"),
             ("GET", "/analisis/alertas-fraude", "reportes-analitica"),
             ("GET", "/analisis/pareto?dimension=motivo", "reportes-analitica"),
             ("POST", "/analisis/sincronizar", None),
             ("GET", "/analisis/resumen", None),
             ("GET", "/analisis/eventos", "/api/v1/auditoria/eventos"))

    @classmethod
    def setUpClass(cls):
        if not _analisis_retirado():
            raise unittest.SkipTest("El analisis sigue habilitado: no hay corte que comprobar")
        cls.analista = _login("Analista de Devoluciones")

    @classmethod
    def tearDownClass(cls):
        _logout(cls.analista)

    def test_health_dice_que_el_analisis_esta_retirado(self):
        codigo, cuerpo = _http(SERVICIO_URL, "GET", "/health")
        self.assertEqual((codigo, cuerpo["analisis"]), (200, "retirado"))

    def test_cada_ruta_del_analisis_responde_410_con_su_sucesor_aun_sin_token(self):
        for metodo, ruta, sucesor in self.RUTAS:
            codigo, cuerpo = _http(SERVICIO_URL, metodo, PREFIJO + ruta, {} if metodo == "POST" else None)
            self.assertEqual(codigo, 410, ruta)
            self.assertEqual(cuerpo["error"]["tipo"], "servicio_movido", ruta)
            sucesores = " ".join(cuerpo["error"]["detalles"].values())
            if sucesor:
                self.assertIn(sucesor, sucesores, ruta)

    def test_la_auditoria_sigue_funcionando(self):
        for ruta in ("/auditoria?por_pagina=3", "/auditoria/eventos?por_pagina=3", "/auditoria/estado"):
            codigo, _ = _http(SERVICIO_URL, "GET", PREFIJO + ruta, token=self.analista)
            self.assertEqual(codigo, 200, ruta)
        codigo, _ = _http(SERVICIO_URL, "GET", PREFIJO + "/auditoria")
        self.assertEqual(codigo, 401)            # sin token sigue pidiendo credenciales


if __name__ == "__main__":
    unittest.main()
