"""Los XSD son validos y aceptan lo que la API documenta (RF-31)."""
import os

import pytest
from lxml import etree

CONTRATOS = os.path.join(os.path.dirname(__file__), "..", "contratos")


def esquema(nombre):
    return etree.XMLSchema(etree.parse(os.path.join(CONTRATOS, nombre)))


@pytest.mark.parametrize("archivo,xml", [
    ("reclamacion.xsd", "<reclamacion><proveedor_id>1</proveedor_id><asunto>Leche tibia</asunto>"
                        "<descripcion>Varias devoluciones</descripcion><lote_id>5</lote_id>"
                        "<devolucion_ids><item>3</item><item>9</item></devolucion_ids></reclamacion>"),
    ("reclamacion.xsd", "<reclamacion><descripcion>d</descripcion><asunto>a</asunto>"
                        "<proveedor_id>2</proveedor_id><devolucion_ids/></reclamacion>"),
    ("seguimiento.xsd", "<seguimiento><estado>enviada</estado></seguimiento>"),
    ("seguimiento.xsd", "<seguimiento><estado>cerrada</estado><resolucion>aceptada</resolucion>"
                        "<monto_recuperado>800.00</monto_recuperado><comentario>Nota de credito</comentario></seguimiento>"),
])
def test_xml_valido(archivo, xml):
    assert esquema(archivo).validate(etree.fromstring(xml)), esquema(archivo).error_log


@pytest.mark.parametrize("archivo,xml", [
    ("reclamacion.xsd", "<reclamacion><asunto>Sin proveedor</asunto><descripcion>d</descripcion></reclamacion>"),
    ("reclamacion.xsd", "<reclamacion><proveedor_id>-1</proveedor_id><asunto>a</asunto><descripcion>d</descripcion></reclamacion>"),
    ("seguimiento.xsd", "<seguimiento><estado>abierta</estado></seguimiento>"),
    ("seguimiento.xsd", "<seguimiento><estado>cerrada</estado><resolucion>ganada</resolucion></seguimiento>"),
])
def test_xml_invalido(archivo, xml):
    assert not esquema(archivo).validate(etree.fromstring(xml))
