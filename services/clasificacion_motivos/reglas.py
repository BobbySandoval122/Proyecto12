"""Reglas puras del catalogo de submotivos y de la revision humana.

Sin base de datos, para probarlas en cualquier maquina.
Trazabilidad: RF-22, RN-09, RN-11.
"""
import re
import unicodedata

from shared.respuestas import ErrorApi

PATRON_CODIGO = re.compile(r"^[a-z0-9_]{3,40}$")
MAX_PALABRAS = 30
DECISIONES = ("confirmar", "corregir", "descartar")
MIN_DESCRIPCION, MAX_DESCRIPCION = 10, 2000


def normalizar(texto):
    """Minusculas y sin acentos: el catalogo y las descripciones se comparan asi."""
    sin = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in sin if unicodedata.category(c) != "Mn")


def puntuar(descripcion, submotivos, maximo=3):
    """Ranking explicable por palabras clave; es una sugerencia, nunca una decision.

    Una palabra coincide si aparece al inicio de una palabra del texto
    ('caduc' coincide con 'caducado' pero 'sol' no con 'solo'). El puntaje es el
    numero de palabras distintas que coincidieron.
    """
    texto = normalizar(descripcion)
    candidatos = []
    for s in submotivos:
        if not s.get("activo", True):
            continue
        hallazgos = sorted({p for p in s.get("palabras_clave") or []
                            if re.search(r"\b" + re.escape(p), texto)})
        if hallazgos:
            candidatos.append({"submotivo_id": s["id"], "codigo": s["codigo"],
                               "submotivo": s["nombre"], "categoria": s.get("categoria"),
                               "motivo_id": s.get("motivo_id"), "version": s.get("version"),
                               "puntaje": len(hallazgos), "coincidencias": hallazgos})
    candidatos.sort(key=lambda c: (-c["puntaje"], c["submotivo"]))
    return candidatos[:maximo]


def validar_descripcion(valor):
    texto = str(valor or "").strip()
    if not MIN_DESCRIPCION <= len(texto) <= MAX_DESCRIPCION:
        raise ErrorApi(400, "validacion",
                       f"descripcion debe contener entre {MIN_DESCRIPCION} y {MAX_DESCRIPCION} caracteres.")
    return texto


def entero_positivo(valor, campo):
    try:
        if isinstance(valor, bool):
            raise ValueError
        numero = int(valor)
        if numero <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ErrorApi(400, "validacion", f"{campo} debe ser un entero positivo.")
    return numero


def _texto(datos, campo, maximo, requerido=True, minimo=1):
    valor = datos.get(campo)
    if valor is None or valor == "":
        if requerido:
            return None, {"campo": campo, "problema": "obligatorio"}
        return None, None
    if not isinstance(valor, str) or not minimo <= len(valor.strip()) <= maximo:
        return None, {"campo": campo, "problema": f"entre {minimo} y {maximo} caracteres"}
    return valor.strip(), None


def validar_submotivo(datos, alta):
    """Alta (con codigo) o edicion (con motivo_cambio, que alimenta el historial)."""
    if not isinstance(datos, dict):
        raise ErrorApi(400, "validacion", "Se requiere un objeto.")
    permitidos = {"categoria_id", "motivo_id", "nombre", "descripcion", "palabras_clave"}
    permitidos |= {"codigo"} if alta else {"motivo_cambio"}
    extra = set(datos) - permitidos
    errores, limpio = [], {}
    if extra:
        errores.append({"campo": ",".join(sorted(extra)), "problema": "campo no permitido"})

    for campo, maximo, requerido, minimo in (("nombre", 100, True, 1),
                                             ("descripcion", 255, False, 1),
                                             ("motivo_cambio", 255, not alta, 5)):
        if campo == "motivo_cambio" and alta:
            continue
        valor, error = _texto(datos, campo, maximo, requerido, minimo)
        if error:
            errores.append(error)
        limpio[campo] = valor
    if alta:
        codigo = datos.get("codigo")
        if not isinstance(codigo, str) or not PATRON_CODIGO.match(codigo):
            errores.append({"campo": "codigo",
                            "problema": "3 a 40 caracteres: minusculas, numeros y guion bajo"})
        limpio["codigo"] = codigo

    for campo, requerido in (("categoria_id", True), ("motivo_id", False)):
        valor = datos.get(campo)
        if valor in (None, ""):
            if requerido:
                errores.append({"campo": campo, "problema": "obligatorio"})
            limpio[campo] = None
            continue
        try:
            limpio[campo] = entero_positivo(valor, campo)
        except ErrorApi:
            errores.append({"campo": campo, "problema": "entero positivo requerido"})

    palabras = datos.get("palabras_clave")
    if palabras in (None, ""):  # XML vacio llega como cadena vacia
        palabras = []
    if not isinstance(palabras, list) or len(palabras) > MAX_PALABRAS:
        errores.append({"campo": "palabras_clave", "problema": f"lista de hasta {MAX_PALABRAS} palabras"})
    else:
        normales = [normalizar(p).strip() if isinstance(p, str) else None for p in palabras]
        if any(not p or not 2 <= len(p) <= 40 for p in normales):
            errores.append({"campo": "palabras_clave", "problema": "cada palabra: 2 a 40 caracteres"})
        else:
            limpio["palabras_clave"] = sorted(set(normales))
    if errores:
        raise ErrorApi(400, "validacion", "Campos invalidos.", errores)
    return limpio


def validar_activo(datos):
    if not isinstance(datos, dict):
        raise ErrorApi(400, "validacion", "Se requiere un objeto.")
    activo = datos.get("activo")
    if isinstance(activo, str) and activo.lower() in ("true", "false"):
        activo = activo.lower() == "true"
    if not isinstance(activo, bool):
        raise ErrorApi(400, "validacion", "activo debe ser booleano.")
    motivo, error = _texto(datos, "motivo_cambio", 255, True, 5)
    if error:
        raise ErrorApi(400, "validacion", "Campos invalidos.", [error])
    return activo, motivo


def validar_revision(datos):
    """Decision humana sobre una sugerencia (RN-11).

    corregir y descartar exigen comentario: quien contradice a la sugerencia
    explica por que, y eso sirve despues para mejorar las palabras clave.
    """
    if not isinstance(datos, dict):
        raise ErrorApi(400, "validacion", "Se requiere un objeto.")
    extra = set(datos) - {"decision", "submotivo_id", "comentario"}
    if extra:
        raise ErrorApi(400, "validacion", "Campos invalidos.",
                       [{"campo": ",".join(sorted(extra)), "problema": "campo no permitido"}])
    decision = datos.get("decision")
    if decision not in DECISIONES:
        raise ErrorApi(400, "validacion", "decision debe ser: " + ", ".join(DECISIONES) + ".")
    comentario, error = _texto(datos, "comentario", 500, decision != "confirmar", 5)
    if error:
        raise ErrorApi(400, "validacion", "Campos invalidos.", [error])
    submotivo_id = None
    if decision == "corregir":
        submotivo_id = entero_positivo(datos.get("submotivo_id"), "submotivo_id")
    elif datos.get("submotivo_id") not in (None, ""):
        raise ErrorApi(400, "validacion", "submotivo_id solo aplica al corregir.")
    return decision, submotivo_id, comentario
