// Thin fetch wrapper around the JSON API.

async function request(method, path, { params, body } = {}) {
  let url = path;
  if (params) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v);
    });
    const s = qs.toString();
    if (s) url += (url.includes('?') ? '&' : '?') + s;
  }
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const err = new Error(extractError(data) || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function extractError(data) {
  if (!data) return null;
  if (typeof data === 'string') return data;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
  }
  return null;
}

export const api = {
  get: (path, params) => request('GET', path, { params }),
  post: (path, body, params) => request('POST', path, { body, params }),
  put: (path, body) => request('PUT', path, { body }),
  patch: (path, body) => request('PATCH', path, { body }),
  del: (path) => request('DELETE', path),
};

let metaPromise = null;
export function getMeta() {
  if (!metaPromise) metaPromise = api.get('/api/meta');
  return metaPromise;
}

export const clinics = {
  list: (params) => api.get('/api/clinics', params),
  get: (id) => api.get(`/api/clinics/${id}`),
  create: (data) => api.post('/api/clinics', data),
  update: (id, data) => api.put(`/api/clinics/${id}`, data),
  setLocation: (id, lat, lng) => api.patch(`/api/clinics/${id}/location`, { lat, lng }),
  remove: (id) => api.del(`/api/clinics/${id}`),
  addNote: (id, body, kind = 'note', author = null, extra = {}) => api.post(`/api/clinics/${id}/notes`, { body, kind, author, ...extra }),
  removeNote: (id, noteId) => api.del(`/api/clinics/${id}/notes/${noteId}`),
  photoNotes: (id, attId) => api.get(`/api/clinics/${id}/attachments/${attId}/notes`),
  tickets: (id) => api.get(`/api/clinics/${id}/tickets`),
  addTicket: (id, data) => api.post(`/api/clinics/${id}/tickets`, data),
  removeTicket: (id, ticketId) => api.del(`/api/clinics/${id}/tickets/${ticketId}`),
  setStage: (id, body) => api.patch(`/api/clinics/${id}/stage`, body),
  timeline: (id) => api.get(`/api/clinics/${id}/timeline`),
  archive: (id, archived) => api.patch(`/api/clinics/${id}/archive`, { archived }),
  quickLog: (id, preset, author, detail) => api.post(`/api/clinics/${id}/quick-log`, { preset, author, detail }),
  duplicates: (params) => api.get('/api/clinics/duplicates', params),
  addLink: (id, data) => api.post(`/api/clinics/${id}/links`, data),
  removeLink: (id, linkId) => api.del(`/api/clinics/${id}/links/${linkId}`),
};

export const locations = {
  all: () => api.get('/api/locations'),
  list: (clinicId) => api.get(`/api/clinics/${clinicId}/locations`),
  create: (clinicId, data) => api.post(`/api/clinics/${clinicId}/locations`, data),
  update: (clinicId, id, data) => api.put(`/api/clinics/${clinicId}/locations/${id}`, data),
  remove: (clinicId, id) => api.del(`/api/clinics/${clinicId}/locations/${id}`),
};

export const groups = {
  list: () => api.get('/api/groups'),
  create: (data) => api.post('/api/groups', data),
};

export const attachments = {
  upload: async (clinicId, file, caption, kind, noteId, serviceId) => {
    const fd = new FormData();
    fd.append('file', file);
    if (caption) fd.append('caption', caption);
    if (kind) fd.append('kind', kind);
    if (noteId != null) fd.append('note_id', noteId);
    if (serviceId != null) fd.append('service_id', serviceId);
    const res = await fetch(`/api/clinics/${clinicId}/attachments`, { method: 'POST', body: fd });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(extractError(data) || `${res.status} ${res.statusText}`);
    return data;
  },
  remove: (id) => api.del(`/api/attachments/${id}`),
  fileUrl: (id, download = false) => `/api/attachments/${id}/file${download ? '?download=true' : ''}`,
};

export const templates = { list: () => api.get('/api/templates') };

export const pricebook = {
  get: () => api.get('/api/pricebook'),
  save: (items) => api.put('/api/pricebook', { items }),
  remove: (key) => api.del(`/api/pricebook/${key}`),
};
export const quotes = {
  list: (params) => api.get('/api/quotes', params),
  get: (id) => api.get(`/api/quotes/${id}`),
  defaults: (clinicId, params) => api.get(`/api/clinics/${clinicId}/quote-defaults`, params),
  create: (clinicId, data) => api.post(`/api/clinics/${clinicId}/quotes`, data),
  update: (id, data) => api.put(`/api/quotes/${id}`, data),
  setStatus: (id, status) => api.patch(`/api/quotes/${id}/status`, { status }),
  applyToDeal: (id) => api.post(`/api/quotes/${id}/apply-to-deal`, {}),
  duplicate: (id) => api.post(`/api/quotes/${id}/duplicate`, {}),
  remove: (id) => api.del(`/api/quotes/${id}`),
  csvUrl: (id) => `/api/quotes/${id}/export.csv`,
};

let deviceMetaPromise = null;
export const devices = {
  meta: () => (deviceMetaPromise ||= api.get('/api/meta/devices')),
  sites: (clinicId) => api.get(`/api/clinics/${clinicId}/sites`),
  list: (clinicId, params) => api.get(`/api/clinics/${clinicId}/devices`, params),
  nextName: (clinicId, deviceType) => api.get(`/api/clinics/${clinicId}/devices/next-name`, { device_type: deviceType }),
  create: (clinicId, data) => api.post(`/api/clinics/${clinicId}/devices`, data),
  topology: (clinicId, site) => api.get(`/api/clinics/${clinicId}/topology`, site ? { site } : undefined),
  racks: (clinicId, site) => api.get(`/api/clinics/${clinicId}/racks`, site ? { site } : undefined),
  csvUrl: (clinicId, site) => `/api/clinics/${clinicId}/devices.csv${site && site !== 'all' ? `?site=${encodeURIComponent(site)}` : ''}`,
  get: (id) => api.get(`/api/devices/${id}`),
  update: (id, data) => api.put(`/api/devices/${id}`, data),
  remove: (id) => api.del(`/api/devices/${id}`),
  addTicket: (id, data) => api.post(`/api/devices/${id}/tickets`, data),
  removeTicket: (id, ticketId) => api.del(`/api/devices/${id}/tickets/${ticketId}`),
  addConnection: (id, data) => api.post(`/api/devices/${id}/connections`, data),
  removeConnection: (id, linkId) => api.del(`/api/devices/${id}/connections/${linkId}`),
  connect: (clinicId, data) => api.post(`/api/clinics/${clinicId}/connect`, data),
  disconnect: (clinicId, data) => api.post(`/api/clinics/${clinicId}/disconnect`, data),
};
export const services = {
  get: (id) => api.get(`/api/services/${id}`),
  create: (deviceId, data) => api.post(`/api/devices/${deviceId}/services`, data),
  update: (id, data) => api.put(`/api/services/${id}`, data),
  remove: (id) => api.del(`/api/services/${id}`),
};
export const vpn = {
  endpoints: (clinicId) => api.get(`/api/clinics/${clinicId}/vpn/endpoints`),
  createEndpoint: (clinicId, data) => api.post(`/api/clinics/${clinicId}/vpn/endpoints`, data),
  updateEndpoint: (id, data) => api.put(`/api/vpn/endpoints/${id}`, data),
  removeEndpoint: (id) => api.del(`/api/vpn/endpoints/${id}`),
  links: (clinicId, site) => api.get(`/api/clinics/${clinicId}/vpn/links`, site && site !== 'all' ? { site } : undefined),
  createLink: (clinicId, data) => api.post(`/api/clinics/${clinicId}/vpn/links`, data),
  getLink: (id) => api.get(`/api/vpn/links/${id}`),
  updateLink: (id, data) => api.put(`/api/vpn/links/${id}`, data),
  removeLink: (id) => api.del(`/api/vpn/links/${id}`),
};
export const settings = { get: () => api.get('/api/settings'), update: (data) => api.put('/api/settings', data) };
export async function scanCard(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/contacts/scan-card', { method: 'POST', body: fd });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(extractError(data) || `${res.status} ${res.statusText}`);
  return data;
}
export const views = {
  list: (page) => api.get('/api/views', { page }),
  create: (data) => api.post('/api/views', data),
  remove: (id) => api.del(`/api/views/${id}`),
};

export const tasks = {
  list: (params) => api.get('/api/tasks', params),
  get: (id) => api.get(`/api/tasks/${id}`),
  create: (data) => api.post('/api/tasks', data),
  update: (id, data) => api.put(`/api/tasks/${id}`, data),
  patch: (id, data) => api.patch(`/api/tasks/${id}`, data),
  remove: (id) => api.del(`/api/tasks/${id}`),
};

export const planRoute = (body) => api.post('/api/route', body);
export const driveTime = (lat, lng) => api.get('/api/drivetime', { lat, lng });

export const contacts = {
  list: (params) => api.get('/api/contacts', params),
  get: (id) => api.get(`/api/contacts/${id}`),
  create: (data) => api.post('/api/contacts', data),
  update: (id, data) => api.put(`/api/contacts/${id}`, data),
  remove: (id) => api.del(`/api/contacts/${id}`),
};

export const appointments = {
  list: (params) => api.get('/api/appointments', params),
  get: (id) => api.get(`/api/appointments/${id}`),
  create: (data) => api.post('/api/appointments', data),
  update: (id, data) => api.put(`/api/appointments/${id}`, data),
  patch: (id, data) => api.patch(`/api/appointments/${id}`, data),
  remove: (id) => api.del(`/api/appointments/${id}`),
};

export const geocode = (q) => api.get('/api/geocode', { q });
export const dashboard = () => api.get('/api/dashboard');
export const revenue = () => api.get('/api/revenue');
export const competitors = () => api.get('/api/competitors');

let billingMetaPromise = null;
export const billingMeta = () => (billingMetaPromise ||= api.get('/api/meta/billing'));

export const inventory = {
  list: (params) => api.get('/api/inventory', params),
  get: (id) => api.get(`/api/inventory/${id}`),
  create: (data) => api.post('/api/inventory', data),
  update: (id, data) => api.put(`/api/inventory/${id}`, data),
  adjust: (id, delta, note) => api.post(`/api/inventory/${id}/adjust`, { delta, note }),
  remove: (id) => api.del(`/api/inventory/${id}`),
};

export const orders = {
  list: (params) => api.get('/api/orders', params),
  create: (data) => api.post('/api/orders', data),
  update: (id, data) => api.put(`/api/orders/${id}`, data),
  receive: (id, data) => api.post(`/api/orders/${id}/receive`, data),
  remove: (id) => api.del(`/api/orders/${id}`),
};

export const invoices = {
  list: (params) => api.get('/api/invoices', params),
  get: (id) => api.get(`/api/invoices/${id}`),
  create: (clinicId, data) => api.post(`/api/clinics/${clinicId}/invoices`, data),
  update: (id, data) => api.put(`/api/invoices/${id}`, data),
  setStatus: (id, status) => api.patch(`/api/invoices/${id}/status`, { status }),
  remove: (id) => api.del(`/api/invoices/${id}`),
  csvUrl: (id) => `/api/invoices/${id}/export.csv`,
};
