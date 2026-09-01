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
  addNote: (id, body) => api.post(`/api/clinics/${id}/notes`, { body }),
  removeNote: (id, noteId) => api.del(`/api/clinics/${id}/notes/${noteId}`),
};

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
