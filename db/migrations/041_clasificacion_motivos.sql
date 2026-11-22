-- =============================================================================
-- Migracion 041: categorias, submotivos con versiones y revision humana
-- Motivo: el catalogo plano `motivos` (001) no distingue si la falla fue del
--   producto, del empaque, del transporte, un error comercial o mal uso del
--   cliente, y esa distincion es la base del analisis de causa raiz. Se agrega:
--   - categorias_motivo y submotivos (dominio 10 del tercer parcial). Cada
--     submotivo puede apuntar a un motivo existente (motivo_id) sin cambiarlo:
--     las devoluciones ya registradas siguen validas.
--   - submotivos_versiones: cada cambio del catalogo crea una version y la
--     anterior se conserva, para saber con que criterio se clasifico un caso
--     en una fecha dada. Nunca se edita ni se borra.
--   - clasificaciones_motivo: la sugerencia automatica por palabras clave es
--     solo una propuesta; queda "pendiente" hasta que una persona la confirme,
--     corrija o descarte (RN-11). Registra quien revisó y con que version.
--   Los submotivos iniciales viven aqui y no en un seed opcional porque son
--   parte del contrato del servicio, igual que los roles (008).
-- Trazabilidad: RF-22, RN-09, RN-11, RN-12, RF-30
-- Rango de migraciones de Persona 4: 040-049 (docs/PUERTOS.md)
-- =============================================================================

CREATE TABLE IF NOT EXISTS categorias_motivo (
    id          SERIAL PRIMARY KEY,
    codigo      VARCHAR(30)  NOT NULL UNIQUE,
    nombre      VARCHAR(80)  NOT NULL,
    descripcion VARCHAR(255)
);
COMMENT ON TABLE categorias_motivo IS 'Origen de la falla: producto, empaque, transporte, error comercial o mal uso (RF-22).';

CREATE TABLE IF NOT EXISTS submotivos (
    id             SERIAL PRIMARY KEY,
    categoria_id   INTEGER NOT NULL REFERENCES categorias_motivo(id) ON DELETE RESTRICT,
    motivo_id      INTEGER REFERENCES motivos(id) ON DELETE RESTRICT,
    codigo         VARCHAR(40)  NOT NULL UNIQUE,
    nombre         VARCHAR(100) NOT NULL,
    descripcion    VARCHAR(255),
    palabras_clave TEXT[] NOT NULL DEFAULT '{}',
    version        INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    activo         BOOLEAN NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE submotivos IS 'Catalogo de submotivos; version sube con cada cambio y el historial vive en submotivos_versiones (RF-22).';
COMMENT ON COLUMN submotivos.palabras_clave IS 'Palabras sin acentos y en minusculas con las que se sugiere la clasificacion; la sugerencia nunca se aplica sola (RN-11).';

CREATE TABLE IF NOT EXISTS submotivos_versiones (
    id             SERIAL PRIMARY KEY,
    submotivo_id   INTEGER NOT NULL REFERENCES submotivos(id) ON DELETE RESTRICT,
    version        INTEGER NOT NULL,
    nombre         VARCHAR(100) NOT NULL,
    descripcion    VARCHAR(255),
    palabras_clave TEXT[] NOT NULL DEFAULT '{}',
    motivo_id      INTEGER,
    activo         BOOLEAN NOT NULL,
    cambiado_por   INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
    motivo_cambio  VARCHAR(255) NOT NULL,
    fecha          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (submotivo_id, version)
);
COMMENT ON TABLE submotivos_versiones IS 'Historial inmutable de cada version de un submotivo (RF-22, RN-12).';

CREATE TABLE IF NOT EXISTS clasificaciones_motivo (
    id                    SERIAL PRIMARY KEY,
    devolucion_id         INTEGER NOT NULL REFERENCES devoluciones(id) ON DELETE RESTRICT,
    submotivo_sugerido_id INTEGER REFERENCES submotivos(id) ON DELETE RESTRICT,
    version_sugerida      INTEGER,
    puntaje               INTEGER NOT NULL DEFAULT 0,
    coincidencias         JSONB NOT NULL DEFAULT '[]',
    estado                VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'confirmada', 'corregida', 'descartada')),
    submotivo_final_id    INTEGER REFERENCES submotivos(id) ON DELETE RESTRICT,
    version_final         INTEGER,
    revisado_por          INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_revision        TIMESTAMPTZ,
    comentario            VARCHAR(500),
    creado_por            INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_creacion        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Una clasificacion definitiva siempre tiene responsable y submotivo (RN-11).
    CONSTRAINT ck_clasificacion_revisada CHECK (
        (estado = 'pendiente' AND revisado_por IS NULL AND submotivo_final_id IS NULL)
     OR (estado = 'descartada' AND revisado_por IS NOT NULL)
     OR (estado IN ('confirmada', 'corregida')
         AND revisado_por IS NOT NULL AND submotivo_final_id IS NOT NULL))
);
COMMENT ON TABLE clasificaciones_motivo IS 'Sugerencia de submotivo y su revision humana. No modifica la devolucion (RN-11).';

-- Una sola sugerencia en espera por devolucion, aunque dos personas la pidan a la vez.
CREATE UNIQUE INDEX IF NOT EXISTS uq_clasificacion_pendiente
    ON clasificaciones_motivo (devolucion_id) WHERE estado = 'pendiente';
CREATE INDEX IF NOT EXISTS idx_clasificaciones_estado
    ON clasificaciones_motivo (estado, fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_submotivos_categoria ON submotivos (categoria_id);

-- ----------------------------------------------------------------------------
-- Datos iniciales
-- ----------------------------------------------------------------------------
INSERT INTO categorias_motivo (codigo, nombre, descripcion) VALUES
    ('falla_producto',  'Falla del producto',  'El producto salio de fabrica o del proveedor con un defecto'),
    ('empaque',         'Empaque',             'El envase o empaque no protegio el producto'),
    ('transporte',      'Transporte',          'El dano ocurrio durante el traslado o la cadena de frio'),
    ('error_comercial', 'Error comercial',     'Se entrego, etiqueto o cobro algo distinto a lo pactado'),
    ('mal_uso',         'Mal uso',             'El problema se origino en el manejo posterior a la entrega')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO submotivos (categoria_id, motivo_id, codigo, nombre, descripcion, palabras_clave)
SELECT c.id,
       (SELECT m.id FROM motivos m WHERE m.nombre = v.motivo ORDER BY m.id LIMIT 1),
       v.codigo, v.nombre, v.descripcion, v.palabras
  FROM (VALUES
    ('falla_producto',  'Calidad inferior',      'mal_olor_sabor',     'Mal olor o sabor',            'Olor, sabor o textura fuera de lo normal',
        ARRAY['olor','sabor','rancio','podrido','textura','agrio']::text[]),
    ('falla_producto',  'Caducidad vencida',     'caducado',           'Caducado o proximo a vencer', 'Fecha de caducidad vencida al recibirlo',
        ARRAY['caduc','vencido','expirado','fecha de caducidad']::text[]),
    ('falla_producto',  'Calidad inferior',      'contaminacion',      'Contaminacion o cuerpo extrano', 'Moho, insectos u objetos dentro del producto',
        ARRAY['moho','hongo','insecto','cuerpo extrano','pelo','contaminad']::text[]),
    ('empaque',         'Producto danado',       'empaque_roto',       'Empaque roto o derramado',    'Envase abierto, roto o con fuga',
        ARRAY['roto','derrame','fuga','abierto','abollado','rasgado']::text[]),
    ('empaque',         'Producto danado',       'sello_danado',       'Sello o tapa danada',         'Sello de seguridad o tapa en mal estado',
        ARRAY['sello','tapa','sin sello','inflado']::text[]),
    ('transporte',      'Cadena de frio rota',   'cadena_frio',        'Cadena de frio rota',         'Producto refrigerado que llego tibio o descongelado',
        ARRAY['caliente','tibio','temperatura','descongelado','refriger','frio']::text[]),
    ('transporte',      'Producto danado',       'golpe_traslado',     'Golpe durante el traslado',   'Producto aplastado o golpeado en el transporte',
        ARRAY['aplastado','golpe','maltratado','transporte','caja mojada']::text[]),
    ('error_comercial', 'Error en el pedido',    'producto_equivocado','Producto equivocado',         'Se entrego un producto distinto al pedido',
        ARRAY['equivocado','distinto','incorrecto','otro producto','no pedi']::text[]),
    ('error_comercial', 'Etiqueta incorrecta',   'etiqueta_precio',    'Etiqueta o precio incorrecto','La etiqueta o el precio no corresponden',
        ARRAY['etiqueta','precio','rotulo','informacion incorrecta']::text[]),
    ('error_comercial', 'Error en el pedido',    'cantidad_incorrecta','Cantidad incorrecta',         'Faltaron unidades o llegaron de mas',
        ARRAY['faltante','falto','incompleto','de menos','de mas']::text[]),
    ('mal_uso',         NULL,                    'almacenamiento_cliente','Almacenamiento inadecuado','El cliente no conservo el producto como indica la etiqueta',
        ARRAY['deje fuera','no lo guarde','mala conservacion','al sol']::text[]),
    ('mal_uso',         NULL,                    'uso_indebido',       'Uso fuera de instrucciones',  'Uso distinto al indicado por el fabricante',
        ARRAY['no segui','instrucciones','uso incorrecto','mal uso']::text[])
  ) AS v(cat, motivo, codigo, nombre, descripcion, palabras)
  JOIN categorias_motivo c ON c.codigo = v.cat
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO submotivos_versiones (submotivo_id, version, nombre, descripcion, palabras_clave,
                                  motivo_id, activo, motivo_cambio)
SELECT s.id, 1, s.nombre, s.descripcion, s.palabras_clave, s.motivo_id, s.activo, 'Catalogo inicial'
  FROM submotivos s
 WHERE NOT EXISTS (SELECT 1 FROM submotivos_versiones sv
                    WHERE sv.submotivo_id = s.id AND sv.version = 1);
