/* Utilidades comunes de las 4 vistas. Sin dependencias externas.
 * Las rutas son relativas a la página, así sirven en /vistas/ y en /sede/N/vistas/. */
'use strict';

const VISTAS = [
  { id: 'paciente', href: 'paciente.html', texto: 'Paciente' },
  { id: 'medico', href: 'medico.html', texto: 'Médico' },
  { id: 'admision', href: 'admision.html', texto: 'Admisionista' },
  { id: 'reportes', href: 'reportes.html', texto: 'Reportero' },
];

/* Constructor de nodos DOM (evita innerHTML: los datos clínicos nunca se interpretan como HTML). */
function h(etiqueta, props, ...hijos) {
  const e = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(e.dataset, v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const hijo of hijos.flat()) {
    if (hijo == null || hijo === false) continue;
    e.append(hijo.nodeType ? hijo : document.createTextNode(String(hijo)));
  }
  return e;
}
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const vaciar = (e) => { while (e.firstChild) e.removeChild(e.firstChild); return e; };

function urlApi(ruta, params) {
  const u = new URL('../api/v2' + ruta, location.href);
  for (const [k, v] of Object.entries(params || {})) if (v !== '' && v != null) u.searchParams.set(k, v);
  return u;
}

function mensajeError(estado, d) {
  if (d && d.error === 'sede_no_propietaria')
    return `Este registro pertenece a la sede ${d.sede_propietaria_nombre || d.sede_propietaria}. Desde esta sede es solo de lectura.`;
  if (d && d.error === 'duplicado') return `Ya existe un registro igual (${d.restriccion || 'restricción única'}).`;
  if (d && d.error === 'codigo_o_referencia_invalida')
    return 'Un código no pertenece al catálogo o la referencia no existe (' + (d.restriccion || '') + ').';
  if (d && d.error === 'dato_invalido') return 'Dato inválido: ' + (d.detalle || d.restriccion || '');
  if (d && d.error === 'fhir_no_disponible')
    return 'El servidor FHIR de esta sede no responde. El registro clínico sigue funcionando; reintente la migración más tarde.';
  if (d && (d.error === 'base_no_disponible' || d.error === 'sede_saturada')) return d.mensaje || 'La sede no puede atender ahora.';
  if (d && d.error === 'fhir_rechazo') return 'El servidor FHIR rechazó el documento (' + (d.estado_hapi || '') + ').';
  if (d && Array.isArray(d.detail)) return d.detail.map((x) => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join(' · ');
  if (d && typeof d.detail === 'string') return d.detail;
  return `Error ${estado}`;
}

/* Sesión: el token vive solo en sessionStorage (se borra al cerrar la pestaña). Es el mismo en las 3 sedes. */
const sesion = {
  leer() {
    try {
      const x = JSON.parse(sessionStorage.getItem('hc_sesion') || 'null');
      if (x && x.token && x.expira > Date.now()) return x;
    } catch { /* sin almacenamiento: se pedirá ingresar */ }
    return null;
  },
  guardar(resp) {
    const x = { token: resp.token, usuario: resp.usuario, expira: Date.now() + resp.expira_en_s * 1000 };
    try { sessionStorage.setItem('hc_sesion', JSON.stringify(x)); } catch { /* ignorar */ }
    return x;
  },
  borrar() { try { sessionStorage.removeItem('hc_sesion'); } catch { /* ignorar */ } },
};

async function api(ruta, { metodo = 'GET', cuerpo, params, sinSesion = false } = {}) {
  let r;
  const cab = cuerpo ? { 'Content-Type': 'application/json' } : {};
  const ses = sinSesion ? null : sesion.leer();
  if (ses) cab.Authorization = 'Bearer ' + ses.token;
  try {
    r = await fetch(urlApi(ruta, params), {
      method: metodo,
      headers: cab,
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
  } catch (e) {
    throw Object.assign(new Error('No hay conexión con la sede.'), { estado: 0, cuerpo: {} });
  }
  const sello = r.headers.get('X-Sello-Auditoria');
  if (sello) mostrarSello(sello);
  const texto = await r.text();
  let datos;
  try { datos = JSON.parse(texto); } catch { datos = { texto }; }
  if (r.status === 401 && ses) {      // la sesión venció o el token ya no vale: volver a pedir ingreso
    sesion.borrar();
    location.reload();
    return new Promise(() => {});
  }
  if (!r.ok) throw Object.assign(new Error(mensajeError(r.status, datos)), { estado: r.status, cuerpo: datos });
  return datos;
}

/* Sello de auditoría: cada escritura exitosa devuelve «n.º de evento:hash» del evento encadenado en la sede. */
function mostrarSello(valor) {
  const [seq, hash] = valor.split(':');
  const e = $('#sello-auditoria');
  if (e) vaciar(e).append(h('span', { class: 'insignia info', title: `Evento de auditoría n.º ${seq}\nSHA-256 ${hash}` }, `Último sello ${seq}:${hash.slice(0, 8)}…`));
}

/* Bus de integración (HSB): lo sirve el gateway en /hsb/, no la API de la sede; el token es el mismo. */
async function apiHsb(ruta) {
  const m = location.pathname.match(/^(.*\/sede\/\d+)\/vistas\//);
  if (!m) throw Object.assign(new Error('El bus de integración solo es accesible por el gateway (/sede/N/vistas/).'), { estado: 0 });
  const ses = sesion.leer();
  let r;
  try {
    r = await fetch(new URL(m[1].replace(/\/sede\/\d+$/, '') + '/hsb' + ruta, location.origin), { headers: ses ? { Authorization: 'Bearer ' + ses.token } : {} });
  } catch { throw Object.assign(new Error('No hay conexión con el bus de integración.'), { estado: 0 }); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(typeof d.detail === 'string' ? d.detail : `El bus respondió ${r.status}`), { estado: r.status });
  return d;
}

/* SHA-256 en el navegador (Web Crypto): solo existe en contextos seguros (HTTPS o localhost). */
function canonico(v) {
  if (Array.isArray(v)) return '[' + v.map(canonico).join(',') + ']';
  if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canonico(v[k])).join(',') + '}';
  return JSON.stringify(v);
}
async function sha256Hex(texto) {
  if (!(window.crypto && crypto.subtle)) throw new Error('Este navegador no permite calcular SHA-256 en una página sin HTTPS.');
  const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(texto));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');
}

/* Estado de la plataforma (Médico y Reportero): sedes, base, FHIR y cadena de auditoría; con el bus si se entra por el gateway. */
async function cargarPlataforma(destino) {
  try {
    const p = await api('/estado-plataforma');
    const bus = await apiHsb('/resumen').catch(() => null);
    vaciar(destino).append(
      h('div', { class: 'estado-sede', style: 'flex-wrap:wrap' },
        p.sedes.map((s) => insignia(`${s.sede}: ${s.estado === 'en_linea' ? (s.detalle === 'esta sede' ? 'esta sede' : 'en línea') : s.estado === 'no_responde' ? 'NO RESPONDE' : 'sin dato'}`,
          s.estado === 'en_linea' ? 'ok' : s.estado === 'no_responde' ? 'mal' : 'aviso')),
        insignia(p.base_de_datos === 'ok' ? 'Base de datos ✓' : 'Base de datos ✗', p.base_de_datos === 'ok' ? 'ok' : 'mal'),
        insignia(p.hapi_fhir === 'ok' ? 'FHIR ✓' : 'FHIR no disponible', p.hapi_fhir === 'ok' ? 'ok' : 'aviso'),
        insignia(p.auditoria.ok ? `Auditoría íntegra (${p.auditoria.verificados} eventos)` : `AUDITORÍA ALTERADA${p.auditoria.primer_fallo && p.auditoria.primer_fallo.seq ? ` (evento ${p.auditoria.primer_fallo.seq})` : ' (el anclaje no coincide)'}`, p.auditoria.ok ? 'ok' : 'mal'),
        ...(p.auditoria.anclaje && p.auditoria.anclaje.ok != null ? [insignia(p.auditoria.anclaje.ok ? 'Anclaje en otras sedes ✓' : 'ANCLAJE NO COINCIDE', p.auditoria.anclaje.ok ? 'ok' : 'mal')] : []),
        bus ? insignia(`Bus: ${bus.total} mensajes, ${bus.porcentaje_fallidos} % fallidos`, bus.porcentaje_fallidos > 0 ? 'aviso' : 'ok') : null));
  } catch (e) { mostrar(destino, 'mal', e.message); }
}

/* Mensajes en pantalla */
function mostrar(contenedor, tipo, texto) {
  const e = typeof contenedor === 'string' ? $(contenedor) : contenedor;
  vaciar(e).append(h('div', { class: `mensaje ${tipo}`, role: 'status' }, texto));
}
const limpiar = (c) => vaciar(typeof c === 'string' ? $(c) : c);

/* Catálogos (con caché) */
const _cat = {};
async function catalogo(nombre) {
  if (!_cat[nombre]) _cat[nombre] = (await api('/catalogos/' + nombre)).items;
  return _cat[nombre];
}
async function llenarSelect(select, nombre, { vacio = 'Seleccione…', etiqueta } = {}) {
  const items = await catalogo(nombre);
  vaciar(select).append(h('option', { value: '' }, vacio));
  for (const it of items)
    select.append(h('option', { value: it.codigo }, etiqueta ? etiqueta(it) : `${it.codigo} · ${it.descripcion}`));
  return items;
}
async function descripcion(nombre, codigo) {
  if (codigo == null) return '';
  const it = (await catalogo(nombre)).find((i) => String(i.codigo) === String(codigo));
  return it ? it.descripcion : codigo;
}

/* Formato */
const fmtFecha = (iso) => (iso ? new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' }) : '—');
const fmtDia = (iso) => (iso ? new Date(iso).toLocaleDateString('es-CO', { dateStyle: 'medium' }) : '—');
const ahoraLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const aIso = (valorLocal) => (valorLocal ? valorLocal + ':00' : null);
const nombreCompleto = (p) => [p.primer_nombre, p.segundo_nombre, p.primer_apellido, p.segundo_apellido].filter(Boolean).join(' ');

/* Etiqueta asociada al control (for/id) para que los lectores de pantalla la anuncien. */
let _siguienteId = 0;
function campo(etiqueta, control) {
  if (!control.id) control.id = 'campo-' + (++_siguienteId);
  return h('div', {}, h('label', { for: control.id }, etiqueta), control);
}

function insignia(texto, tipo = 'neutro') { return h('span', { class: `insignia ${tipo}` }, texto); }

const ROL_TEXTO = { admisionista: 'Admisionista', medico: 'Médico', reportero: 'Reportero', paciente: 'Paciente', administrador: 'Administrador' };

/* Formulario de ingreso del personal. Al entrar se recarga la página con la sesión guardada. */
function formularioIngreso(rolesVista) {
  const inpUsuario = h('input', { required: true, autocomplete: 'username', autocapitalize: 'none' });
  const inpClave = h('input', { type: 'password', required: true, autocomplete: 'current-password' });
  const msg = h('div', { 'aria-live': 'polite' });
  const form = h('form', { class: 'rejilla' }, campo('Usuario', inpUsuario), campo('Clave', inpClave),
    h('div', { style: 'align-self:end' }, h('button', { type: 'submit' }, 'Ingresar')));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    limpiar(msg);
    try {
      const resp = await api('/auth/login', { metodo: 'POST', cuerpo: { usuario: inpUsuario.value.trim(), clave: inpClave.value }, sinSesion: true });
      sesion.guardar(resp);
      location.reload();
    } catch (e) { inpClave.value = ''; mostrar(msg, 'mal', e.message); }
  });
  const cuales = rolesVista.map((r) => ROL_TEXTO[r] || r).join(' / ');
  return h('section', { class: 'tarjeta', id: 'ingreso-personal' }, h('h3', {}, 'Ingreso del personal'),
    h('p', { class: 'sub' }, `Esta vista es para el rol ${cuales}. Las claves de laboratorio las entrega scripts/credenciales.py.`), form, msg);
}

/* Barra superior con navegación, estado de la sede y sesión.
 * `roles`: si se indica, la vista exige ese rol (el administrador entra a todas). Sin sesión válida muestra el
 * ingreso y la promesa no se resuelve, así el resto de la página no se ejecuta con datos que no puede ver. */
async function cabecera(activa, roles) {
  const ses = sesion.leer();
  const nav = h('nav', {}, h('a', { href: 'index.html', class: activa === 'inicio' ? 'activa' : '' }, 'Inicio'),
    VISTAS.map((v) => h('a', { href: v.href, class: v.id === activa ? 'activa' : '' }, v.texto)));
  const estado = h('div', { class: 'estado-sede', 'aria-live': 'polite' }, insignia('Conectando…', 'neutro'));
  const quien = h('div', { class: 'estado-sede' }, h('span', { id: 'sello-auditoria' }));
  if (ses) quien.append(insignia(`${ses.usuario.nombre || ses.usuario.usuario} · ${ROL_TEXTO[ses.usuario.rol] || ses.usuario.rol}`, 'info'),
    h('button', { type: 'button', class: 'sec', onclick: () => { sesion.borrar(); location.reload(); } }, 'Salir'));
  document.body.prepend(h('header', { class: 'barra' }, h('h1', {}, 'Historia clínica distribuida'), nav, estado, quien));

  async function refrescar() {
    try {
      const r = await fetch(new URL('../api/health', location.href));
      const d = await r.json();
      vaciar(estado).append(
        insignia(`Sede ${d.sede.nombre || d.sede.id}`, 'info'),
        insignia(d.db === 'ok' ? 'Base de datos ✓' : 'Base de datos ✗', d.db === 'ok' ? 'ok' : 'mal'),
        insignia(d.fhir.estado === 'ok' ? 'FHIR ✓' : 'FHIR no disponible', d.fhir.estado === 'ok' ? 'ok' : 'aviso'));
    } catch {
      vaciar(estado).append(insignia('Sede sin conexión', 'mal'));
    }
  }
  refrescar();
  setInterval(refrescar, 10000);

  if (roles && roles.length) {
    const rol = ses && ses.usuario.rol;
    if (!ses || !(rol === 'administrador' || roles.includes(rol))) {
      const main = $('main');
      main.hidden = true;
      const aviso = ses ? h('div', { class: 'mensaje aviso', role: 'alert' },
        `Está dentro como ${ROL_TEXTO[rol] || rol}; esta vista es de otro rol. Ingrese con un usuario que corresponda o vuelva al inicio.`) : null;
      main.before(h('main', { id: 'puerta' }, h('h2', {}, 'Ingrese para continuar'), aviso, formularioIngreso(roles)));
      return new Promise(() => {});
    }
  }
  return ses;
}

/* Descarga de un archivo generado en el navegador (CSV / JSON). */
function descargar(nombre, contenido, tipo) {
  const url = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  const a = h('a', { href: url, download: nombre });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function aCsv(filas) {
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n;]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  return '﻿' + filas.map((f) => f.map(esc).join(',')).join('\n');
}

/* Tabla simple a partir de columnas [{t: 'Título', f: (fila) => nodo|texto}] */
function tabla(columnas, filas, vacioTexto = 'Sin registros') {
  if (!filas.length) return h('div', { class: 'vacio' }, vacioTexto);
  return h('table', {}, h('thead', {}, h('tr', {}, columnas.map((c) => h('th', {}, c.t)))),
    h('tbody', {}, filas.map((f) => h('tr', {}, columnas.map((c) => h('td', {}, c.f(f)))))));
}
