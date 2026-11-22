-- =============================================================================
-- Migracion 043: alertas de patron e investigaciones de causa raiz
-- Motivo: hoy el panel de causas (RF-23, RF-24) muestra patrones, pero nada
--   obliga a investigarlos ni deja rastro de quien concluyo que. El tercer
--   parcial pide el flujo completo (dominio 11): el sistema detecta un patron
--   raro y genera una alerta; una persona abre la investigacion, junta
--   evidencia, escribe hipotesis (5 porques, Ishikawa), las verifica y marca la
--   causa como confirmada o inconclusa. Las acciones correctivas y su medicion
--   viven en la migracion 044.
--   - alertas_patron: lo que detecta el sistema. Es solo una PROPUESTA; no abre
--     investigaciones por si sola (RN-09). Una sola alerta abierta por objeto.
--   - investigaciones: expediente con estados controlados y linea base de la
--     tasa de devolucion al abrirla, para poder comparar despues.
--   - hipotesis: 5 porques (cadena de niveles 1 a 5) o categoria de Ishikawa.
--   - evidencias_investigacion: inmutables; pueden apuntar a una devolucion.
--   - seguimiento_investigacion: linea de tiempo inmutable (RN-12).
-- Trazabilidad: RF-23, RF-24, RF-30, RN-09, RN-11, RN-12
-- Rango de migraciones de Persona 4: 040-049 (docs/PUERTOS.md)
-- =============================================================================

CREATE SEQUENCE IF NOT EXISTS seq_folio_investigacion START 1;

CREATE OR REPLACE FUNCTION fn_nuevo_folio_investigacion()
RETURNS VARCHAR AS $$
    SELECT 'INV-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
           lpad(nextval('seq_folio_investigacion')::text, 4, '0');
$$ LANGUAGE sql;

-- ----------------------------------------------------------------------------
-- Alertas que propone el sistema
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alertas_patron (
    id                  SERIAL PRIMARY KEY,
    dimension           VARCHAR(20) NOT NULL
        CHECK (dimension IN ('lote', 'proveedor', 'tienda', 'producto')),
    referencia_id       INTEGER NOT NULL,
    etiqueta            VARCHAR(200) NOT NULL,
    unidades_vendidas   INTEGER NOT NULL,
    unidades_devueltas  INTEGER NOT NULL,
    casos               INTEGER NOT NULL,
    tasa_pct            NUMERIC(7, 2) NOT NULL,
    tasa_promedio_pct   NUMERIC(7, 2) NOT NULL,
    veces_promedio      NUMERIC(7, 2) NOT NULL,
    estado              VARCHAR(20) NOT NULL DEFAULT 'abierta'
        CHECK (estado IN ('abierta', 'investigando', 'descartada')),
    comentario          VARCHAR(500),
    fecha_deteccion     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resuelta_por        INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
    CONSTRAINT ck_alerta_descartada CHECK (estado <> 'descartada' OR (comentario IS NOT NULL AND resuelta_por IS NOT NULL))
);
COMMENT ON TABLE alertas_patron IS 'Patron raro detectado por el sistema; propone una investigacion pero no la abre (RN-09).';

-- Detectar dos veces el mismo lote no duplica la alerta mientras siga abierta.
CREATE UNIQUE INDEX IF NOT EXISTS uq_alerta_abierta
    ON alertas_patron (dimension, referencia_id) WHERE estado = 'abierta';
CREATE INDEX IF NOT EXISTS idx_alertas_estado ON alertas_patron (estado, fecha_deteccion DESC);

-- ----------------------------------------------------------------------------
-- Investigaciones
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS investigaciones (
    id                    SERIAL PRIMARY KEY,
    folio                 VARCHAR(30) NOT NULL UNIQUE DEFAULT fn_nuevo_folio_investigacion(),
    alerta_id             INTEGER REFERENCES alertas_patron(id) ON DELETE RESTRICT,
    dimension             VARCHAR(20) NOT NULL
        CHECK (dimension IN ('lote', 'proveedor', 'tienda', 'producto')),
    referencia_id         INTEGER NOT NULL,
    etiqueta              VARCHAR(200) NOT NULL,
    titulo                VARCHAR(150) NOT NULL,
    descripcion           TEXT NOT NULL,
    estado                VARCHAR(20) NOT NULL DEFAULT 'abierta'
        CHECK (estado IN ('abierta', 'en_verificacion', 'concluida', 'en_accion',
                          'en_medicion', 'cerrada')),
    analista_id           INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    linea_base            JSONB NOT NULL,
    conclusion            VARCHAR(20) CHECK (conclusion IN ('causa_confirmada', 'inconclusa')),
    causa_raiz            TEXT,
    justificacion         TEXT,
    fecha_conclusion      TIMESTAMPTZ,
    cerrada_por           INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
    comentario_cierre     TEXT,
    veredicto_final       VARCHAR(20) CHECK (veredicto_final IN ('efectiva', 'no_efectiva', 'sin_datos', 'sin_acciones')),
    fecha_creacion        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_cierre          TIMESTAMPTZ,
    -- La conclusion y el cierre siempre dejan responsable y razon (RN-09, RN-12).
    CONSTRAINT ck_investigacion_conclusion CHECK (
        (estado IN ('abierta', 'en_verificacion') AND conclusion IS NULL)
     OR (estado NOT IN ('abierta', 'en_verificacion') AND conclusion IS NOT NULL
         AND justificacion IS NOT NULL AND fecha_conclusion IS NOT NULL)),
    CONSTRAINT ck_investigacion_causa CHECK (conclusion IS DISTINCT FROM 'causa_confirmada' OR causa_raiz IS NOT NULL),
    CONSTRAINT ck_investigacion_cierre CHECK (
        (estado = 'cerrada' AND cerrada_por IS NOT NULL AND comentario_cierre IS NOT NULL
         AND fecha_cierre IS NOT NULL AND veredicto_final IS NOT NULL)
     OR (estado <> 'cerrada' AND cerrada_por IS NULL AND fecha_cierre IS NULL))
);
COMMENT ON TABLE investigaciones IS 'Expediente de una investigacion de causa raiz (RF-24). El analisis apoya; la conclusion es humana (RN-09).';
COMMENT ON COLUMN investigaciones.linea_base IS 'Tasa de devolucion del objeto investigado al abrirla; no sustituye la medicion de eficacia (044).';

CREATE INDEX IF NOT EXISTS idx_investigaciones_estado ON investigaciones (estado, fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_investigaciones_objeto ON investigaciones (dimension, referencia_id);
-- Un objeto no puede tener dos investigaciones sin cerrar al mismo tiempo.
CREATE UNIQUE INDEX IF NOT EXISTS uq_investigacion_activa
    ON investigaciones (dimension, referencia_id) WHERE estado <> 'cerrada';

-- ----------------------------------------------------------------------------
-- Hipotesis, evidencias y linea de tiempo
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hipotesis (
    id                      SERIAL PRIMARY KEY,
    investigacion_id        INTEGER NOT NULL REFERENCES investigaciones(id) ON DELETE RESTRICT,
    tipo                    VARCHAR(20) NOT NULL CHECK (tipo IN ('cinco_porques', 'ishikawa', 'libre')),
    nivel                   SMALLINT CHECK (nivel BETWEEN 1 AND 5),
    padre_id                INTEGER REFERENCES hipotesis(id) ON DELETE RESTRICT,
    categoria_ishikawa      VARCHAR(20) CHECK (categoria_ishikawa IN
        ('material', 'metodo', 'maquina', 'mano_de_obra', 'medicion', 'medio_ambiente')),
    descripcion             TEXT NOT NULL,
    estado                  VARCHAR(20) NOT NULL DEFAULT 'propuesta'
        CHECK (estado IN ('propuesta', 'verificada', 'descartada')),
    resultado_verificacion  TEXT,
    verificada_por          INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_verificacion      TIMESTAMPTZ,
    creada_por              INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_creacion          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Cada tipo usa solo sus campos: los porques llevan nivel; Ishikawa, categoria.
    CONSTRAINT ck_hipotesis_tipo CHECK (
        (tipo = 'cinco_porques' AND nivel IS NOT NULL AND categoria_ishikawa IS NULL
            AND ((nivel = 1 AND padre_id IS NULL) OR (nivel > 1 AND padre_id IS NOT NULL)))
     OR (tipo = 'ishikawa' AND nivel IS NULL AND padre_id IS NULL AND categoria_ishikawa IS NOT NULL)
     OR (tipo = 'libre' AND nivel IS NULL AND padre_id IS NULL AND categoria_ishikawa IS NULL)),
    CONSTRAINT ck_hipotesis_verificada CHECK (
        (estado = 'propuesta' AND verificada_por IS NULL)
     OR (estado <> 'propuesta' AND verificada_por IS NOT NULL AND resultado_verificacion IS NOT NULL
         AND fecha_verificacion IS NOT NULL))
);
COMMENT ON TABLE hipotesis IS 'Hipotesis de causa: cadena de 5 porques, rama de Ishikawa o libre (RF-24).';
CREATE INDEX IF NOT EXISTS idx_hipotesis_investigacion ON hipotesis (investigacion_id);
-- Un porque solo puede tener una continuacion; asi la cadena no se ramifica.
CREATE UNIQUE INDEX IF NOT EXISTS uq_hipotesis_cadena
    ON hipotesis (padre_id) WHERE padre_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS evidencias_investigacion (
    id                  SERIAL PRIMARY KEY,
    investigacion_id    INTEGER NOT NULL REFERENCES investigaciones(id) ON DELETE RESTRICT,
    hipotesis_id        INTEGER REFERENCES hipotesis(id) ON DELETE RESTRICT,
    devolucion_id       INTEGER REFERENCES devoluciones(id) ON DELETE RESTRICT,
    tipo                VARCHAR(20) NOT NULL
        CHECK (tipo IN ('devolucion', 'inspeccion', 'dato', 'documento', 'nota')),
    descripcion         TEXT NOT NULL,
    referencia_externa  VARCHAR(255),
    creada_por          INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_creacion      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE evidencias_investigacion IS 'Evidencia inmutable de una investigacion; nunca se edita ni se borra (RN-12).';
CREATE INDEX IF NOT EXISTS idx_evidencias_inv ON evidencias_investigacion (investigacion_id);

CREATE TABLE IF NOT EXISTS seguimiento_investigacion (
    id                SERIAL PRIMARY KEY,
    investigacion_id  INTEGER NOT NULL REFERENCES investigaciones(id) ON DELETE RESTRICT,
    estado_anterior   VARCHAR(20),
    estado_nuevo      VARCHAR(20) NOT NULL,
    comentario        VARCHAR(500),
    usuario_id        INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE seguimiento_investigacion IS 'Linea de tiempo inmutable de cada investigacion (RN-12).';
CREATE INDEX IF NOT EXISTS idx_seguimiento_inv ON seguimiento_investigacion (investigacion_id, fecha);
