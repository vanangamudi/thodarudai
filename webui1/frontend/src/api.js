import axios from './http';

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE) ||
  'http://127.0.0.1:8000';

const trim = (s) => (s || '').trim();

export async function queryWords(p) {
  const clean = {
    prefix: trim(p.prefix),
    suffix: trim(p.suffix),
    regex: trim(p.regex),
    prefix_not: trim(p.prefix_not),
    suffix_not: trim(p.suffix_not),
    regex_not: trim(p.regex_not),
    length_spec: trim(String(p.length_spec || '')) || '8-',
    limit: p.limit,
    curated_ratio: p.curated_ratio,
  };
  const fd = new URLSearchParams();
  Object.entries(clean).forEach(([k, v]) => fd.append(k, v));
  const r = await axios.post(`${API_BASE}/api/query`, fd);
  return r.data?.results || [];
}

export async function generateBatchName(p) {
  const fd = new URLSearchParams();
  fd.append('prefix', p.prefix || '');
  fd.append('suffix', p.suffix || '');
  fd.append('length_spec', p.length_spec || '8-');
  const r = await axios.post(`${API_BASE}/api/generate_batch_name`, fd);
  return r.data?.batch || '';
}

export async function commitBatch(edited, batch) {
  const fd = new URLSearchParams();
  if (batch) fd.append('batch', batch);
  fd.append('edited_rows', JSON.stringify(edited));
  const r = await axios.post(`${API_BASE}/api/commit`, fd);
  return r.data;
}

export async function getSummary() {
  const r = await axios.get(`${API_BASE}/api/summary`);
  return r.data;
}

export async function getHealth() {
  const r = await axios.get(`${API_BASE}/api/health`);
  return r.data;
}

export async function getReminders() {
  const r = await axios.get(`${API_BASE}/api/reminders`);
  return r.data?.words || [];
}

export async function getReminderResults() {
  const r = await axios.get(`${API_BASE}/api/reminders/results`);
  return r.data?.results || [];
}

export async function updateReminders(action, words) {
  const fd = new URLSearchParams();
  fd.append('action', action);
  fd.append('words_json', JSON.stringify(words || []));
  const r = await axios.post(`${API_BASE}/api/reminders`, fd);
  return r.data;
}
