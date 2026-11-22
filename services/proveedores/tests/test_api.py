"""Seguridad de la API sin base de datos: todo exige JWT (RNF-09, RN-13)."""
import pytest

from app import create_app


@pytest.fixture(scope="module")
def cliente():
    return create_app().test_client()


@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/api/v1/proveedores"), ("get", "/api/v1/proveedores/1"),
    ("get", "/api/v1/proveedores/1/productos"), ("get", "/api/v1/proveedores/1/indicadores"),
    ("get", "/api/v1/proveedores/reclamaciones"), ("get", "/api/v1/proveedores/reclamaciones/1"),
    ("post", "/api/v1/proveedores/reclamaciones"),
    ("post", "/api/v1/proveedores/reclamaciones/1/seguimiento"),
])
def test_sin_token_401(cliente, metodo, ruta):
    assert getattr(cliente, metodo)(ruta).status_code == 401
