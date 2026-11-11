# fhir/

Artefactos HL7 FHIR R4 del proyecto. **Se generan con el mismo código que usa el sistema** (`scripts/generar_ejemplos_fhir.sh`), no se escriben a mano.

| Archivo | Qué es |
|---|---|
| `ejemplos/01_adt_a01_transaction.json` | Mensaje HL7 v2 `ADT^A01` del parcial (`ejemplos/01_…hl7`) convertido por el HSB a un Bundle `transaction`: `Patient`, `Practitioner`, `Encounter` y `Condition` (CIE-10 J45.9), con `PUT` e ids deterministas (`pac-1007`, `enc-2-V-S2-0101`, …) para que reenviar no duplique |
| `ejemplos/02_oru_r01_transaction.json` | `ORU^R01` con una `Observation` LOINC 718-7 = 13,8 g/dL (UCUM) |
| `ejemplos/04_csv_sede3_transaction.json` | Primera fila válida del CSV legado de la sede 3: el diagnóstico local pasa a CIE-10 con `ref_terminologia` |
| `ejemplos/dx_local_conceptmap.json` | `ConceptMap` diagnóstico local → CIE-10 (también en `GET /hsb/terminologia/conceptmap`) |
| `ejemplos/rda_document.json` | El RDA (Reporte de Detalle de Atención) de un encuentro sintético como Bundle `document` con `Composition` primero, tal como lo genera la API |
| `ejemplos/rda_transaction.json` | Los mismos recursos del RDA como **recursos propios** de HAPI: Bundle `transaction` con `PUT` e ids deterministas (`pac-<documento>`, `enc-<sede>-<encuentro>`, `cond-…`, `obs-…`), como los sube la API al migrar un encuentro |
| `validar.sh` | Pasa cada Bundle por `Bundle/$validate` de HAPI y resume el `OperationOutcome` |

El código que los produce está en `hsb/hc_hsb/fhir.py` (Bundle `transaction` del bus) y `app/hc_api/fhir.py` (RDA `document` y recursos). Los mensajes de entrada están en `ejemplos/` (contrato del parcial, sin modificar).
