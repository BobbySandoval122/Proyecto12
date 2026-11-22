"""CSV, XLSX y PDF escritos con la biblioteca estandar. No necesitan base de datos.

Trazabilidad: RF-28, RNF-11, RNF-16.
"""
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from xml.dom import minidom

import pytest

import formatos as f

COLS = [("folio", "Folio", "texto"), ("fecha", "Fecha", "fecha"), ("motivo", "Motivo", "texto"),
        ("n", "Unidades", "entero"), ("tasa", "Tasa (%)", "decimal"), ("costo", "Costo", "dinero")]


def filas(n=3):
    return [{"folio": f"DEV-{i:04d}", "fecha": date(2026, 1, 1) + timedelta(days=i), "motivo": "Cadena de frío rota",
             "n": i, "tasa": Decimal("18.75"), "costo": Decimal("1234.50")} for i in range(1, n + 1)]


# --------------------------------------------------------------------------- texto / CSV
def test_texto_de_celda():
    assert f.texto(None) == "" and f.texto(True) == "si" and f.texto(Decimal("1E+3")) == "1000"
    assert f.texto(date(2026, 1, 2)) == "2026-01-02"
    assert f.texto(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02 03:04"


@pytest.mark.parametrize("valor", ["=SUMA(A1)", "+1+1", "-2+3", "@cmd", "\tx", "\rx"])
def test_csv_neutraliza_formulas(valor):
    assert f.celda_csv(valor) == "'" + valor


def test_csv_deja_numeros_y_texto_normal_intactos():
    assert f.celda_csv(-5) == "-5" and f.celda_csv(Decimal("-1.50")) == "-1.50"
    assert f.celda_csv("Producto dañado") == "Producto dañado" and f.celda_csv(None) == ""


def test_csv_con_bom_crlf_y_columnas_en_orden():
    crudo = f.a_csv(COLS, filas(2))
    assert crudo.startswith("﻿".encode("utf-8"))
    lineas = crudo.decode("utf-8-sig").split("\r\n")
    assert lineas[0] == "Folio,Fecha,Motivo,Unidades,Tasa (%),Costo"
    assert lineas[1] == "DEV-0001,2026-01-02,Cadena de frío rota,1,18.75,1234.50"


def test_csv_escapa_comas_y_comillas():
    fila = [{"folio": 'a,"b"', "motivo": "x\ny"}]
    assert '"a,""b"""' in f.a_csv(COLS, fila).decode("utf-8")


# --------------------------------------------------------------------------- limites
def test_demasiadas_filas_por_formato():
    grande = [{"folio": "x"}] * (f.MAX_FILAS["pdf"] + 1)
    with pytest.raises(f.DemasiadasFilas) as err:
        f.a_pdf("t", [], COLS, grande)
    assert err.value.formato == "pdf"
    assert f.a_csv(COLS, grande)                     # el mismo volumen si cabe en CSV
    with pytest.raises(f.DemasiadasFilas):
        f.a_csv(COLS, [{"folio": "x"}] * (f.MAX_FILAS["csv"] + 1))


# --------------------------------------------------------------------------- XLSX
def abrir(crudo):
    z = zipfile.ZipFile(io.BytesIO(crudo))
    for nombre in z.namelist():
        minidom.parseString(z.read(nombre))          # todo el XML esta bien formado
    return z


def test_xlsx_tiene_las_partes_de_un_libro_valido():
    z = abrir(f.a_xlsx("Devoluciones", COLS, filas(), [("Filtros", "sin filtros")]))
    assert set(z.namelist()) == {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                                 "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                                 "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"}
    assert b'name="Datos"' in z.read("xl/workbook.xml") and b'name="Informacion"' in z.read("xl/workbook.xml")


def test_xlsx_numeros_como_numeros_y_texto_como_texto():
    hoja = abrir(f.a_xlsx("T", COLS, filas(1), [])).read("xl/worksheets/sheet1.xml").decode()
    assert '<c r="D2" s="3"><v>1</v></c>' in hoja            # entero
    assert '<c r="E2" s="2"><v>18.75</v></c>' in hoja         # decimal
    assert '<c r="F2" s="4"><v>1234.50</v></c>' in hoja       # dinero
    assert 't="inlineStr"' in hoja and "Cadena de frío rota" in hoja
    assert '<pane ySplit="1"' in hoja                          # encabezado congelado


def test_xlsx_nunca_escribe_formulas():
    peligro = [{"folio": "=HYPERLINK(\"http://x\")", "motivo": "+cmd", "n": 1}]
    hoja = abrir(f.a_xlsx("T", COLS, peligro, [])).read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in hoja and "<f " not in hoja
    assert "&quot;http://x&quot;" in hoja                     # el texto va escapado, como texto


def test_xlsx_escapa_xml_y_quita_caracteres_de_control():
    fila = [{"folio": "<b>&\"'x\x00\x08y</b>", "motivo": "a\ud800b"}]
    hoja = abrir(f.a_xlsx("T", COLS, fila, [])).read("xl/worksheets/sheet1.xml").decode()
    assert "&lt;b&gt;&amp;&quot;" in hoja                      # escapado como texto
    assert "<b>" not in hoja and "\x00" not in hoja and "\x08" not in hoja


def test_xlsx_omite_valores_nulos_y_numeros_no_finitos():
    fila = [{"folio": "x", "n": None, "tasa": float("nan"), "costo": float("inf")}]
    hoja = abrir(f.a_xlsx("T", COLS, fila, [])).read("xl/worksheets/sheet1.xml").decode()
    assert "nan" not in hoja and "inf" not in hoja
    assert 'r="D2"' not in hoja and 'r="E2"' not in hoja


@pytest.mark.parametrize("indice,letras", [(0, "A"), (25, "Z"), (26, "AA"), (27, "AB"), (701, "ZZ"), (702, "AAA")])
def test_letras_de_columna(indice, letras):
    assert f._letras(indice) == letras


def test_xlsx_hoja_de_informacion():
    hoja = abrir(f.a_xlsx("Mi reporte", COLS, [], [("Filtros", "desde=2026-10-01"), ("Filas", "0")])).read(
        "xl/worksheets/sheet2.xml").decode()
    assert "Mi reporte" in hoja and "desde=2026-10-01" in hoja


# --------------------------------------------------------------------------- PDF
def estructura_pdf(crudo):
    """Verifica %PDF, el xref (cada desplazamiento apunta a su objeto) y el trailer."""
    assert crudo.startswith(b"%PDF-1.4") and crudo.rstrip().endswith(b"%%EOF")
    inicio = int(re.search(rb"startxref\n(\d+)\n%%EOF", crudo).group(1))
    assert crudo[inicio:inicio + 4] == b"xref"
    n = int(re.search(rb"xref\n0 (\d+)\n", crudo).group(1))
    entradas = re.findall(rb"(\d{10}) (\d{5}) ([nf]) \n", crudo[inicio:])
    assert len(entradas) == n and entradas[0][2] == b"f"
    for numero in range(1, n):
        desplazamiento = int(entradas[numero][0])
        assert crudo[desplazamiento:].startswith(b"%d 0 obj\n" % numero), numero
    assert int(re.search(rb"/Size (\d+)", crudo).group(1)) == n
    return n


def test_pdf_tiene_estructura_valida_y_paginas():
    crudo = f.a_pdf("Devoluciones", ["Generado: hoy", "Filas: 120"], COLS, filas(120))
    estructura_pdf(crudo)
    paginas = int(re.search(rb"/Type /Pages /Count (\d+)", crudo).group(1))
    assert paginas == 4 and crudo.count(b"/Type /Page ") == 4
    assert b"Pagina 1 de 4" in crudo and b"Pagina 4 de 4" in crudo


def test_pdf_longitud_de_cada_flujo_es_exacta():
    crudo = f.a_pdf("T", ["s"], COLS, filas(80))
    for m in re.finditer(rb"<< /Length (\d+) >>\nstream\n", crudo):
        inicio = m.end()
        assert crudo[inicio + int(m.group(1)):].startswith(b"\nendstream")


def test_pdf_sin_datos_dice_que_no_hay():
    crudo = f.a_pdf("Vacio", [], COLS, [])
    estructura_pdf(crudo)
    assert b"sin datos con estos filtros" in crudo


def test_pdf_escapa_parentesis_y_barras_y_acepta_acentos():
    fila = [{"folio": "a(b)c\\d", "motivo": "Cadena de frío rota ñ"}]
    crudo = f.a_pdf("Prueba (1)", [], COLS, fila)
    estructura_pdf(crudo)
    assert b"a\\(b\\)c\\\\d" in crudo
    assert "frío".encode("cp1252") in crudo and "ñ".encode("cp1252") in crudo


def test_pdf_caracteres_fuera_de_winansi_no_rompen_el_archivo():
    crudo = f.a_pdf("T", [], COLS, [{"folio": "日本語 \x00 ok", "motivo": "emoji 😀"}])
    estructura_pdf(crudo)
    assert b"\x00 " not in crudo.split(b"stream\n", 1)[1].split(b"endstream")[0]


def test_pdf_columnas_anchas_se_recortan_para_caber_en_la_pagina():
    ancho = [("a", "Columna uno", "texto"), ("b", "Columna dos", "texto"), ("c", "Columna tres", "texto")]
    fila = [{"a": "x" * 80, "b": "y" * 80, "c": "z" * 80}]
    assert sum(f._anchos_pdf(ancho, fila)) + 4 <= f.MAX_CAR
    crudo = f.a_pdf("T", [], ancho, fila)
    estructura_pdf(crudo)
    assert "…".encode("cp1252") in crudo


def test_pdf_alinea_numeros_a_la_derecha():
    linea = f._linea_tabla(["x", 7], [("a", "A", "texto"), ("n", "N", "entero")], [4, 5])
    assert linea == "x         7"


def test_pdf_pagina_justa_no_crea_pagina_vacia():
    primera = max(f.LINEAS_PAGINA - 2 - 1, 3)
    crudo = f.a_pdf("T", ["s"], COLS, filas(primera))
    assert int(re.search(rb"/Count (\d+)", crudo).group(1)) == 1
    crudo = f.a_pdf("T", ["s"], COLS, filas(primera + 1))
    assert int(re.search(rb"/Count (\d+)", crudo).group(1)) == 2
