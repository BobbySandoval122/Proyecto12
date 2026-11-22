"""Reglas puras de causa raiz y acciones correctivas (sin base de datos).

El flujo del profe: patron -> alerta -> investigacion -> evidencia -> hipotesis
(5 porques, Ishikawa) -> verificacion -> causa confirmada o inconclusa -> CAPA
con responsable y fecha -> medir si funciono -> cierre por un supervisor.
El analisis APOYA; cada paso lo decide una persona (RN-09, RN-11).

Trazabilidad: RF-23, RF-24, RN-09, RN-11, RN-12.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from shared.respuestas import ErrorApi

DIMENSIONES = ("lote", "proveedor", "tienda", "producto")
# Una alerta exige un patron claro y suficiente muestra, para no alarmar por ruido.
VECES_ALERTA = 2.0
MIN_UNIDADES = 20
MIN_CASOS = 3
META_PREDETERMINADA = Decimal("30")
VENTANA_ANTES_DIAS = 90
MAX_VENTANA_DIAS = 365
PLAZO_PREDETERMINADO = 30  # dias; el real sale de politicas_devolucion (RN-16)

ESTADOS = ("abierta", "en_verificacion", "concluida", "en_accion", "en_medicion", "cerrada")
TRANSICIONES = {
    "abierta": {"en_verificacion"},
    "en_verificacion": {"concluida"},
    # Una conclusion inconclusa puede reabrirse si aparece mas informacion.
    "concluida": {"en_accion", "en_verificacion", "cerrada"},
    # Cerrar desde en_accion solo si todas las acciones se cancelaron (lo valida el servicio).
    "en_accion": {"en_medicion", "cerrada"},
    "en_medicion": {"en_medicion", "cerrada"},
    "cerrada": set(),
}
CATEGORIAS_ISHIKAWA = ("material", "metodo", "maquina", "mano_de_obra", "medicion", "medio_ambiente")
TIPOS_HIPOTESIS = ("cinco_porques", "ishikawa", "libre")
TIPOS_EVIDENCIA = ("devolucion", "inspeccion", "dato", "documento", "nota")
TIPOS_CAPA = ("correctiva", "preventiva")
TRANSICIONES_CAPA = {
    "planificada": {"en_curso", "cancelada"},
    "en_curso": {"implementada", "cancelada"},
    "implementada": set(),
    "cancelada": set(),
}


def tasa(devueltas, vendidas):
    vendidas = float(vendidas or 0)
    if vendidas <= 0:
        return None
    return round(float(devueltas or 0) * 100.0 / vendidas, 2)


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


def _texto(datos, campo, maximo, minimo=1, requerido=True):
    valor = datos.get(campo)
    if valor is None or valor == "":
        return (None, {"campo": campo, "problema": "obligatorio"}) if requerido else (None, None)
    if not isinstance(valor, str) or not minimo <= len(valor.strip()) <= maximo:
        return None, {"campo": campo, "problema": f"entre {minimo} y {maximo} caracteres"}
    return valor.strip(), None


def _objeto(datos, permitidos):
    if not isinstance(datos, dict):
        raise ErrorApi(400, "validacion", "Se requiere un objeto.")
    extra = set(datos) - set(permitidos)
    if extra:
        raise ErrorApi(400, "validacion", "Campos invalidos.",
                       [{"campo": ",".join(sorted(extra)), "problema": "campo no permitido"}])


def _levantar(errores):
    if errores:
        raise ErrorApi(400, "validacion", "Campos invalidos.", errores)


def exigir_transicion(actual, nuevo, tabla=TRANSICIONES, nombre="investigacion"):
    if nuevo not in tabla.get(actual, set()):
        raise ErrorApi(409, "transicion_invalida",
                       f"La {nombre} no puede pasar de {actual} a {nuevo}.")


# --------------------------------------------------------------------------- #
# Alertas
# --------------------------------------------------------------------------- #
def evaluar_alerta(vendidas, devueltas, casos, promedio_pct):
    """Veces sobre el promedio si el patron amerita alerta; None si no.

    Criterios: tasa al menos el doble del promedio, 20 unidades vendidas y 3
    casos como minimo. Un lote con 1 venta y 1 devolucion no es un patron.
    """
    t = tasa(devueltas, vendidas)
    if t is None or not promedio_pct or vendidas < MIN_UNIDADES or casos < MIN_CASOS:
        return None
    veces = round(t / promedio_pct, 2)
    return veces if veces >= VECES_ALERTA else None


def validar_descartar(datos):
    _objeto(datos, {"comentario"})
    comentario, error = _texto(datos, "comentario", 500, 10)
    _levantar([error] if error else [])
    return comentario


# --------------------------------------------------------------------------- #
# Investigaciones
# --------------------------------------------------------------------------- #
def validar_investigacion(datos, desde_alerta=False):
    """Alta manual (con objeto) o desde una alerta (el objeto ya viene de ella)."""
    permitidos = {"titulo", "descripcion"} | (set() if desde_alerta else {"dimension", "referencia_id"})
    _objeto(datos, permitidos)
    errores, limpio = [], {}
    for campo, maximo, minimo in (("titulo", 150, 5), ("descripcion", 2000, 10)):
        limpio[campo], error = _texto(datos, campo, maximo, minimo)
        if error:
            errores.append(error)
    if not desde_alerta:
        if datos.get("dimension") not in DIMENSIONES:
            errores.append({"campo": "dimension", "problema": "debe ser: " + ", ".join(DIMENSIONES)})
        limpio["dimension"] = datos.get("dimension")
        try:
            limpio["referencia_id"] = entero_positivo(datos.get("referencia_id"), "referencia_id")
        except ErrorApi:
            errores.append({"campo": "referencia_id", "problema": "entero positivo requerido"})
    _levantar(errores)
    return limpio


def validar_hipotesis(datos, hipotesis_existentes):
    """Hipotesis nueva. El nivel de un porque se calcula, no lo manda el cliente.

    hipotesis_existentes: las de esta investigacion (id, tipo, nivel). Un porque
    sin padre es el nivel 1; con padre, el nivel siguiente. La cadena no pasa de
    5 niveles ni se ramifica (cada porque tiene una sola continuacion).
    """
    _objeto(datos, {"tipo", "descripcion", "padre_id", "categoria_ishikawa"})
    tipo = datos.get("tipo")
    errores = []
    if tipo not in TIPOS_HIPOTESIS:
        raise ErrorApi(400, "validacion", "tipo debe ser: " + ", ".join(TIPOS_HIPOTESIS) + ".")
    descripcion, error = _texto(datos, "descripcion", 2000, 10)
    if error:
        errores.append(error)
    nivel = padre_id = categoria = None
    if tipo == "ishikawa":
        categoria = datos.get("categoria_ishikawa")
        if categoria not in CATEGORIAS_ISHIKAWA:
            errores.append({"campo": "categoria_ishikawa",
                            "problema": "debe ser: " + ", ".join(CATEGORIAS_ISHIKAWA)})
    elif datos.get("categoria_ishikawa") not in (None, ""):
        errores.append({"campo": "categoria_ishikawa", "problema": "solo aplica a Ishikawa"})
    if tipo == "cinco_porques":
        if datos.get("padre_id") in (None, ""):
            nivel = 1
        else:
            try:
                padre_id = entero_positivo(datos["padre_id"], "padre_id")
            except ErrorApi:
                errores.append({"campo": "padre_id", "problema": "entero positivo requerido"})
            else:
                padre = next((h for h in hipotesis_existentes if h["id"] == padre_id), None)
                if not padre or padre["tipo"] != "cinco_porques":
                    raise ErrorApi(409, "padre_invalido", "El porque anterior no existe en esta investigacion.")
                if padre["nivel"] >= 5:
                    raise ErrorApi(409, "cadena_completa", "La cadena de 5 porques ya esta completa.")
                if any(h.get("padre_id") == padre_id for h in hipotesis_existentes):
                    raise ErrorApi(409, "porque_con_continuacion",
                                   "Ese porque ya tiene una continuacion.")
                nivel = padre["nivel"] + 1
    elif datos.get("padre_id") not in (None, ""):
        errores.append({"campo": "padre_id", "problema": "solo aplica a los 5 porques"})
    _levantar(errores)
    return {"tipo": tipo, "nivel": nivel, "padre_id": padre_id,
            "categoria_ishikawa": categoria, "descripcion": descripcion}


def validar_verificacion(datos):
    _objeto(datos, {"resultado", "resultado_verificacion"})
    if datos.get("resultado") not in ("verificada", "descartada"):
        raise ErrorApi(400, "validacion", "resultado debe ser verificada o descartada.")
    texto, error = _texto(datos, "resultado_verificacion", 1000, 10)
    _levantar([error] if error else [])
    return datos["resultado"], texto


def validar_evidencia(datos):
    _objeto(datos, {"tipo", "descripcion", "devolucion_id", "hipotesis_id", "referencia_externa"})
    errores, limpio = [], {}
    if datos.get("tipo") not in TIPOS_EVIDENCIA:
        errores.append({"campo": "tipo", "problema": "debe ser: " + ", ".join(TIPOS_EVIDENCIA)})
    limpio["tipo"] = datos.get("tipo")
    limpio["descripcion"], error = _texto(datos, "descripcion", 2000, 5)
    if error:
        errores.append(error)
    limpio["referencia_externa"], error = _texto(datos, "referencia_externa", 255, 1, requerido=False)
    if error:
        errores.append(error)
    for campo in ("devolucion_id", "hipotesis_id"):
        if datos.get(campo) in (None, ""):
            limpio[campo] = None
            continue
        try:
            limpio[campo] = entero_positivo(datos[campo], campo)
        except ErrorApi:
            errores.append({"campo": campo, "problema": "entero positivo requerido"})
    if limpio["tipo"] in ("devolucion", "inspeccion") and limpio.get("devolucion_id") is None:
        errores.append({"campo": "devolucion_id", "problema": "obligatorio para este tipo"})
    _levantar(errores)
    return limpio


def validar_conclusion(datos, hipotesis_verificadas, evidencias):
    """Causa confirmada solo con evidencia y al menos una hipotesis verificada (RN-09)."""
    _objeto(datos, {"conclusion", "causa_raiz", "justificacion"})
    conclusion = datos.get("conclusion")
    if conclusion not in ("causa_confirmada", "inconclusa"):
        raise ErrorApi(400, "validacion", "conclusion debe ser causa_confirmada o inconclusa.")
    errores = []
    justificacion, error = _texto(datos, "justificacion", 2000, 10)
    if error:
        errores.append(error)
    causa, error = _texto(datos, "causa_raiz", 2000, 10, requerido=conclusion == "causa_confirmada")
    if error:
        errores.append(error)
    if conclusion == "inconclusa" and causa:
        errores.append({"campo": "causa_raiz", "problema": "una investigacion inconclusa no declara causa"})
    _levantar(errores)
    if conclusion == "causa_confirmada":
        if evidencias < 1:
            raise ErrorApi(409, "sin_evidencia", "Confirmar una causa exige al menos una evidencia.")
        if hipotesis_verificadas < 1:
            raise ErrorApi(409, "sin_hipotesis_verificada",
                           "Confirmar una causa exige al menos una hipotesis verificada.")
    return conclusion, causa, justificacion


def validar_cierre(datos):
    _objeto(datos, {"comentario"})
    comentario, error = _texto(datos, "comentario", 2000, 10)
    _levantar([error] if error else [])
    return comentario


# --------------------------------------------------------------------------- #
# CAPA
# --------------------------------------------------------------------------- #
def _meta(valor):
    if valor in (None, ""):
        return META_PREDETERMINADA
    try:
        if isinstance(valor, bool):
            raise InvalidOperation
        cifra = Decimal(str(valor).strip())
        if not cifra.is_finite() or not Decimal("1") <= cifra <= Decimal("100") \
                or cifra != cifra.quantize(Decimal("0.01")):
            raise InvalidOperation
    except InvalidOperation:
        raise ErrorApi(400, "validacion", "meta_reduccion_pct debe estar entre 1 y 100 con dos decimales como maximo.")
    return cifra.quantize(Decimal("0.01"))


def validar_capa(datos, hoy=None):
    hoy = hoy or date.today()
    _objeto(datos, {"tipo", "descripcion", "responsable_id", "fecha_compromiso", "meta_reduccion_pct"})
    errores, limpio = [], {}
    if datos.get("tipo") not in TIPOS_CAPA:
        errores.append({"campo": "tipo", "problema": "debe ser correctiva o preventiva"})
    limpio["tipo"] = datos.get("tipo")
    limpio["descripcion"], error = _texto(datos, "descripcion", 2000, 10)
    if error:
        errores.append(error)
    try:
        limpio["responsable_id"] = entero_positivo(datos.get("responsable_id"), "responsable_id")
    except ErrorApi:
        errores.append({"campo": "responsable_id", "problema": "entero positivo requerido"})
    try:
        fecha = date.fromisoformat(str(datos.get("fecha_compromiso")))
        if fecha < hoy:
            raise ValueError
        limpio["fecha_compromiso"] = fecha
    except ValueError:
        errores.append({"campo": "fecha_compromiso", "problema": "fecha AAAA-MM-DD que no sea pasada"})
    try:
        limpio["meta_reduccion_pct"] = _meta(datos.get("meta_reduccion_pct"))
    except ErrorApi as exc:
        errores.append({"campo": "meta_reduccion_pct", "problema": exc.mensaje})
    _levantar(errores)
    return limpio


def validar_estado_capa(datos, actual, hoy=None):
    """Cambio de estado de una accion: (estado, fecha_implementacion, comentario)."""
    hoy = hoy or date.today()
    _objeto(datos, {"estado", "comentario", "fecha_implementacion"})
    nuevo = datos.get("estado")
    if nuevo not in TRANSICIONES_CAPA:
        raise ErrorApi(400, "validacion", "estado debe ser: en_curso, implementada o cancelada.")
    exigir_transicion(actual, nuevo, TRANSICIONES_CAPA, "accion")
    comentario, error = _texto(datos, "comentario", 500, 5, requerido=nuevo == "cancelada")
    _levantar([error] if error else [])
    fecha = None
    if nuevo == "implementada":
        bruto = datos.get("fecha_implementacion")
        try:
            fecha = hoy if bruto in (None, "") else date.fromisoformat(str(bruto))
            if fecha > hoy or fecha < hoy - timedelta(days=MAX_VENTANA_DIAS):
                raise ValueError
        except ValueError:
            raise ErrorApi(400, "validacion",
                           "fecha_implementacion debe ser una fecha AAAA-MM-DD, no futura y de menos de un ano.")
    elif datos.get("fecha_implementacion") not in (None, ""):
        raise ErrorApi(400, "validacion", "fecha_implementacion solo aplica al implementar.")
    return nuevo, fecha, comentario


# --------------------------------------------------------------------------- #
# Medicion de eficacia
# --------------------------------------------------------------------------- #
def validar_medicion(datos, hoy=None):
    hoy = hoy or date.today()
    _objeto(datos, {"ventana_antes_dias", "hasta"})
    ventana = datos.get("ventana_antes_dias", VENTANA_ANTES_DIAS)
    if ventana in (None, ""):
        ventana = VENTANA_ANTES_DIAS
    try:
        if isinstance(ventana, bool):
            raise ValueError
        ventana = int(ventana)
        if not 7 <= ventana <= MAX_VENTANA_DIAS:
            raise ValueError
    except (TypeError, ValueError):
        raise ErrorApi(400, "validacion", f"ventana_antes_dias debe estar entre 7 y {MAX_VENTANA_DIAS}.")
    hasta = None
    if datos.get("hasta") not in (None, ""):
        try:
            hasta = date.fromisoformat(str(datos["hasta"]))
            if hasta > hoy:
                raise ValueError
        except ValueError:
            raise ErrorApi(400, "validacion", "hasta debe ser una fecha AAAA-MM-DD que no sea futura.")
    return ventana, hasta


def periodos_medicion(fecha_implementacion, hoy, plazo_dias, ventana_antes, hasta_pedido=None):
    """Periodos de comparacion por cohorte de VENTA.

    - Antes: los `ventana_antes` dias previos a la implementacion.
    - Despues: desde la implementacion hasta `hasta` (o hoy), pero NUNCA mas
      alla de hoy menos el plazo maximo de devolucion. Lo vendido en los
      ultimos dias aun puede devolverse; contarlo haria ver mejor de lo que es.
      Si "despues" queda vacio, la medicion es sin_datos.
    El periodo "antes" no se recorta: si algo aun no madura, la tasa de antes sale
    mas baja y la meta se vuelve mas dificil, es decir, el error es conservador.
    """
    antes_hasta = fecha_implementacion - timedelta(days=1)
    antes_desde = antes_hasta - timedelta(days=ventana_antes - 1)
    tope = hoy - timedelta(days=plazo_dias)
    despues_hasta = min(hasta_pedido or hoy, tope)
    inmaduro = despues_hasta < fecha_implementacion
    return {"antes_desde": antes_desde, "antes_hasta": antes_hasta,
            "despues_desde": fecha_implementacion,
            "despues_hasta": fecha_implementacion if inmaduro else despues_hasta,
            "inmaduro": inmaduro, "madurez_hasta": tope}


def calcular_medicion(antes_vendidas, antes_devueltas, despues_vendidas, despues_devueltas,
                      meta_pct, inmaduro=False, madurez_hasta=None):
    """Veredicto de eficacia; solo 'efectiva' con muestra suficiente en ambos lados."""
    t_antes = tasa(antes_devueltas, antes_vendidas)
    t_despues = tasa(despues_devueltas, despues_vendidas)
    reduccion, motivo = None, None
    if inmaduro:
        motivo = (f"Las ventas posteriores a la implementacion aun no cumplen el plazo de "
                  f"devolucion; se puede medir con ventas hasta {madurez_hasta}.")
    elif antes_vendidas < MIN_UNIDADES:
        motivo = f"Antes hay {antes_vendidas} unidades vendidas; se requieren al menos {MIN_UNIDADES}."
    elif despues_vendidas < MIN_UNIDADES:
        motivo = f"Despues hay {despues_vendidas} unidades vendidas; se requieren al menos {MIN_UNIDADES}."
    elif not t_antes:
        motivo = "Antes no hubo devoluciones; no hay nada que reducir."
    if motivo:
        veredicto = "sin_datos"
    else:
        reduccion = round((t_antes - t_despues) / t_antes * 100.0, 2)
        veredicto = "efectiva" if reduccion >= float(meta_pct) else "no_efectiva"
    return {"antes_tasa_pct": t_antes, "despues_tasa_pct": t_despues, "reduccion_pct": reduccion,
            "veredicto": veredicto, "motivo_sin_datos": motivo}


def veredicto_global(veredictos_por_accion):
    """Veredicto de toda la investigacion a partir de la ultima medicion de cada accion.

    Una sola accion no efectiva o sin medir pesa mas que las efectivas: el cierre
    no debe esconder que algo no funciono.
    """
    if not veredictos_por_accion:
        return "sin_acciones"
    if any(v == "no_efectiva" for v in veredictos_por_accion):
        return "no_efectiva"
    if any(v in (None, "sin_datos") for v in veredictos_por_accion):
        return "sin_datos"
    return "efectiva"
