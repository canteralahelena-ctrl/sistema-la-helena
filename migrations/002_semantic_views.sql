CREATE OR REPLACE VIEW replica.v_saldos_clientes AS
SELECT c.id_cliente, c.razon_social,
       COALESCE(v.debe, 0) - COALESCE(p.haber, 0) AS saldo
FROM replica.clientes c
LEFT JOIN (SELECT id_cliente, sum(saldo) debe FROM replica.comprobantes GROUP BY id_cliente) v USING (id_cliente)
LEFT JOIN (SELECT CASE WHEN id_cliente_texto ~ '^[0-9]+$' THEN id_cliente_texto::bigint END id_cliente,
                  sum(saldo) haber FROM replica.pagos GROUP BY 1) p USING (id_cliente);

CREATE OR REPLACE VIEW replica.v_mayores_deudores AS
SELECT * FROM replica.v_saldos_clientes WHERE saldo > 0 ORDER BY saldo DESC;

CREATE OR REPLACE VIEW replica.v_ventas AS
SELECT c.id_comprobante, c.fecha, c.tipo, c.numero, c.id_cliente, cl.razon_social,
       c.subtotal, c.iva, c.importe
FROM replica.comprobantes c LEFT JOIN replica.clientes cl USING (id_cliente)
WHERE COALESCE(upper(c.tipo), '') NOT LIKE 'NC%';

CREATE OR REPLACE VIEW replica.v_ventas_producto AS
SELECT c.id_cliente, cl.razon_social, c.fecha, d.producto, d.unidad,
       d.cantidad, d.subtotal, c.id_comprobante
FROM replica.comprobantes c JOIN replica.comprobante_detalles d USING (id_comprobante)
LEFT JOIN replica.clientes cl USING (id_cliente)
WHERE COALESCE(upper(c.tipo), '') NOT LIKE 'NC%';

CREATE OR REPLACE VIEW replica.v_cliente_metricas AS
SELECT c.id_cliente, c.razon_social, max(v.fecha) ultima_compra,
       count(DISTINCT v.id_comprobante) frecuencia,
       COALESCE(sum(v.importe),0) valor_total,
       COALESCE(avg(v.importe),0) ticket_promedio
FROM replica.clientes c LEFT JOIN replica.v_ventas v USING (id_cliente)
GROUP BY c.id_cliente, c.razon_social;

CREATE OR REPLACE VIEW replica.v_productos_habituales_cliente AS
SELECT id_cliente, razon_social, producto, sum(cantidad) cantidad, sum(subtotal) importe,
       rank() OVER (PARTITION BY id_cliente ORDER BY sum(cantidad) DESC NULLS LAST) posicion
FROM replica.v_ventas_producto GROUP BY id_cliente, razon_social, producto;

CREATE OR REPLACE VIEW replica.v_ventas_mensuales AS
SELECT date_trunc('month', fecha)::date periodo, producto, sum(cantidad) cantidad, sum(subtotal) importe
FROM replica.v_ventas_producto GROUP BY 1, producto;

CREATE OR REPLACE VIEW replica.v_ventas_semanales AS
SELECT date_trunc('week', fecha)::date periodo, sum(importe) importe, count(*) comprobantes
FROM replica.v_ventas GROUP BY 1;

CREATE OR REPLACE VIEW replica.v_caida_compras AS
WITH mensual AS (
 SELECT id_cliente, date_trunc('month', fecha)::date mes, sum(importe) importe
 FROM replica.v_ventas GROUP BY 1,2
), medidas AS (
 SELECT id_cliente, avg(importe) FILTER (WHERE mes < date_trunc('month', current_date)) promedio_historico,
        sum(importe) FILTER (WHERE mes = date_trunc('month', current_date)) mes_actual
 FROM mensual GROUP BY id_cliente
)
SELECT m.id_cliente, c.razon_social, m.promedio_historico, COALESCE(m.mes_actual,0) mes_actual,
       COALESCE(m.mes_actual,0) - m.promedio_historico variacion
FROM medidas m JOIN replica.clientes c USING (id_cliente)
WHERE COALESCE(m.mes_actual,0) < m.promedio_historico;

CREATE OR REPLACE VIEW replica.v_cheques_vencimiento AS
SELECT e.*, c.razon_social, (e.fecha_cobro::date - current_date) dias_restantes
FROM replica.entregas e LEFT JOIN replica.clientes c USING (id_cliente)
WHERE e.estado = 'EN CAJA' AND upper(e.tipo) IN ('CHEQUE','CHEQUE FISICO','CHEQUE FÍSICO','ECHEQ','E-CHEQ','ECHEQUE','E-CHEQUE','ECHQ');

CREATE OR REPLACE VIEW replica.v_cobranzas AS
SELECT p.*, c.id_cliente, c.razon_social FROM replica.pagos p
LEFT JOIN replica.clientes c ON p.id_cliente_texto ~ '^[0-9]+$' AND p.id_cliente_texto::bigint = c.id_cliente;

CREATE OR REPLACE VIEW replica.v_resumen_gerencial AS
SELECT current_date fecha,
 (SELECT COALESCE(sum(importe),0) FROM replica.v_ventas WHERE fecha >= date_trunc('month', current_date)) ventas_mes,
 (SELECT COALESCE(sum(monto),0) FROM replica.pagos WHERE fecha >= date_trunc('month', current_date)) cobranzas_mes,
 (SELECT COALESCE(sum(saldo),0) FROM replica.v_saldos_clientes WHERE saldo > 0) deuda_clientes,
 (SELECT COALESCE(sum(importe),0) FROM replica.v_cheques_vencimiento) cheques_en_cartera;

GRANT SELECT ON ALL TABLES IN SCHEMA replica TO helena_bridge_reader;
