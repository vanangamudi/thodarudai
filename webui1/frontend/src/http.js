import axios from 'axios';

const DEBUG_HTTP =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_DEBUG_HTTP === '1');

if (typeof window !== 'undefined' && DEBUG_HTTP && !window.__AXIOS_LOGGER_INSTALLED__) {
  axios.defaults.timeout = 20000;
  axios.interceptors.request.use((cfg) => {
    cfg.metadata = { start: Date.now() };
    console.log('[axios][request]', (cfg.method || '').toUpperCase(), cfg.url || '');
    return cfg;
  });
  axios.interceptors.response.use(
    (resp) => {
      const start = resp?.config?.metadata?.start;
      const dur = (typeof start === 'number') ? (Date.now() - start) : undefined;
      const parts = ['[axios][response]', resp.config?.url || '', resp.status];
      if (dur != null) parts.push(`${dur}ms`);
      console.log(...parts);
      return resp;
    },
    (err) => {
      const cfg = err?.config;
      const start = cfg?.metadata?.start;
      const dur = (typeof start === 'number') ? (Date.now() - start) : undefined;
      const parts = ['[axios][error]', err.message, err.response?.status, cfg?.url || ''];
      if (dur != null) parts.push(`${dur}ms`);
      console.error(...parts);
      return Promise.reject(err);
    }
  );
  window.__AXIOS_LOGGER_INSTALLED__ = true;
}

export default axios;
