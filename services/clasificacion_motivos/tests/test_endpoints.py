"""POST /sugerencias con la base simulada: quien puede usarlo (RN-13, RNF-09).

Trazabilidad: RF-22, RN-11, RN-13, RNF-09.
"""
import pytest

import app as servicio
import shared.seguridad as seguridad

CATALOGO = [{"id": 1, "codigo": "cadena_frio", "nombre": "Cadena de frio rota", "categoria": "Transporte",
             "motivo_id": 4, "version": 1, "activo": True, "palabras_clave": ["tibio", "temperatura"]}]


@pytest.fixture
def api(monkeypatch):
    estado = {"rol": "Cliente", "limites": []}
    monkeypatch.setattr(seguridad, "decodificar", lambda token, tipo="access": {
        "sub": "7", "rol": estado["rol"], "nombre": "P", "sid": "s", "jti": "j"})
    monkeypatch.setattr(seguridad, "comprobar_en_redis", lambda claims: None)
    monkeypatch.setattr(servicio, "limitar", lambda *a, **k: estado["limites"].append((a, k)))
    monkeypatch.setattr(servicio, "consultar", lambda *a, **k: CATALOGO)
    cliente = servicio.create_app().test_client()
    cliente.estado = estado

    def pedir(rol, cuerpo=None):
        estado["rol"] = rol
        return cliente.post("/api/v1/motivos/sugerencias", headers={"Authorization": "Bearer x"},
                            json=cuerpo or {"descripcion": "El producto llego tibio y la temperatura era alta"})
    cliente.pedir = pedir
    return cliente


@pytest.mark.parametrize("rol", list(seguridad.TODOS_LOS_ROLES))
def test_cualquier_rol_puede_pedir_una_sugerencia(api, rol):
    """Esta documentado como 'cualquier rol'; el Supervisor y los roles de campo tambien."""
    r = api.pedir(rol)
    assert r.status_code == 200, rol
    assert r.json["requiere_confirmacion"] is True
    assert r.json["sugerencias"][0]["codigo"] == "cadena_frio"


def test_no_revela_las_palabras_clave_a_ningun_rol(api):
    for rol in ("Cliente", "Supervisor", "Administrador"):
        assert "coincidencias" not in api.pedir(rol).json["sugerencias"][0]


def test_el_limite_de_uso_es_por_usuario(api):
    api.pedir("Supervisor")
    (args, kwargs), = api.estado["limites"]
    assert args[:3] == ("sugerir_motivo", 30, 60) and kwargs["sujeto"] == "7"


def test_un_rol_desconocido_sigue_sin_permiso(api):
    assert api.pedir("Rol inventado").status_code == 403


def test_sin_token_401():
    assert servicio.create_app().test_client().post("/api/v1/motivos/sugerencias", json={}).status_code == 401
