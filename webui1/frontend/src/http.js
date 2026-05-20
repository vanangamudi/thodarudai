import axios from 'axios';

if (typeof window !== 'undefined' && !window.__AXIOS_LOGGER_INSTALLED__) {
  axios.defaults.timeout = 20000;
  axios.interceptors.request.use((cfg) => {
    console.log('[axios][request]', cfg.method?.toUpperCase(), cfg.url);
    return cfg;
  });
  axios.interceptors.response.use(
    (resp) => {
      console.log('[axios][response]', resp.config?.url, resp.status);
      return resp;
    },
    (err) => {
      console.error('[axios][error]', err.message, err.response?.status);
      return Promise.reject(err);
    }
  );
  window.__AXIOS_LOGGER_INSTALLED__ = true;
}

export default axios;
