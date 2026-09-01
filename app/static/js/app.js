// Hash router + global actions.
import * as dashboard from './pages/dashboard.js';
import * as mapPage from './pages/map.js';
import * as clinicsPage from './pages/clinics.js';
import * as clinicDetail from './pages/clinic-detail.js';
import * as contactsPage from './pages/contacts.js';
import * as calendarPage from './pages/calendar.js';
import * as pipelinePage from './pages/pipeline.js';
import * as tasksPage from './pages/tasks.js';
import { openClinicForm, openAppointmentForm } from './forms.js';
import { navigate, toast, toggleTheme, getTheme } from './ui.js';

const routes = [
  { pattern: /^\/?$/, page: dashboard, nav: '' },
  { pattern: /^\/map$/, page: mapPage, nav: 'map' },
  { pattern: /^\/clinics$/, page: clinicsPage, nav: 'clinics' },
  { pattern: /^\/clinics\/(?<id>\d+)$/, page: clinicDetail, nav: 'clinics' },
  { pattern: /^\/contacts$/, page: contactsPage, nav: 'contacts' },
  { pattern: /^\/calendar$/, page: calendarPage, nav: 'calendar' },
  { pattern: /^\/pipeline$/, page: pipelinePage, nav: 'pipeline' },
  { pattern: /^\/tasks$/, page: tasksPage, nav: 'tasks' },
];

let current = null;
const app = document.getElementById('app');

async function route() {
  const hash = window.location.hash.replace(/^#/, '') || '/';
  const [path, query = ''] = hash.split('?');
  const params = new URLSearchParams(query);
  const match = routes.find(r => r.pattern.test(path));
  if (!match) { navigate('#/'); return; }

  if (current && current.page.destroy) current.page.destroy(app);
  current = match;
  document.querySelectorAll('#topnav a').forEach(a => a.classList.toggle('active', a.dataset.route === match.nav));
  app.innerHTML = '<div class="loading">Loading…</div>';
  const routeParams = path.match(match.pattern).groups || {};
  try {
    await match.page.render(app, params, routeParams);
  } catch (e) {
    console.error(e);
    app.innerHTML = `<div class="card empty">Something went wrong: ${e.message}</div>`;
  }
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
window.addEventListener('DOMContentLoaded', route);

document.getElementById('global-add-clinic').onclick = () =>
  openClinicForm({ onSaved: (c) => navigate(`#/clinics/${c.id}`) });
document.getElementById('global-add-appointment').onclick = () =>
  openAppointmentForm({ onSaved: () => route() });

// Dark mode toggle (theme itself is applied before first paint in index.html).
const themeBtn = document.getElementById('theme-toggle');
const syncThemeBtn = () => { themeBtn.textContent = getTheme() === 'dark' ? '☀' : '☾'; };
themeBtn.onclick = () => { toggleTheme(); syncThemeBtn(); };
syncThemeBtn();

// Surface API failures that escape page code.
window.addEventListener('unhandledrejection', (e) => {
  if (e.reason && e.reason.message) toast(e.reason.message, 'error');
});
