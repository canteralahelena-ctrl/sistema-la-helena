# Codex task: construir puente ChatGPT <-> Access V1

Implementar completamente la especificación de `docs/PUENTE_CHATGPT_ACCESS_V1.md` en esta rama.

Reglas adicionales:
- No pedir intervención humana durante análisis, implementación, tests o correcciones.
- No tocar `work` ni `work_v2` productivos.
- Access debe ser estrictamente solo lectura.
- No versionar secretos ni datos reales.
- Reutilizar `helena_core` y scripts existentes cuando exista lógica validada.
- Construir código completo, tests, instalador Windows único, validación end-to-end y rollback.
- Corregir autónomamente fallos encontrados en tests.
- No detenerse por decisiones técnicas deducibles del repositorio.
- Terminar únicamente cuando quede `LISTO_PARA_INSTALAR_LOCALMENTE: SI` o exista un bloqueo físico real imposible de resolver sin la PC/credencial externa del usuario.

Resultado final: actualizar este PR con toda la implementación y un resumen ejecutivo según la especificación.