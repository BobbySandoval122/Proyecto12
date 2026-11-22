"""Los XSD son validos y aceptan lo que la API documenta (RF-31)."""
import os

import pytest
from lxml import etree

CONTRATOS = os.path.join(os.path.dirname(__file__), "..", "contratos")


def esquema(nombre):
    return etree.XMLSchema(etree.parse(os.path.join(CONTRATOS, nombre)))


@pytest.mark.parametrize("archivo,xml", [
    ("submotivo.xsd", "<submotivo><categoria_id>1</categoria_id><codigo>nuevo_sub</codigo>"
                      "<nombre>Nuevo</nombre><palabras_clave><item>olor</item><item>sabor</item>"
                      "</palabras_clave></submotivo>"),
    ("submotivo.xsd", "<submotivo><nombre>N</nombre><categoria_id>2</categoria_id>"
                      "<motivo_cambio>Ajuste de palabras</motivo_cambio><palabras_clave/></submotivo>"),
    ("estado.xsd", "<estado><activo>false</activo><motivo_cambio>Ya no se usa</motivo_cambio></estado>"),
    ("sugerencia.xsd", "<sugerencia><descripcion>El producto llego tibio</descripcion></sugerencia>"),
    ("clasificacion.xsd", "<clasificacion><devolucion_id>7</devolucion_id></clasificacion>"),
    ("revision.xsd", "<revision><decision>confirmar</decision></revision>"),
    ("revision.xsd", "<revision><decision>corregir</decision><submotivo_id>2</submotivo_id>"
                     "<comentario>Era un golpe</comentario></revision>"),
])
def test_xml_valido(archivo, xml):
    assert esquema(archivo).validate(etree.fromstring(xml)), esquema(archivo).error_log


@pytest.mark.parametrize("archivo,xml", [
    ("submotivo.xsd", "<submotivo><nombre>Sin categoria</nombre></submotivo>"),
    ("estado.xsd", "<estado><activo>quiza</activo><motivo_cambio>x</motivo_cambio></estado>"),
    ("sugerencia.xsd", "<sugerencia><descripcion>corta</descripcion></sugerencia>"),
    ("clasificacion.xsd", "<clasificacion><devolucion_id>-1</devolucion_id></clasificacion>"),
    ("revision.xsd", "<revision><decision>aprobar</decision></revision>"),
])
def test_xml_invalido(archivo, xml):
    assert not esquema(archivo).validate(etree.fromstring(xml))
