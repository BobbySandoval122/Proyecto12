"""Seguridad de la API sin base de datos: todo exige JWT (RNF-09, RN-13)."""
import pytest

from app import create_app


@pytest.fixture(scope="module")
def cliente():
    return create_app().test_client()


RUTAS = [
    ("post", "/api/v1/causa-raiz/alertas/detectar"), ("get", "/api/v1/causa-raiz/alertas"),
    ("post", "/api/v1/causa-raiz/alertas/1/descartar"), ("post", "/api/v1/causa-raiz/alertas/1/investigar"),
    ("get", "/api/v1/causa-raiz/investigaciones"), ("post", "/api/v1/causa-raiz/investigaciones"),
    ("get", "/api/v1/causa-raiz/investigaciones/1"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/hipotesis"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/evidencias"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/verificacion"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/hipotesis/1/verificacion"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/conclusion"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/reabrir"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/acciones"),
    ("post", "/api/v1/causa-raiz/investigaciones/1/cierre"),
    ("get", "/api/v1/causa-raiz/acciones"), ("get", "/api/v1/causa-raiz/acciones/1"),
    ("post", "/api/v1/causa-raiz/acciones/1/estado"), ("post", "/api/v1/causa-raiz/acciones/1/mediciones"),
]


@pytest.mark.parametrize("metodo,ruta", RUTAS)
def test_sin_token_401(cliente, metodo, ruta):
    assert getattr(cliente, metodo)(ruta).status_code == 401


def test_las_rutas_probadas_son_todas_las_del_servicio(cliente):
    """Si alguien agrega un endpoint sin protegerlo, esta prueba lo senala."""
    app = cliente.application
    reales = {(m.lower(), str(r).replace("<int:iid>", "1").replace("<int:aid>", "1").replace("<int:hid>", "1"))
              for r in app.url_map.iter_rules() if str(r).startswith("/api/")
              for m in r.methods if m in ("GET", "POST")}
    assert reales == set(RUTAS)
