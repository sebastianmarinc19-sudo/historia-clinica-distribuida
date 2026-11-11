"""Utilidades mínimas para generar el cuerpo de un .docx sobre la plantilla del curso.

Solo usa la biblioteca estándar. Usa los estilos que ya trae la plantilla
(Ttulo1/2/3, Listaconvietas, Normal, Tablaconcuadrcula) y agrega imágenes,
tablas, bloques de código y numeración de página.
"""
import re
import struct
import zipfile
from xml.sax.saxutils import escape

ANCHO_UTIL = 8842          # dxa: ancho de página 12240 menos márgenes de 1699
EMU_POR_PULGADA = 914400
LANG = '<w:lang w:val="es-CO"/>'


# ------------------------------------------------------------------ texto en línea
def _rpr(b=False, i=False, code=False, sz=None, color=None):
    partes = []
    if code:
        partes.append('<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/>')
    if b:
        partes.append("<w:b/>")
    if i:
        partes.append("<w:i/>")
    if color:
        partes.append(f'<w:color w:val="{color}"/>')
    if sz:
        partes.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
    partes.append(LANG)
    return "<w:rPr>" + "".join(partes) + "</w:rPr>"


def run(texto, **kw):
    return f'<w:r>{_rpr(**kw)}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'


_TOKENS = re.compile(r"(\*\*.+?\*\*|`.+?`|(?<![\w*])\*[^*\s][^*]*?\*(?![\w*]))")


def runs(texto, sz=None, color=None, b=False, i=False):
    """Convierte **negrita**, *cursiva* y `código` en runs."""
    salida = []
    for trozo in _TOKENS.split(texto):
        if not trozo:
            continue
        if trozo.startswith("**") and trozo.endswith("**"):
            salida.append(run(trozo[2:-2], b=True, i=i, sz=sz, color=color))
        elif trozo.startswith("`") and trozo.endswith("`"):
            salida.append(run(trozo[1:-1], code=True, b=b, i=i, sz=(sz or 22) - 2 if sz else 20, color=color))
        elif trozo.startswith("*") and trozo.endswith("*") and len(trozo) > 2:
            salida.append(run(trozo[1:-1], i=True, b=b, sz=sz, color=color))
        else:
            salida.append(run(trozo, b=b, i=i, sz=sz, color=color))
    return "".join(salida)


# ------------------------------------------------------------------ párrafos
def p(texto="", estilo=None, jc=None, antes=None, despues=120, keep=False, ind=None, sz=None, b=False, i=False, color=None,
      interlineado=None):
    ppr = []
    if estilo:
        ppr.append(f'<w:pStyle w:val="{estilo}"/>')
    if keep:
        ppr.append("<w:keepNext/>")
    sp = f'<w:spacing w:after="{despues}"'
    if antes is not None:
        sp += f' w:before="{antes}"'
    if interlineado:
        sp += f' w:line="{interlineado}" w:lineRule="auto"'
    ppr.append(sp + "/>")
    if ind:
        ppr.append(f'<w:ind w:left="{ind}"/>')
    if jc:
        ppr.append(f'<w:jc w:val="{jc}"/>')
    ppr.append(f"<w:rPr>{LANG}</w:rPr>")
    return f'<w:p><w:pPr>{"".join(ppr)}</w:pPr>{runs(texto, sz=sz, b=b, i=i, color=color)}</w:p>'


def justificado(texto, **kw):
    return p(texto, jc="both", **kw)


def h1(texto):
    return p(texto, estilo="Ttulo1", despues=120)


def h2(texto):
    return p(texto, estilo="Ttulo2", despues=100)


def h3(texto):
    return p(texto, estilo="Ttulo3", despues=80)


def viñetas(items, sz=None):
    return "".join(p(x, estilo="Listaconvietas", despues=60, sz=sz) for x in items)


def pie(texto):
    """Pie de figura o tabla: centrado, cursiva, tamaño menor."""
    return p(texto, jc="center", despues=200, sz=19, i=True, color="404040")


def salto_pagina():
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def codigo(texto):
    """Bloque de código con fondo gris claro y barra lateral."""
    salida = []
    lineas = texto.strip("\n").split("\n")
    for n, linea in enumerate(lineas):
        borde = ('<w:pBdr><w:left w:val="single" w:sz="18" w:space="6" w:color="8FA9C4"/></w:pBdr>'
                 '<w:shd w:val="clear" w:color="auto" w:fill="F2F4F7"/>')
        despues = 160 if n == len(lineas) - 1 else 0
        salida.append(
            f'<w:p><w:pPr>{borde}<w:spacing w:before="0" w:after="{despues}" w:line="240" w:lineRule="auto"/>'
            f'<w:ind w:left="200"/><w:rPr>{LANG}</w:rPr></w:pPr>'
            f'<w:r>{_rpr(code=True, sz=16)}<w:t xml:space="preserve">{escape(linea) if linea else " "}</w:t></w:r></w:p>')
    return "".join(salida)


# ------------------------------------------------------------------ tablas
def tabla(encabezado, filas, anchos, sz=18, alinear_centro=()):
    """anchos: lista en dxa que suma ANCHO_UTIL. Las celdas aceptan **negrita** y `código`."""
    assert sum(anchos) == ANCHO_UTIL, f"los anchos suman {sum(anchos)} y deben sumar {ANCHO_UTIL}"
    borde = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
    bordes = "<w:tblBorders>" + "".join(borde.format(x) for x in ("top", "left", "bottom", "right", "insideH", "insideV")) + "</w:tblBorders>"
    xml = ['<w:tbl><w:tblPr><w:tblStyle w:val="Tablaconcuadrcula"/>'
           f'<w:tblW w:w="{ANCHO_UTIL}" w:type="dxa"/><w:jc w:val="center"/>{bordes}<w:tblLayout w:type="fixed"/>'
           '<w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:bottom w:w="50" w:type="dxa"/>'
           '<w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr>']
    xml.append("<w:tblGrid>" + "".join(f'<w:gridCol w:w="{a}"/>' for a in anchos) + "</w:tblGrid>")

    def celda(texto, ancho, cabecera=False, centro=False):
        sombreado = '<w:shd w:val="clear" w:color="auto" w:fill="D9E2F3"/>' if cabecera else ""
        jc = '<w:jc w:val="center"/>' if centro else ""
        contenido = "".join(
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>{jc}<w:rPr>{LANG}</w:rPr></w:pPr>'
            f'{runs(parte, sz=sz, b=cabecera)}</w:p>' for parte in str(texto).split("\n"))
        return f'<w:tc><w:tcPr><w:tcW w:w="{ancho}" w:type="dxa"/>{sombreado}</w:tcPr>{contenido}</w:tc>'

    xml.append('<w:tr><w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>' +
               "".join(celda(t, a, cabecera=True) for t, a in zip(encabezado, anchos)) + "</w:tr>")
    for fila in filas:
        xml.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>' +
                   "".join(celda(t, a, centro=(k in alinear_centro)) for k, (t, a) in enumerate(zip(fila, anchos))) + "</w:tr>")
    xml.append("</w:tbl>")
    return "".join(xml)


# ------------------------------------------------------------------ imágenes
def tamano_imagen(ruta):
    with open(ruta, "rb") as f:
        cab = f.read(32)
        if cab[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", cab[16:24])
        f.seek(2)
        while True:
            marcador = f.read(2)
            if len(marcador) < 2:
                raise ValueError("JPEG sin SOF")
            if marcador[0] != 0xFF:
                continue
            largo = struct.unpack(">H", f.read(2))[0]
            if marcador[1] in (0xC0, 0xC1, 0xC2):
                f.read(1)
                alto, ancho = struct.unpack(">HH", f.read(4))
                return ancho, alto
            f.seek(largo - 2, 1)


class Imagenes:
    """Registra imágenes para incrustarlas y entrega el XML en línea."""

    def __init__(self):
        self.archivos = []     # (rId, ruta_origen, nombre_destino)
        self._n = 0

    def en_linea(self, ruta, ancho_pulgadas, descripcion):
        self._n += 1
        rid = f"rIdImg{self._n}"
        ext = ruta.rsplit(".", 1)[-1].lower()
        destino = f"imagen{self._n}.{ext}"
        self.archivos.append((rid, ruta, destino))
        w, h_ = tamano_imagen(ruta)
        cx = int(ancho_pulgadas * EMU_POR_PULGADA)
        cy = int(cx * h_ / w)
        return (
            '<w:p><w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60"/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{self._n}" name="Imagen {self._n}" descr="{escape(descripcion, {chr(34): "&quot;"})}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{self._n}" name="{destino}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:inline></w:drawing></w:r></w:p>')


# ------------------------------------------------------------------ ensamblado
PIE_PAGINA = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
    '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t>1</w:t></w:r>'
    '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')


def construir(plantilla, salida, cuerpo_xml, imagenes, titulo, autores):
    """Reemplaza el cuerpo de la plantilla conservando su sectPr, estilos y numeración."""
    with zipfile.ZipFile(plantilla) as zin:
        archivos = {n: zin.read(n) for n in zin.namelist() if not n.endswith("/")}

    doc = archivos["word/document.xml"].decode("utf-8")
    sect = re.search(r"<w:sectPr.*?</w:sectPr>", doc, re.S).group(0)
    sect = sect.replace(">", '><w:footerReference w:type="default" r:id="rIdPie1"/>', 1) if "<w:footerReference" not in sect else sect
    inicio = doc.index("<w:body>") + len("<w:body>")
    doc = doc[:inicio] + cuerpo_xml + sect + "</w:body></w:document>"
    archivos["word/document.xml"] = doc.encode("utf-8")

    rels = archivos["word/_rels/document.xml.rels"].decode("utf-8")
    nuevas = ['<Relationship Id="rIdPie1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>']
    for rid, ruta, destino in imagenes.archivos:
        nuevas.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{destino}"/>')
        with open(ruta, "rb") as f:
            archivos[f"word/media/{destino}"] = f.read()
    archivos["word/_rels/document.xml.rels"] = rels.replace("</Relationships>", "".join(nuevas) + "</Relationships>").encode("utf-8")
    archivos["word/footer1.xml"] = PIE_PAGINA.encode("utf-8")

    tipos = archivos["[Content_Types].xml"].decode("utf-8")
    extra = ('<Default Extension="png" ContentType="image/png"/><Default Extension="jpg" ContentType="image/jpeg"/>'
             '<Default Extension="jpeg" ContentType="image/jpeg"/>'
             '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>')
    archivos["[Content_Types].xml"] = tipos.replace("</Types>", extra + "</Types>").encode("utf-8")

    core = archivos["docProps/core.xml"].decode("utf-8")
    core = re.sub(r"<dc:title>.*?</dc:title>", f"<dc:title>{escape(titulo)}</dc:title>", core)
    core = re.sub(r"<dc:creator>.*?</dc:creator>", f"<dc:creator>{escape(autores)}</dc:creator>", core)
    core = re.sub(r"<dc:description>.*?</dc:description>", "<dc:description></dc:description>", core)
    archivos["docProps/core.xml"] = core.encode("utf-8")

    orden = ["[Content_Types].xml"] + [n for n in archivos if n != "[Content_Types].xml"]
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in orden:
            zout.writestr(n, archivos[n])
