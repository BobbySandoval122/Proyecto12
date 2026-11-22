"""Escritores de CSV, Excel (XLSX) y PDF con la biblioteca estandar.

CLAUDE.md pide no agregar librerias sin acordarlas con el equipo, y el repo no
tiene ninguna de PDF ni Excel; por eso se escriben aqui, simples y verificables:

 - CSV: UTF-8 con BOM (Excel lo abre con acentos) y celdas que no se ejecutan
   como formula (inyeccion de formulas).
 - XLSX: un zip de XML con dos hojas (Datos e Informacion), encabezado en
   negrita, primera fila congelada y numeros como numeros. Los textos van como
   cadenas en linea, nunca como formulas.
 - PDF: tablas en Courier (ancho fijo, asi el calculo de columnas es exacto),
   A4 horizontal, encabezado repetido en cada pagina y numeracion.

Una "columna" es (clave, titulo, tipo) con tipo texto, entero, decimal, dinero o fecha.
Trazabilidad: RF-28, RNF-11, RNF-16.
"""
import csv
import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal

NUMERICOS = ("entero", "decimal", "dinero")
PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")
MAX_FILAS = {"csv": 50000, "xlsx": 50000, "pdf": 3000}
_INVALIDOS_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


class DemasiadasFilas(Exception):
    def __init__(self, formato, filas):
        super().__init__(f"{filas} filas superan el maximo de {MAX_FILAS[formato]} para {formato}")
        self.formato, self.filas = formato, filas


def validar_tamano(formato, filas):
    if len(filas) > MAX_FILAS[formato]:
        raise DemasiadasFilas(formato, len(filas))


# --------------------------------------------------------------------------- #
# Texto de celda
# --------------------------------------------------------------------------- #
def texto(valor):
    """Valor a texto plano (fechas ISO, decimales sin notacion cientifica)."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "si" if valor else "no"
    if isinstance(valor, (datetime, date)):
        return valor.isoformat(sep=" ", timespec="minutes") if isinstance(valor, datetime) else valor.isoformat()
    if isinstance(valor, Decimal):
        return format(valor, "f")
    return str(valor)


def es_numero(valor):
    return isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool)


def celda_csv(valor):
    """Un texto que empieza con =, +, - o @ se leeria como formula: se antepone un apostrofo.

    Los numeros reales, incluso negativos, se dejan tal cual: el riesgo esta en
    el texto, no en las cifras.
    """
    if es_numero(valor):
        return texto(valor)
    cadena = texto(valor)
    return "'" + cadena if cadena.startswith(PREFIJOS_FORMULA) else cadena


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def a_csv(columnas, filas):
    validar_tamano("csv", filas)
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow([c[1] for c in columnas])
    for fila in filas:
        escritor.writerow([celda_csv(fila.get(c[0])) for c in columnas])
    return "﻿".encode("utf-8") + salida.getvalue().encode("utf-8")


# --------------------------------------------------------------------------- #
# XLSX
# --------------------------------------------------------------------------- #
def _xml(valor):
    cadena = _INVALIDOS_XML.sub("", texto(valor))
    return (cadena.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _letras(indice):
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _celda_xlsx(ref, valor, tipo, estilo_texto=0):
    if valor is None or valor == "":
        return ""
    if tipo in NUMERICOS and es_numero(valor):
        if isinstance(valor, float) and (valor != valor or valor in (float("inf"), float("-inf"))):
            return ""
        estilo = {"entero": 3, "decimal": 2, "dinero": 4}[tipo]
        return f'<c r="{ref}" s="{estilo}"><v>{texto(valor)}</v></c>'
    estilo = f' s="{estilo_texto}"' if estilo_texto else ""
    return f'<c r="{ref}"{estilo} t="inlineStr"><is><t xml:space="preserve">{_xml(valor)}</t></is></c>'


def _hoja(filas_celdas, anchos, congelar):
    """filas_celdas: lista de listas de (valor, tipo, estilo_texto)."""
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{a}" customWidth="1"/>' for i, a in enumerate(anchos))
    vista = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
             'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>') if congelar else ""
    filas = []
    for r, fila in enumerate(filas_celdas, start=1):
        celdas = "".join(_celda_xlsx(f"{_letras(c)}{r}", v, t, e) for c, (v, t, e) in enumerate(fila))
        filas.append(f'<row r="{r}">{celdas}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{vista}<cols>{cols}</cols><sheetData>{"".join(filas)}</sheetData></worksheet>')


def _anchos(columnas, filas):
    anchos = []
    for clave, titulo, _ in columnas:
        mayor = max([len(titulo)] + [len(texto(f.get(clave))) for f in filas[:500]])
        anchos.append(min(max(mayor + 2, 8), 60))
    return anchos


ESTILOS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
           '<fills count="3"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill>'
           '<fill><patternFill patternType="solid"><fgColor rgb="FFE7E6E6"/><bgColor indexed="64"/></patternFill></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="5">'
           '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
           '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '</cellXfs></styleSheet>')


def a_xlsx(titulo, columnas, filas, informacion):
    """informacion: lista de (nombre, valor) para la hoja 'Informacion'."""
    validar_tamano("xlsx", filas)
    datos = [[(c[1], "texto", 1) for c in columnas]]
    for fila in filas:
        datos.append([(fila.get(c[0]), c[2], 0) for c in columnas])
    info = [[("Reporte", "texto", 1), (titulo, "texto", 0)]]
    info += [[(n, "texto", 1), (v, "texto", 0)] for n, v in informacion]
    hoja1 = _hoja(datos, _anchos(columnas, filas), congelar=True)
    hoja2 = _hoja(info, [24, 70], congelar=False)
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Datos" sheetId="1" r:id="rId1"/>'
                   '<sheet name="Informacion" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
                   '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml", ESTILOS)
        z.writestr("xl/worksheets/sheet1.xml", hoja1)
        z.writestr("xl/worksheets/sheet2.xml", hoja2)
    return salida.getvalue()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
ANCHO_PAG, ALTO_PAG = 842, 595        # A4 horizontal, en puntos
MARGEN = 36
TAM = 8
ANCHO_CAR = 0.6 * TAM                 # Courier: cada caracter mide 0.6 em
INTERLINEA = 11.5
MAX_CAR = int((ANCHO_PAG - 2 * MARGEN) / ANCHO_CAR)
LINEAS_PAGINA = int((ALTO_PAG - 2 * MARGEN - 50) / INTERLINEA)


def _pdf_texto(valor):
    """Texto en WinAnsi (cp1252) escapado para un literal de PDF."""
    cadena = _INVALIDOS_XML.sub("", texto(valor)).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    crudo = cadena.encode("cp1252", errors="replace")
    return crudo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _recortar(cadena, ancho):
    return cadena if len(cadena) <= ancho else cadena[:max(ancho - 1, 0)] + "…"


def _anchos_pdf(columnas, filas):
    """Ancho en caracteres por columna; si no caben en la pagina se achican las mas anchas."""
    anchos = [min(max([len(c[1])] + [len(texto(f.get(c[0]))) for f in filas]), 40) for c in columnas]
    separacion = 2 * (len(columnas) - 1)
    while sum(anchos) + separacion > MAX_CAR and max(anchos) > 8:
        mayor = anchos.index(max(anchos))
        anchos[mayor] -= 1
    return anchos


def _linea_tabla(valores, columnas, anchos):
    celdas = []
    for valor, (_, _, tipo), ancho in zip(valores, columnas, anchos):
        cadena = _recortar(texto(valor), ancho)
        celdas.append(cadena.rjust(ancho) if tipo in NUMERICOS else cadena.ljust(ancho))
    return "  ".join(celdas)


def a_pdf(titulo, subtitulos, columnas, filas):
    """subtitulos: lineas de texto bajo el titulo (fecha, filtros, total)."""
    validar_tamano("pdf", filas)
    anchos = _anchos_pdf(columnas, filas)
    encabezado = _linea_tabla([c[1] for c in columnas], columnas, anchos)
    cuerpo = [_linea_tabla([f.get(c[0]) for c in columnas], columnas, anchos) for f in filas]
    if not cuerpo:
        cuerpo = ["(sin datos con estos filtros)"]

    # Pagina 1 lleva titulo y subtitulos; el resto, solo la tabla.
    paginas, indice = [], 0
    primera = max(LINEAS_PAGINA - 2 - len(subtitulos), 3)
    cupo = primera
    while indice < len(cuerpo) or not paginas:
        paginas.append(cuerpo[indice:indice + cupo])
        indice += cupo
        cupo = LINEAS_PAGINA
    total = len(paginas)

    objetos = {}  # numero -> bytes del cuerpo del objeto
    ids_paginas = []
    siguiente = 5
    for n, lineas in enumerate(paginas, start=1):
        ops = [b"BT"]
        y = ALTO_PAG - MARGEN

        def linea(fuente, tam, x, yy, contenido):
            ops.append(b"/%s %s Tf 1 0 0 1 %s %s Tm (" % (fuente, str(tam).encode(), str(x).encode(),
                       ("%.2f" % yy).encode()) + _pdf_texto(contenido) + b") Tj")
        if n == 1:
            linea(b"F2", 12, MARGEN, y, titulo)
            y -= 16
            for s in subtitulos:
                linea(b"F1", TAM, MARGEN, y, _recortar(s, MAX_CAR))
                y -= INTERLINEA
            y -= 6
        linea(b"F2", TAM, MARGEN, y, encabezado)
        raya = y - 3
        y -= INTERLINEA + 2
        for texto_linea in lineas:
            linea(b"F1", TAM, MARGEN, y, texto_linea)
            y -= INTERLINEA
        linea(b"F1", TAM, MARGEN, MARGEN - 14, f"{_recortar(titulo, 80)}   Pagina {n} de {total}")
        ops.append(b"ET")
        ops.append(b"0.5 w %d %.2f m %d %.2f l S" % (MARGEN, raya, ANCHO_PAG - MARGEN, raya))
        flujo = b"\n".join(ops)
        objetos[siguiente + 1] = b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream"
        objetos[siguiente] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                              b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
                              % (ANCHO_PAG, ALTO_PAG, siguiente + 1))
        ids_paginas.append(siguiente)
        siguiente += 2
    objetos[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objetos[2] = (b"<< /Type /Pages /Count %d /Kids [%s] >>"
                  % (total, b" ".join(b"%d 0 R" % i for i in ids_paginas)))
    objetos[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"
    objetos[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold /Encoding /WinAnsiEncoding >>"
    info = siguiente
    objetos[info] = b"<< /Title (" + _pdf_texto(titulo) + b") /Producer (Plataforma de devoluciones) >>"

    salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    desplazamientos = {}
    for numero in sorted(objetos):
        desplazamientos[numero] = len(salida)
        salida += b"%d 0 obj\n" % numero + objetos[numero] + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += b"xref\n0 %d\n0000000000 65535 f \n" % (info + 1)
    for numero in range(1, info + 1):
        salida += b"%010d 00000 n \n" % desplazamientos[numero]
    salida += (b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
               % (info + 1, info, inicio_xref))
    return bytes(salida)


# --------------------------------------------------------------------------- #
FORMATOS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}
