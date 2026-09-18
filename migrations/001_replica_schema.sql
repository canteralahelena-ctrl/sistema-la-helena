CREATE SCHEMA IF NOT EXISTS replica;

CREATE TABLE IF NOT EXISTS replica.clientes (
  id_cliente bigint PRIMARY KEY, razon_social text, cuit text, localidad text
);
CREATE TABLE IF NOT EXISTS replica.productos (
  id_producto bigint PRIMARY KEY, producto text, unidad text, precio_unitario numeric(18,4)
);
CREATE TABLE IF NOT EXISTS replica.comprobantes (
  id_comprobante bigint PRIMARY KEY, id_cliente bigint, fecha timestamp, tipo text,
  numero text, subtotal numeric(18,2), iva numeric(18,2), importe numeric(18,2), saldo numeric(18,2)
);
CREATE TABLE IF NOT EXISTS replica.comprobante_detalles (
  id_detalle bigint PRIMARY KEY, id_comprobante bigint, producto text, unidad text,
  cantidad numeric(18,4), precio_unitario numeric(18,4), subtotal numeric(18,2)
);
CREATE TABLE IF NOT EXISTS replica.pagos (
  id_pago bigint PRIMARY KEY, id_cliente_texto text, fecha timestamp, monto numeric(18,2), tipo text, saldo numeric(18,2)
);
CREATE TABLE IF NOT EXISTS replica.entregas (
  id_entrega bigint PRIMARY KEY, id_pago bigint, id_cliente bigint, tipo text, estado text,
  banco text, numero text, fecha_cobro timestamp, importe numeric(18,2), observacion text
);
CREATE TABLE IF NOT EXISTS replica.sync_runs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, started_at timestamptz NOT NULL,
  finished_at timestamptz, status text NOT NULL, source_fingerprint text, row_counts jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Access histórico admite descripciones incompletas; la réplica conserva esos NULL sin inventar datos.
ALTER TABLE replica.clientes ALTER COLUMN razon_social DROP NOT NULL;
ALTER TABLE replica.productos ALTER COLUMN producto DROP NOT NULL;
CREATE INDEX IF NOT EXISTS ix_comprobantes_cliente_fecha ON replica.comprobantes(id_cliente, fecha);
CREATE INDEX IF NOT EXISTS ix_detalles_comprobante ON replica.comprobante_detalles(id_comprobante);
CREATE INDEX IF NOT EXISTS ix_pagos_cliente_fecha ON replica.pagos(id_cliente_texto, fecha);
CREATE INDEX IF NOT EXISTS ix_entregas_vencimiento ON replica.entregas(fecha_cobro) WHERE estado = 'EN CAJA';

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'helena_bridge_reader') THEN
    CREATE ROLE helena_bridge_reader NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA replica TO helena_bridge_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA replica TO helena_bridge_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA replica GRANT SELECT ON TABLES TO helena_bridge_reader;
