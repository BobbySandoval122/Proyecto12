"""Integracion real de clasificacion-motivos contra la VM (PostgreSQL, Redis y auth reales).

    docker compose run --rm -e INTEGRACION=1 -e PASSWORD_DEMO=... clasificacion-motivos \
        python -m pytest -v tests/test_integracion.py

Crea sus propios submotivos y devoluciones y los borra al terminar.
Trazabilidad: RF-22, RN-11, RN-12, RN-13, RNF-09, RNF-28.
"""
import json
import os
import unittest
import urllib.error
import urllib.request

import psycopg2
import psycopg2.extras

AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8000")
SERVICIO_URL = os.environ.get("CLASIFICACION_URL", "http://clasificacion-motivos:8000")
BASE = "/api/v1/motivos"
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
class IntegracionClasificacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = _login("Administrador")
        cls.analista = _login("Analista de Devoluciones")
        cls.inspector = _login("Inspector")
        cls.cliente = _login("Cliente")
        cls.codigo = "prueba_integracion"
        cls.devoluciones, cls.limpiar_codigos = [], [cls.codigo]

    @classmethod
    def tearDownClass(cls):
        if cls.devoluciones:
            _sql("DELETE FROM clasificaciones_motivo WHERE devolucion_id = ANY(%s)", (cls.devoluciones,))
            _sql("DELETE FROM devoluciones WHERE id = ANY(%s)", (cls.devoluciones,))
        _sql("DELETE FROM submotivos_versiones WHERE submotivo_id IN "
             "(SELECT id FROM submotivos WHERE codigo = ANY(%s))", (cls.limpiar_codigos,))
        _sql("DELETE FROM submotivos WHERE codigo = ANY(%s)", (cls.limpiar_codigos,))

    def call(self, metodo, ruta, cuerpo=None, token=None):
        return _http(SERVICIO_URL, metodo, BASE + ruta, cuerpo, token or self.analista)

    def _devolucion(self, descripcion):
        linea = _sql("SELECT id FROM venta_detalle ORDER BY id LIMIT 1", uno=True)["id"]
        motivo = _sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1", uno=True)["id"]
        dev = _sql("""INSERT INTO devoluciones (venta_detalle_id, motivo_id, descripcion_problema,
                          cantidad_devuelta, estado)
                      VALUES (%s,%s,%s,1,'solicitada') RETURNING id""",
                   (linea, motivo, descripcion), uno=True)["id"]
        self.devoluciones.append(dev)
        return dev

    def test_seguridad(self):
        self.assertEqual(_http(SERVICIO_URL, "GET", BASE + "/submotivos")[0], 401)
        self.assertEqual(self.call("GET", "/submotivos", token=self.cliente)[0], 403)
        self.assertEqual(self.call("GET", "/clasificaciones", token=self.cliente)[0], 403)
        self.assertEqual(self.call("POST", "/submotivos", {}, self.inspector)[0], 403)

    def test_catalogo_inicial(self):
        codigo, cat = self.call("GET", "/categorias")
        self.assertEqual(codigo, 200)
        self.assertEqual({c["codigo"] for c in cat["datos"]},
                         {"falla_producto", "empaque", "transporte", "error_comercial", "mal_uso"})

    def test_cada_cambio_crea_version_y_conserva_la_anterior(self):
        cat = self.call("GET", "/categorias")[1]["datos"][0]["id"]
        alta = {"categoria_id": cat, "codigo": self.codigo, "nombre": "Prueba", "palabras_clave": ["zzprueba"]}
        codigo, creado = self.call("POST", "/submotivos", alta, self.admin)
        self.assertEqual((codigo, creado["version"]), (201, 1))
        self.assertEqual(self.call("POST", "/submotivos", alta, self.admin)[0], 409)
        sid = creado["id"]
        cuerpo = {"categoria_id": cat, "nombre": "Prueba v2", "palabras_clave": ["zzprueba", "otra"],
                  "motivo_cambio": "Se agrega una palabra"}
        self.assertEqual(self.call("PUT", f"/submotivos/{sid}", cuerpo, self.admin)[1]["version"], 2)
        # Repetir exactamente lo mismo no crea otra version.
        self.assertTrue(self.call("PUT", f"/submotivos/{sid}", cuerpo, self.admin)[1]["sin_cambios"])
        self.assertEqual(self.call("PATCH", f"/submotivos/{sid}/estado",
                                   {"activo": False, "motivo_cambio": "Se retira"}, self.admin)[1]["version"], 3)
        _, detalle = self.call("GET", f"/submotivos/{sid}")
        self.assertEqual([v["version"] for v in detalle["versiones"]], [3, 2, 1])
        self.assertEqual(detalle["versiones"][2]["nombre"], "Prueba")
        # Sin motivo del cambio no se edita.
        sin = {k: v for k, v in cuerpo.items() if k != "motivo_cambio"}
        self.assertEqual(self.call("PUT", f"/submotivos/{sid}", sin, self.admin)[0], 400)

    def test_sugerencia_de_texto_no_revela_palabras_clave_ni_guarda(self):
        antes = _sql("SELECT COUNT(*) AS n FROM clasificaciones_motivo", uno=True)["n"]
        codigo, r = self.call("POST", "/sugerencias",
                              {"descripcion": "El producto llego tibio y descongelado"}, self.cliente)
        self.assertEqual(codigo, 200)
        self.assertTrue(r["requiere_confirmacion"])
        self.assertEqual(r["sugerencias"][0]["codigo"], "cadena_frio")
        self.assertNotIn("coincidencias", r["sugerencias"][0])
        self.assertEqual(_sql("SELECT COUNT(*) AS n FROM clasificaciones_motivo", uno=True)["n"], antes)

    def test_flujo_de_revision_humana_no_toca_la_devolucion(self):
        dev = self._devolucion("El producto llego tibio, la temperatura era alta")
        antes = _sql("SELECT motivo_id, estado FROM devoluciones WHERE id=%s", (dev,), uno=True)
        codigo, cl = self.call("POST", "/clasificaciones", {"devolucion_id": dev})
        self.assertEqual(codigo, 201)
        self.assertEqual(cl["sugerencias"][0]["codigo"], "cadena_frio")
        # Una segunda sugerencia mientras la primera esta pendiente es un conflicto.
        self.assertEqual(self.call("POST", "/clasificaciones", {"devolucion_id": dev})[0], 409)
        # Corregir sin comentario no se acepta.
        self.assertEqual(self.call("POST", f"/clasificaciones/{cl['id']}/revision",
                                   {"decision": "corregir", "submotivo_id": 1})[0], 400)
        codigo, rev = self.call("POST", f"/clasificaciones/{cl['id']}/revision", {"decision": "confirmar"})
        self.assertEqual(codigo, 200)
        self.assertEqual((rev["estado"], rev["aplicado_a_devolucion"]), ("confirmada", False))
        self.assertEqual(rev["revisado_por"] is not None, True)
        # Ya revisada: no se puede revisar de nuevo.
        self.assertEqual(self.call("POST", f"/clasificaciones/{cl['id']}/revision",
                                   {"decision": "descartar", "comentario": "Cambie de idea"})[0], 409)
        despues = _sql("SELECT motivo_id, estado FROM devoluciones WHERE id=%s", (dev,), uno=True)
        self.assertEqual(antes, despues)  # RN-11

    def test_sin_coincidencias_solo_se_puede_corregir_o_descartar(self):
        dev = self._devolucion("No me gusto para nada el producto")
        _, cl = self.call("POST", "/clasificaciones", {"devolucion_id": dev})
        self.assertEqual(cl["sugerencias"], [])
        self.assertEqual(self.call("POST", f"/clasificaciones/{cl['id']}/revision",
                                   {"decision": "confirmar"})[0], 400)
        codigo, rev = self.call("POST", f"/clasificaciones/{cl['id']}/revision",
                                {"decision": "descartar", "comentario": "Texto sin informacion"})
        self.assertEqual((codigo, rev["estado"]), (200, "descartada"))


if __name__ == "__main__":
    unittest.main()
