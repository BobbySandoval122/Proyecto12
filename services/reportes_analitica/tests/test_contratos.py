"""El XSD de respuesta acepta el XML real que produce el servicio (RF-31)."""
import os
from xml.etree import ElementTree as ET

import pytest
from lxml import etree

from shared.respuestas import a_xml

RUTA = os.path.join(os.path.dirname(__file__), "..", "contratos", "reporte.xsd")


@pytest.fixture(scope="module")
def esquema():
    return etree.XMLSchema(etree.parse(RUTA))


def respuesta(datos, columnas=None):
    return {"reporte": "tasas", "titulo": "Tasa de devolucion", "generado_en": "2026-11-21T12:00:00+00:00",
            "filtros": {"por": "proveedor", "desde": "2026-10-01"},
            "columnas": columnas or [{"clave": "etiqueta", "titulo": "Nombre", "tipo": "texto"},
                                     {"clave": "tasa_pct", "titulo": "Tasa (%)", "tipo": "decimal"}],
            "datos": datos, "paginacion": {"pagina": 1, "por_pagina": 20, "total": len(datos), "paginas": 1}}


def test_xml_con_filas(esquema):
    xml = a_xml("reporte", respuesta([{"etiqueta": "Lacteos del Norte", "tasa_pct": 18.75},
                                      {"etiqueta": "CampoVerde", "tasa_pct": None}]))
    assert esquema.validate(etree.fromstring(xml)), esquema.error_log


def test_xml_sin_filas_ni_filtros(esquema):
    cuerpo = respuesta([])
    cuerpo["filtros"] = {}
    assert esquema.validate(etree.fromstring(a_xml("reporte", cuerpo))), esquema.error_log


def test_xml_rechaza_un_tipo_de_columna_desconocido(esquema):
    malo = respuesta([], [{"clave": "x", "titulo": "X", "tipo": "magia"}])
    assert not esquema.validate(etree.fromstring(a_xml("reporte", malo)))


def test_xml_rechaza_si_falta_la_paginacion(esquema):
    cuerpo = respuesta([])
    del cuerpo["paginacion"]
    assert not esquema.validate(etree.fromstring(a_xml("reporte", cuerpo)))
