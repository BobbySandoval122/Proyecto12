"""Pruebas unitarias de los endpoints que responden antes de tocar la base."""
import os
import time
import unittest
import uuid

import jwt

os.environ.setdefault("JWT_SECRET", "x" * 48)
os.environ["MONITOREO_INTERVALO_SEG"] = "0"  # sin hilo de fondo en pruebas
import app as servicio  # noqa: E402
import monitor  # noqa: E402
from shared import seguridad  # noqa: E402


class RedisFalso:
    def __init__(self):
        self.datos = {}

    def exists(self, k):
        return int(k in self.datos)


class PruebaApi(unittest.TestCase):
    def setUp(self):
        self.r = RedisFalso()
        self.original = seguridad.get_redis
        seguridad.get_redis = lambda: self.r
        self.cliente = servicio.create_app().test_client()

    def tearDown(self):
        seguridad.get_redis = self.original

    def cab(self, rol, **extra):
        sid = uuid.uuid4().hex
        self.r.datos[seguridad.clave_sesion(sid)] = "1"
        ahora = int(time.time())
        token = jwt.encode({"iss": seguridad.EMISOR, "sub": "7", "rol": rol, "nombre": "Prueba", "sid": sid,
                            "jti": uuid.uuid4().hex, "typ": "access", "iat": ahora, "exp": ahora + 600},
                           os.environ["JWT_SECRET"], algorithm="HS256")
        return {"Authorization": "Bearer " + token, **extra}

    def test_sin_token(self):
        self.assertEqual(self.cliente.get("/api/v1/monitoreo/estado").status_code, 401)

    def test_roles(self):
        self.assertEqual(self.cliente.get("/api/v1/monitoreo/estado",
                                          headers=self.cab(seguridad.CLIENTE)).status_code, 403)
        self.assertEqual(self.cliente.post("/api/v1/integraciones/ventas", json={},
                                           headers=self.cab(seguridad.SUPERVISOR)).status_code, 403)
        self.assertEqual(self.cliente.get("/api/v1/integraciones/exportaciones/devoluciones",
                                          headers=self.cab(seguridad.RECOLECTOR)).status_code, 403)

    def test_venta_invalida_responde_400_con_detalle(self):
        r = self.cliente.post("/api/v1/integraciones/ventas", headers=self.cab(seguridad.ADMINISTRADOR),
                              json={"id_externo": "TK-1", "lineas": []})
        self.assertEqual(r.status_code, 400)
        campos = {d["campo"] for d in r.get_json()["error"]["detalles"]}
        self.assertIn("tienda_externa", campos)
        self.assertIn("lineas", campos)

    def test_venta_xml_fuera_del_contrato(self):
        r = self.cliente.post("/api/v1/integraciones/ventas",
                              headers=self.cab(seguridad.ADMINISTRADOR, **{"Content-Type": "application/xml"}),
                              data="<venta><id_externo>TK 1</id_externo></venta>")
        self.assertEqual(r.status_code, 400)
        self.assertIn(b"xml_no_cumple_xsd", r.data)

    def test_parametros_invalidos(self):
        admin = self.cab(seguridad.ADMINISTRADOR)
        self.assertEqual(self.cliente.get("/api/v1/monitoreo/traza/a;b", headers=admin).status_code, 400)
        self.assertEqual(self.cliente.get("/api/v1/monitoreo/disponibilidad?horas=0", headers=admin).status_code, 400)
        self.assertEqual(self.cliente.get("/api/v1/monitoreo/alertas?estado=x", headers=admin).status_code, 400)
        r = self.cliente.post("/api/v1/integraciones/transportistas/eventos", headers=admin,
                              json={"guia": "G-1", "estado": "perdida"})
        self.assertEqual(r.status_code, 400)

    def test_servicio_que_no_responde_es_caido(self):
        resultado = monitor.revisar_servicio("fantasma", "http://127.0.0.1:9", timeout=1)
        self.assertEqual((resultado["estado"], resultado["ms"]), ("caido", None))
        self.assertIsNotNone(resultado["error"])

    def test_lista_de_servicios_desde_el_entorno(self):
        os.environ["MONITOREO_SERVICIOS"] = "a=http://a:8000/, b=http://b:8000"
        try:
            self.assertEqual(monitor.servicios_configurados(), {"a": "http://a:8000", "b": "http://b:8000"})
        finally:
            del os.environ["MONITOREO_SERVICIOS"]
        self.assertIn("sincronizacion", monitor.servicios_configurados())


if __name__ == "__main__":
    unittest.main()
