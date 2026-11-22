-- =============================================================================
-- Migracion 040: numeros de serie por lote
-- Motivo: el tercer parcial pide que de cada producto se pueda saber su lote,
--   SERIE, proveedor, tienda, venta y recorrido. Hasta ahora solo existia el
--   lote (001); la unidad individual no se podia identificar. Una serie
--   pertenece a un lote y, cuando se vende, apunta a la linea de venta
--   (venta_detalle), de donde se llega a tienda, cliente y devolucion.
--   numero_serie es UNIQUE global: un mismo numero no puede identificar dos
--   unidades fisicas distintas, ni siquiera de lotes diferentes.
--   venta_detalle_id es NULL mientras la unidad sigue en almacen.
-- Trazabilidad: RF-05, RF-23, RF-24, RN-10 (tercer parcial: dominio 9,
--   lotes-trazabilidad, agrupado en ventas-catalogos 8006)
-- Rango de migraciones de Persona 4: 040-049 (docs/PUERTOS.md)
-- =============================================================================

CREATE TABLE IF NOT EXISTS series_producto (
    id                SERIAL PRIMARY KEY,
    lote_id           INTEGER NOT NULL REFERENCES lotes(id) ON DELETE RESTRICT,
    numero_serie      VARCHAR(60) NOT NULL UNIQUE,
    venta_detalle_id  INTEGER REFERENCES venta_detalle(id) ON DELETE RESTRICT,
    fecha_registro    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activo            BOOLEAN NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE series_producto IS 'Unidad individual de un lote, con su numero de serie (RF-05, RF-24). venta_detalle_id NULL = aun no vendida.';

CREATE INDEX IF NOT EXISTS idx_series_lote    ON series_producto (lote_id);
CREATE INDEX IF NOT EXISTS idx_series_detalle ON series_producto (venta_detalle_id)
    WHERE venta_detalle_id IS NOT NULL;

-- Las tasas por proveedor/ruta/tienda recorren recolecciones por ruta.
CREATE INDEX IF NOT EXISTS idx_recolecciones_ruta ON recolecciones (ruta_id);
