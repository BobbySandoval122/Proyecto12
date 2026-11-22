"""Los XSD son validos y aceptan lo que la API documenta (RF-31)."""
import glob
import os

import pytest
from lxml import etree

CONTRATOS = os.path.join(os.path.dirname(__file__), "..", "contratos")


def esquema(nombre):
    return etree.XMLSchema(etree.parse(os.path.join(CONTRATOS, nombre)))


def test_todos_los_xsd_cargan():
    archivos = glob.glob(os.path.join(CONTRATOS, "*.xsd"))
    assert len(archivos) == 12
    for a in archivos:
        etree.XMLSchema(etree.parse(a))


@pytest.mark.parametrize("archivo,xml", [
    ("vacio.xsd", "<verificacion/>"),
    ("descartar.xsd", "<descartar><comentario>Prueba interna</comentario></descartar>"),
    ("investigacion_alerta.xsd", "<investigacion><titulo>Lote</titulo><descripcion>Propuesta</descripcion></investigacion>"),
    ("investigacion.xsd", "<investigacion><dimension>lote</dimension><referencia_id>7</referencia_id>"
                          "<titulo>t</titulo><descripcion>d</descripcion></investigacion>"),
    ("hipotesis.xsd", "<hipotesis><tipo>cinco_porques</tipo><descripcion>Porque</descripcion><padre_id>3</padre_id></hipotesis>"),
    ("hipotesis.xsd", "<hipotesis><descripcion>Rama</descripcion><tipo>ishikawa</tipo>"
                      "<categoria_ishikawa>medio_ambiente</categoria_ishikawa></hipotesis>"),
    ("evidencia.xsd", "<evidencia><tipo>devolucion</tipo><descripcion>Caso</descripcion><devolucion_id>9</devolucion_id></evidencia>"),
    ("verificacion_hipotesis.xsd", "<verificacion><resultado>verificada</resultado>"
                                   "<resultado_verificacion>Confirmado</resultado_verificacion></verificacion>"),
    ("conclusion.xsd", "<conclusion><conclusion>inconclusa</conclusion><justificacion>Faltan datos</justificacion></conclusion>"),
    ("cierre.xsd", "<cierre><comentario>Todo funciono</comentario></cierre>"),
    ("accion.xsd", "<accion><tipo>correctiva</tipo><descripcion>d</descripcion><responsable_id>5</responsable_id>"
                   "<fecha_compromiso>2026-12-15</fecha_compromiso><meta_reduccion_pct>40</meta_reduccion_pct></accion>"),
    ("estado_accion.xsd", "<estado_accion><estado>implementada</estado><fecha_implementacion>2026-10-01</fecha_implementacion></estado_accion>"),
    ("medicion.xsd", "<medicion/>"),
    ("medicion.xsd", "<medicion><ventana_antes_dias>60</ventana_antes_dias></medicion>"),
])
def test_xml_valido(archivo, xml):
    assert esquema(archivo).validate(etree.fromstring(xml)), esquema(archivo).error_log


@pytest.mark.parametrize("archivo,xml", [
    ("descartar.xsd", "<descartar/>"),
    ("investigacion.xsd", "<investigacion><dimension>ruta</dimension><referencia_id>7</referencia_id>"
                          "<titulo>t</titulo><descripcion>d</descripcion></investigacion>"),
    ("investigacion.xsd", "<investigacion><dimension>lote</dimension><referencia_id>-7</referencia_id>"
                          "<titulo>t</titulo><descripcion>d</descripcion></investigacion>"),
    ("hipotesis.xsd", "<hipotesis><tipo>magia</tipo><descripcion>d</descripcion></hipotesis>"),
    ("evidencia.xsd", "<evidencia><tipo>video</tipo><descripcion>d</descripcion></evidencia>"),
    ("verificacion_hipotesis.xsd", "<verificacion><resultado>quiza</resultado><resultado_verificacion>x</resultado_verificacion></verificacion>"),
    ("conclusion.xsd", "<conclusion><conclusion>tal_vez</conclusion><justificacion>x</justificacion></conclusion>"),
    ("accion.xsd", "<accion><tipo>correctiva</tipo><descripcion>d</descripcion></accion>"),
    ("estado_accion.xsd", "<estado_accion><estado>planificada</estado></estado_accion>"),
    ("vacio.xsd", "<verificacion><algo>x</algo></verificacion>"),
])
def test_xml_invalido(archivo, xml):
    assert not esquema(archivo).validate(etree.fromstring(xml))
