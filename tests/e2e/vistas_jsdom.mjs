// Carga las vistas nuevas (reporte de HC, accesos del paciente, bus del admisionista, estado de la plataforma) en jsdom contra el gateway,
// sin navegador, y lee lo que pintan. Las sesiones llegan por variables de entorno (las crea scripts/prueba_vistas.sh). No sustituye al E2E de
// Chromium (tests/e2e/test_vistas.py): no mide estilos ni accesibilidad, solo que cada vista llame a la API y pinte lo esperado.
import { JSDOM } from 'jsdom';
import vm from 'node:vm';
import fs from 'node:fs';
const BASE = process.env.BASE, ESTATICO = '/static', DOC = process.env.DOC;
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
async function cargar(pagina, rol, tokenVar) {
  const html = fs.readFileSync(`${ESTATICO}/${pagina}.html`, 'utf8').replace(/<script[\s\S]*?<\/script>/g, '');
  const dom = new JSDOM(html, { url: `${BASE}/sede/1/vistas/${pagina}.html`, pretendToBeVisual: true, runScripts: 'outside-only' });
  const w = dom.window;
  w.fetch = (u, o) => fetch(u, o);
  Object.defineProperty(w, 'crypto', { value: globalThis.crypto });
  w.TextEncoder = TextEncoder;
  w.print = () => { w.__imprimio = true; };
  w.sessionStorage.setItem('hc_sesion', JSON.stringify({ token: process.env[tokenVar], usuario: { usuario: rol, rol, nombre: rol }, expira: Date.now() + 3600e3 }));
  const ctx = dom.getInternalVMContext();
  new vm.Script(fs.readFileSync(`${ESTATICO}/comun.js`, 'utf8')).runInContext(ctx);
  const m = fs.readFileSync(`${ESTATICO}/${pagina}.html`, 'utf8').match(/<script type="module">([\s\S]*?)<\/script>/)[1];
  const p = new vm.Script(`(async () => {${m}})().catch((e) => { window.__error = String(e && e.stack || e); })`).runInContext(ctx);
  return { w, p };
}
const texto = (w, sel) => (w.document.querySelector(sel)?.textContent || '').replace(/\s+/g, ' ').trim();
let fallos = 0;
const ok = (c, msg, extra = '') => { console.log(`  ${c ? 'OK   ' : 'FALLA'} ${msg}${c ? '' : ' → ' + extra}`); if (!c) fallos++; };

console.log('== Inicio: las sedes se pintan como insignias (no como «[object HTMLSpanElement]»)');
{ const { w } = await cargar('index', 'medico', 'TOK_MEDICO'); await esperar(3000);
  const t = texto(w, '#sedes'); ok(w.__error === undefined, 'el script de la vista corre sin errores', w.__error);
  ok(/Sincelejo/.test(t) && /Cartagena/.test(t) && !/object/i.test(t), 'las tres sedes salen como texto', t); }

console.log('== Admisionista: tabla de mensajes del bus');
{ const { w } = await cargar('admision', 'admisionista', 'TOK_ADMISION'); await esperar(4000);
  const t = texto(w, '#bus-tabla'); ok(w.__error === undefined, 'el script de la vista corre sin errores', w.__error);
  ok(/entregado|rechazado|muerto|Todavía no/.test(t), 'pinta la tabla del bus', t.slice(0, 120)); ok(!/\bCSV CSV\b/i.test(t), 'la columna Formato no repite el tipo (CSV, no «CSV CSV»)', t.slice(0, 160)); ok(/mensajes/.test(texto(w, '#bus-resumen')), 'muestra el resumen por estado', texto(w, '#bus-resumen')); console.log('    ', texto(w, '#bus-resumen').slice(0, 110)); }

console.log('== Médico: estado de la plataforma');
{ const { w } = await cargar('medico', 'medico', 'TOK_MEDICO'); await esperar(5000);
  const t = texto(w, '#plataforma'); ok(w.__error === undefined, 'el script de la vista corre sin errores', w.__error);
  ok(/Sincelejo/.test(t) && /Auditoría íntegra/.test(t) && /Base de datos ✓/.test(t), 'sedes, base y auditoría', t); console.log('    ', t.slice(0, 200)); }

console.log('== Paciente: quién accedió a mi historia');
{ const { w } = await cargar('paciente', 'paciente', 'TOK_PACIENTE'); await esperar(5000);
  ok(w.__error === undefined, 'el script de la vista corre sin errores', w.__error);
  ok(!w.document.querySelector('#s-accesos').hidden, 'la tarjeta de accesos se muestra'); const t = texto(w, '#mis-accesos');
  ok(/reportero|medico|admision/.test(t), 'lista quién accedió', t.slice(0, 150)); console.log('    ', t.slice(0, 160)); }

console.log('== Reportero: reporte de HC, sello, estado');
{ const { w } = await cargar('reportes', 'reportero', 'TOK_REPORTERO'); await esperar(4000);
  ok(w.__error === undefined, 'el script de la vista corre sin errores', w.__error);
  ok(/Auditoría íntegra|Base de datos/.test(texto(w, '#estado-plataforma')), 'estado de la plataforma', texto(w, '#estado-plataforma'));
  ok(/cadena íntegra/.test(texto(w, '#integridad')), 'verificación de la cadena de auditoría', texto(w, '#integridad'));
  ok(/Anclaje de la cabeza en las otras sedes/.test(texto(w, '#integridad')), 'muestra el anclaje en las otras sedes', texto(w, '#integridad'));
  w.document.querySelector('#rep-num').value = DOC;
  w.document.querySelector('#f-reporte').dispatchEvent(new w.Event('submit', { cancelable: true })); await esperar(5000);
  const r = texto(w, '#reporte-hc'); ok(r.includes(DOC) && /campos completos/.test(r) && /Sede Sincelejo/.test(r) && /I10/.test(r), 'reporte con sedes, cobertura y diagnóstico', r.slice(0, 200));
  ok(/campos por completar/i.test(r), 'lista de campos faltantes'); console.log('    ', r.slice(0, 220));
  const boton = (t) => [...w.document.querySelectorAll('#reporte-hc button')].find((b) => b.textContent.includes(t));
  boton('Comprobar sello').click(); await esperar(800); ok(/coincide/.test(texto(w, '#rep-comprobacion')) && !/NO coincide/.test(texto(w, '#rep-comprobacion')), 'el sello se recalcula en el navegador y coincide', texto(w, '#rep-comprobacion'));
  boton('Imprimir').click(); ok(w.__imprimio === true, 'el botón de imprimir llama a print()');
  ok(!!boton('Descargar el reporte'), 'hay descarga del reporte en JSON');
  ok(!boton('Descargar Bundle'), 'un encuentro sin migrar a FHIR no ofrece descargar el Bundle');
  // un documento que no existe
  w.document.querySelector('#rep-num').value = 'NOEXISTE999'; w.document.querySelector('#f-reporte').dispatchEvent(new w.Event('submit', { cancelable: true })); await esperar(2500);
  ok(/No hay un paciente/.test(texto(w, '#reporte-hc')), 'documento inexistente: mensaje claro', texto(w, '#reporte-hc')); }
console.log('== Reporte de HC como médico: genera el de cualquier paciente, sin las tarjetas del reportero');
{ const { w } = await cargar('reportes', 'medico', 'TOK_MEDICO'); await esperar(3500);
  ok(w.__error === undefined, 'el script de la vista corre sin errores', w.__error);
  ok(w.document.querySelector('#s-cobertura').hidden && w.document.querySelector('#s-accesos').hidden, 'las tarjetas de cobertura y accesos (del reportero) están ocultas');
  ok(/Auditoría íntegra|Base de datos/.test(texto(w, '#estado-plataforma')), 've el tablero de estado', texto(w, '#estado-plataforma'));
  w.document.querySelector('#rep-num').value = DOC; w.document.querySelector('#f-reporte').dispatchEvent(new w.Event('submit', { cancelable: true })); await esperar(5000);
  ok(texto(w, '#reporte-hc').includes(DOC) && /campos completos/.test(texto(w, '#reporte-hc')), 'genera el reporte', texto(w, '#reporte-hc').slice(0, 120)); }

console.log('== Reporte de HC como paciente: se genera solo y es el suyo');
{ const { w } = await cargar('reportes', 'paciente', 'TOK_PACIENTE'); await esperar(7000);
  ok(w.__error === undefined, 'el script de la vista corre sin errores', w.__error);
  ok(w.document.querySelector('#rep-num').readOnly && w.document.querySelector('#rep-num').value === DOC, 'el documento viene de su sesión y no se puede cambiar');
  ok(texto(w, '#reporte-hc').includes(DOC) && /campos completos/.test(texto(w, '#reporte-hc')), 'el reporte se generó solo', texto(w, '#reporte-hc').slice(0, 120));
  ok(w.document.querySelector('#s-estado').hidden && w.document.querySelector('#s-cobertura').hidden, 'no ve el estado de la plataforma ni las tarjetas del reportero'); }
console.log(fallos ? `\n${fallos} fallo(s)` : '\nVistas: todo en orden'); process.exit(fallos ? 1 : 0);
