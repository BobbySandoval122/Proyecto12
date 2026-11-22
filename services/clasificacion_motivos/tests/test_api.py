"""Seguridad de la API sin base de datos: todo exige JWT (RNF-09, RN-13)."""
import pytest

from app import create_app


@pytest.fixture(scope="module")
def cliente():
    return create_app().test_client()


@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/api/v1/motivos/categorias"), ("get", "/api/v1/motivos/submotivos"),
    ("get", "/api/v1/motivos/submotivos/1"), ("post", "/api/v1/motivos/submotivos"),
    ("put", "/api/v1/motivos/submotivos/1"), ("patch", "/api/v1/motivos/submotivos/1/estado"),
    ("post", "/api/v1/motivos/sugerencias"), ("post", "/api/v1/motivos/clasificaciones"),
    ("get", "/api/v1/motivos/clasificaciones"),
    ("post", "/api/v1/motivos/clasificaciones/1/revision"),
])
def test_sin_token_401(cliente, metodo, ruta):
    assert getattr(cliente, metodo)(ruta).status_code == 401
