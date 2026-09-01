// Desktop notifications for upcoming appointments and tasks.
// Polls /api/reminders while a tab is open and fires browser notifications at the
// event time and, when set, N minutes before it.
import { api } from './api.js';
import { esc, parseDate, fmtTime, navigate } from './ui.js';

const POLL_MS = 60 * 1000;
const FIRED_KEY = 'notif_fired';
const DISMISS_KEY = 'notif_banner_dismissed_until';
let timer = null;

export function supported() { return typeof window !== 'undefined' && 'Notification' in window; }
export function permission() { return supported() ? Notification.permission : 'unsupported'; }
export function enabled() { return permission() === 'granted'; }

export async function requestPermission() {
  if (!supported()) throw new Error('This browser does not support notifications.');
  if (!window.isSecureContext) throw new Error('Notifications need a secure page (https:// or localhost). Open the app via https or localhost.');
  const p = await Notification.requestPermission();
  if (p === 'granted') start();
  return p;
}

export function sendTest() {
  if (!enabled()) return false;
  show('Area Book Planner', { body: 'Notifications are working. You will be reminded before appointments and tasks.', tag: 'test' });
  return true;
}

function show(title, { body, tag, url }) {
  try {
    const n = new Notification(title, { body, tag, icon: '/static/icon.svg', renotify: false });
    n.onclick = () => { window.focus(); if (url) navigate(url); n.close(); };
  } catch (e) { console.warn('notification failed', e); }
}

function loadFired() {
  try { return JSON.parse(localStorage.getItem(FIRED_KEY) || '{}'); } catch { return {}; }
}
function saveFired(map) {
  const cutoff = Date.now() - 2 * 86400000;
  for (const k of Object.keys(map)) if (map[k] < cutoff) delete map[k];
  try { localStorage.setItem(FIRED_KEY, JSON.stringify(map)); } catch { /* ignore */ }
}

async function poll() {
  if (!enabled()) return;
  let data;
  try { data = await api.get('/api/reminders', { horizon_minutes: 120 }); } catch { return; }
  const now = Date.now();
  const fired = loadFired();
  for (const item of data.items) {
    const at = parseDate(item.at);
    if (!at) continue;
    const points = [{ key: `${item.kind}-${item.id}-${item.at}-0`, time: at.getTime(), lead: 0 }];
    if (item.reminder_minutes) {
      points.push({ key: `${item.kind}-${item.id}-${item.at}-${item.reminder_minutes}`, time: at.getTime() - item.reminder_minutes * 60000, lead: item.reminder_minutes });
    }
    for (const p of points) {
      if (fired[p.key]) continue;
      // Fire if due and not more than 15 minutes stale (so a sleeping laptop doesn't flood on wake).
      if (now >= p.time && now - p.time <= 15 * 60000) {
        const what = item.kind === 'appointment' ? 'Appointment' : 'Task';
        const when = p.lead ? `in ${p.lead} min (${fmtTime(item.at)})` : 'now';
        show(`${what} ${p.lead ? 'coming up' : 'starting'}: ${item.title}`, {
          body: `${item.clinic_name ? item.clinic_name + ' · ' : ''}${when}`,
          tag: p.key, url: item.url,
        });
        fired[p.key] = now;
      }
    }
  }
  saveFired(fired);
}

export function start() {
  if (timer || !enabled()) return;
  poll();
  timer = setInterval(poll, POLL_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
}

// Ask the visitor once whether they want reminders (a friendly in-page bar, then the browser prompt).
export function initNotifications() {
  const root = document.getElementById('notif-banner');
  if (!root) return;
  if (enabled()) { start(); return; }
  if (!supported() || permission() === 'denied') return;
  let until = 0;
  try { until = Number(localStorage.getItem(DISMISS_KEY) || 0); } catch { /* ignore */ }
  if (until > Date.now()) return;
  const secure = window.isSecureContext;
  root.innerHTML = `
    <span>🔔 <strong>Turn on desktop reminders?</strong> Area Book can notify you when an appointment or task is about to start.${secure ? '' : ' <em>(Needs https:// or localhost)</em>'}</span>
    <button class="btn btn-sm btn-primary" id="notif-enable" ${secure ? '' : 'disabled'}>Enable</button>
    <button class="btn btn-sm" id="notif-later">Not now</button>`;
  root.classList.remove('hidden');
  root.querySelector('#notif-enable').onclick = async () => {
    try {
      const p = await requestPermission();
      root.classList.add('hidden');
      if (p === 'granted') sendTest();
    } catch (e) { root.querySelector('span').innerHTML = esc(e.message); }
  };
  root.querySelector('#notif-later').onclick = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now() + 7 * 86400000)); } catch { /* ignore */ }
    root.classList.add('hidden');
  };
}
