# Puente ChatGPT <-> Access V1

## Objetivo

Construir un puente completo, seguro y de solo lectura para que ChatGPT pueda consultar los datos administrativos de Cantera La Helena sin modificar Access ni el servidor productivo.

El objetivo funcional es que, una vez instalado el puente, Hugo pueda hacer preguntas desde ChatGPT como:

- "¿Cuál es el saldo de CLIENTE?"
- "¿Cuánto vendimos esta semana?"
- "¿Qué producto compra más CLIENTE?"
- "¿Qué cheques vencen en los próximos 7 días?"
- "Graficame las ventas de arena de los últimos 12 meses."
- "¿Qué clientes redujeron sus compras respecto de su promedio?"

Y recibir respuestas basadas en datos reales, sin abrir PowerShell ni Telegram.

## Principios obligatorios

1. ACCESS ES SOLO LECTURA.
   - Prohibido INSERT, UPDATE, DELETE, DDL o cualquier escritura.
   - Nunca modificar archivos .accdb/.mdb.
   - Nunca escribir en la base del servidor.

2. FUENTE.
   - Reutilizar la copia local y la lógica existente de work_v2/helena_core.
   - Antes de leer datos reales, actualizar/validar la copia local usando el mecanismo existente.
   - No inventar una segunda lógica de negocio si ya existe una consulta/servicio validado.

3. AISLAMIENTO.
   - No tocar work productivo.
   - No alterar work_v2 productivo durante el desarrollo.
   - Trabajar en la rama `asistente-access-bridge-v1`.

4. SEGURIDAD.
   - No versionar tokens, contraseñas, cadenas de conexión reales, emails privados, rutas UNC reales ni datos reales.
   - Toda credencial debe entrar por variables de entorno o archivo privado ignorado por Git.
   - El puente debe requerir autenticación.

5. AUTONOMÍA.
   - Resolver por cuenta propia decisiones técnicas que puedan deducirse del repositorio.
   - No pedir a Hugo que ejecute pruebas intermedias.
   - No detenerse por problemas corregibles técnicamente.
   - Sólo detenerse si hace falta una credencial real, una acción física en Windows/Access o una decisión funcional no definida.

## Arquitectura elegida para V1

La V1 debe usar una **réplica de lectura en PostgreSQL cloud** como capa consultable desde ChatGPT.

Motivo: ChatGPT no puede abrir directamente un archivo Access situado en una PC Windows. La forma más corta y robusta es sincronizar, en una sola dirección, datos desde la copia local Access hacia una base PostgreSQL dedicada de lectura. ChatGPT podrá consultar esa réplica mediante un conector PostgreSQL compatible.

Flujo:

```text
Access servidor (solo origen)
        |
        v
actualizar_copia_base.ps1
        |
        v
Copia local Access
        |
        v
sync_access_readonly.py / servicios existentes
        |
        v
PostgreSQL cloud (réplica de consulta)
        |
        v
ChatGPT
```

Nunca existe flujo inverso PostgreSQL -> Access.

## Alcance funcional V1

### A. Inventario de datos

Detectar y documentar:
- tablas disponibles;
- claves primarias cuando existan;
- relaciones inferibles/confirmadas por scripts existentes;
- campos relevantes;
- tablas sensibles que no deban replicarse.

No exportar datos reales al repositorio.

### B. Sincronizador local read-only

Crear un sincronizador ejecutable en Windows que:
- valide/actualice la copia local;
- abra Access exclusivamente en modo lectura;
- extraiga datos necesarios;
- sincronice a PostgreSQL en una sola dirección;
- use UPSERT en PostgreSQL sin tocar Access;
- soporte sincronización completa inicial e incremental cuando sea posible;
- registre fecha/hora, cantidad de filas y errores técnicos;
- falle de forma segura sin afectar Access;
- no incluya secretos en logs.

Preferir Python y reutilizar utilidades/contratos existentes. Si el acceso Access ya está resuelto mejor mediante PowerShell/ADO en el repositorio, reutilizar ese mecanismo en lugar de introducir otro driver sin necesidad.

### C. Esquema PostgreSQL de consulta

Crear migraciones SQL versionadas para una réplica orientada a consulta.

Debe incluir como mínimo la información necesaria para:
- clientes;
- saldos/cuenta corriente;
- comprobantes/facturas/remitos;
- detalle de comprobantes y productos;
- productos/materiales;
- pagos/cobranzas;
- cheques/eCheq;
- proveedores/gastos sólo si ya existe lectura validada y no expone información que deba quedar fuera.

Mantener nombres estables y documentar mapeos Access -> PostgreSQL.

### D. Capa semántica de solo lectura

Crear vistas SQL o funciones read-only para las preguntas frecuentes, reutilizando reglas existentes:
- saldo cliente;
- mayores deudores;
- ventas por período;
- ventas por producto/categoría;
- producto más comprado por cliente;
- última compra;
- frecuencia de compra;
- cheques/eCheq por vencimiento;
- IVA estimado si la lógica existente puede preservarse correctamente;
- cobranza;
- resumen gerencial básico.

No duplicar reglas comerciales si ya están implementadas en helena_core/scripts.

### E. Analítica para el futuro asistente

Preparar consultas/vistas base para:
- top productos;
- evolución mensual/semanal;
- ticket promedio por cliente;
- recencia/frecuencia/valor por cliente;
- productos habituales por cliente;
- caída de compras respecto del promedio histórico;
- anomalías simples;
- datos listos para gráficos.

No implementar todavía modelos ML complejos. La V1 debe dejar datos confiables y consultables.

### F. Servicio local opcional de diagnóstico

Agregar un comando local de diagnóstico que permita comprobar:
- copia Access accesible;
- conexión PostgreSQL accesible;
- sync inicial/incremental;
- conteos por tabla;
- modo read-only confirmado;
- timestamp del último sync.

### G. Configuración

Crear sólo ejemplos sanitizados:
- `config/bridge.example.json` o equivalente;
- `.env.example` si se necesita.

Nunca agregar credenciales reales.

### H. Tests

Agregar tests que prueben:
- nunca se emiten operaciones de escritura contra Access;
- errores de sync no modifican Access;
- mapeos de datos;
- UPSERT sólo ocurre en PostgreSQL;
- consultas/vistas esperadas;
- configuración sin secretos;
- compatibilidad con Windows paths;
- reuso de reglas existentes donde corresponda.

Ejecutar todas las pruebas posibles en Cloud y documentar las que requieran Windows/Access real.

## Criterio de terminado

La tarea NO termina con "código preparado".

Debe entregar un candidato completo que requiera de Hugo únicamente las acciones inevitables de instalación/conexión local.

Antes de pedir intervención humana, Codex debe haber:

1. implementado todos los archivos necesarios;
2. revisado el diff completo;
3. ejecutado tests disponibles;
4. corregido autónomamente sus fallos;
5. documentado instalación automatizada;
6. preparado un único script de instalación Windows;
7. preparado un único script de validación end-to-end;
8. preparado una única secuencia de rollback/desinstalación;
9. dejado PR listo contra la rama base correspondiente.

## Instalación final esperada

El instalador final debe hacer, con mínima intervención:
- verificar Python/PowerShell necesarios;
- crear entorno/config local sin sobrescribir secretos existentes;
- solicitar o detectar únicamente la credencial cloud que no pueda existir en Git;
- validar Access local en lectura;
- ejecutar sync inicial;
- comprobar PostgreSQL;
- dejar sincronización automática instalada;
- mostrar un resultado final claro.

No debe pedir a Hugo editar archivos manualmente.

## Resultado final obligatorio de Codex

Al terminar, devolver únicamente un informe ejecutivo con:

- ARQUITECTURA IMPLEMENTADA
- ARCHIVOS CREADOS/MODIFICADOS
- PRUEBAS CLOUD
- LIMITACIONES REALES RESTANTES
- ACCIÓN ÚNICA QUE DEBE HACER HUGO (si existe)
- COMANDO/INSTALADOR ÚNICO PARA WINDOWS
- PR CREADO
- LISTO_PARA_INSTALAR_LOCALMENTE: SI/NO

No declarar listo si todavía faltan decisiones técnicas que Codex pueda resolver por sí mismo.
