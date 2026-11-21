"""Reglas puras de clasificacion de motivos. No necesitan base de datos.

Trazabilidad: RF-22, RN-09, RN-11, RNF-11.
"""
import pytest

import reglas
from shared.respuestas import ErrorApi

CATALOGO = [
    {"id": 1, "codigo": "cadena_frio", "nombre": "Cadena de frio rota", "categoria": "Transporte",
     "motivo_id": 4, "version": 1, "activo": True,
     "palabras_clave": ["tibio", "temperatura", "descongelado", "frio"]},
    {"id": 2, "codigo": "empaque_roto", "nombre": "Empaque roto", "categoria": "Empaque",
     "motivo_id": 1, "version": 3, "activo": True,
     "palabras_clave": ["roto", "derrame", "fuga"]},
    {"id": 3, "codigo": "uso", "nombre": "Almacenamiento", "categoria": "Mal uso",
     "motivo_id": None, "version": 1, "activo": True, "palabras_clave": ["al sol"]},
    {"id": 4, "codigo": "viejo", "nombre": "Desactivado", "categoria": "Empaque",
     "motivo_id": 1, "version": 2, "activo": False, "palabras_clave": ["roto"]},
]


def test_normalizar_quita_acentos_y_mayusculas():
    assert reglas.normalizar("Llegó TIBIO, Frío") == "llego tibio, frio"


def test_sugiere_el_submotivo_con_mas_coincidencias():
    r = reglas.puntuar("El producto llego tibio, la temperatura era alta y estaba descongelado", CATALOGO)
    assert r[0]["codigo"] == "cadena_frio"
    assert r[0]["puntaje"] == 3
    assert r[0]["coincidencias"] == ["descongelado", "temperatura", "tibio"]
    assert r[0]["version"] == 1


def test_no_sugiere_submotivos_inactivos():
    r = reglas.puntuar("El empaque llego roto", CATALOGO)
    assert [x["codigo"] for x in r] == ["empaque_roto"]


def test_palabra_coincide_por_inicio_no_por_fragmento():
    """'sol' dentro de 'solo' no debe disparar 'al sol'; 'rot' no coincide con 'derrota'."""
    assert reglas.puntuar("Solo llego una caja", CATALOGO) == []
    assert reglas.puntuar("El pan estaba al sol", CATALOGO)[0]["codigo"] == "uso"


def test_sin_coincidencias_no_inventa_una_sugerencia():
    assert reglas.puntuar("No me gusto", CATALOGO) == []


def test_empate_se_ordena_por_nombre_y_se_limita():
    cat = [{"id": i, "codigo": f"c{i}", "nombre": n, "activo": True, "palabras_clave": ["roto"]}
           for i, n in enumerate(["Beta", "Alfa", "Gamma", "Delta"])]
    r = reglas.puntuar("roto", cat, maximo=3)
    assert [x["submotivo"] for x in r] == ["Alfa", "Beta", "Delta"]


@pytest.mark.parametrize("texto", ["", "corto", "x" * 2001, None])
def test_descripcion_invalida(texto):
    with pytest.raises(ErrorApi) as err:
        reglas.validar_descripcion(texto)
    assert err.value.codigo == 400


ALTA = {"categoria_id": 1, "codigo": "nuevo_sub", "nombre": "Nuevo", "palabras_clave": ["Olor", "olor", " Sabor "]}


def test_alta_valida_normaliza_y_deduplica_palabras():
    r = reglas.validar_submotivo(dict(ALTA), alta=True)
    assert r["palabras_clave"] == ["olor", "sabor"]
    assert r["motivo_id"] is None


def test_alta_acepta_palabras_vacias_como_en_xml():
    assert reglas.validar_submotivo({**ALTA, "palabras_clave": ""}, alta=True)["palabras_clave"] == []


@pytest.mark.parametrize("cambio", [
    {"codigo": "Con Espacios"}, {"codigo": "ab"}, {"nombre": ""}, {"nombre": "x" * 101},
    {"categoria_id": 0}, {"categoria_id": True}, {"motivo_id": "abc"},
    {"palabras_clave": "texto"}, {"palabras_clave": ["a"]}, {"palabras_clave": [1]},
    {"palabras_clave": [f"palabra{i}" for i in range(31)]},
    {"motivo_cambio": "no va en el alta"}, {"id": 5}, {"activo": False},
])
def test_alta_invalida(cambio):
    with pytest.raises(ErrorApi) as err:
        reglas.validar_submotivo({**ALTA, **cambio}, alta=True)
    assert err.value.codigo == 400


def test_edicion_exige_motivo_del_cambio():
    base = {"categoria_id": 1, "nombre": "Nuevo", "palabras_clave": ["olor"]}
    with pytest.raises(ErrorApi):
        reglas.validar_submotivo(base, alta=False)
    with pytest.raises(ErrorApi):  # demasiado corto para explicar algo
        reglas.validar_submotivo({**base, "motivo_cambio": "ok"}, alta=False)
    assert reglas.validar_submotivo({**base, "motivo_cambio": "Se agrega la palabra olor"},
                                    alta=False)["motivo_cambio"] == "Se agrega la palabra olor"


def test_edicion_no_permite_cambiar_el_codigo():
    with pytest.raises(ErrorApi):
        reglas.validar_submotivo({"categoria_id": 1, "nombre": "N", "codigo": "otro",
                                  "motivo_cambio": "Cambio de codigo"}, alta=False)


def test_activo_acepta_texto_de_xml():
    assert reglas.validar_activo({"activo": "false", "motivo_cambio": "Ya no se usa"}) == (False, "Ya no se usa")
    for malo in ({"activo": "si", "motivo_cambio": "Ya no se usa"}, {"activo": True}):
        with pytest.raises(ErrorApi):
            reglas.validar_activo(malo)


def test_confirmar_no_pide_comentario():
    assert reglas.validar_revision({"decision": "confirmar"}) == ("confirmar", None, None)


def test_corregir_exige_submotivo_y_comentario():
    assert reglas.validar_revision({"decision": "corregir", "submotivo_id": "2",
                                    "comentario": "Era un golpe, no frio"}) == ("corregir", 2, "Era un golpe, no frio")
    for malo in ({"decision": "corregir", "comentario": "Era un golpe"},
                 {"decision": "corregir", "submotivo_id": 2},
                 {"decision": "descartar"},
                 {"decision": "confirmar", "submotivo_id": 2},
                 {"decision": "aprobar"}, {}, {"decision": "confirmar", "extra": 1}):
        with pytest.raises(ErrorApi):
            reglas.validar_revision(malo)
