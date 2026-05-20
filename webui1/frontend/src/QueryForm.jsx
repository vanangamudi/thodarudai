import React, { useState } from 'react';
import axios from 'axios';
axios.defaults.timeout = 20000; // 20s dev-timeout to surface hung requests

// Log every axios request/response
axios.interceptors.request.use(cfg => {
  console.log("[axios][request]", cfg.method?.toUpperCase(), cfg.url, cfg.headers, cfg.data);
  return cfg;
});
axios.interceptors.response.use(
  resp => {
    const len = Array.isArray(resp.data?.results) ? resp.data.results.length : undefined;
    console.log("[axios][response]", resp.config?.url, resp.status, len !== undefined ? `results=${len}` : resp.data);
    return resp;
  },
  err => {
    console.error("[axios][error]", err.message, err.response?.status, err.response?.data);
    return Promise.reject(err);
  }
);

// Catch unhandled promise rejections and window errors
if (typeof window !== "undefined") {
  window.addEventListener("unhandledrejection", (e) => {
    console.error("[window][unhandledrejection]", e.reason);
  });
  window.addEventListener("error", (e) => {
    console.error("[window][error]", e.message, e.error);
  });
}

const QueryForm = () => {
  const [params, setParams] = useState({
    prefix: '',
    suffix: '',
    regex: '',
    prefix_not: '',
    suffix_not: '',
    regex_not: '',
    length_spec: '8-',
    limit: 1000,
    curated_ratio: 20, // percent
  });
  const [rows, setRows] = useState([]);            // [{id, word, freq, glen, splits, notes}]
  const [baseline, setBaseline] = useState([]);    // [splits baseline]
  const [loading, setLoading] = useState(false);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [summary, setSummary] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    console.log("[ui] submit query", params);
    try {
      const clean = {
        ...params,
        prefix: (params.prefix || "").trim(),
        suffix: (params.suffix || "").trim(),
        regex: (params.regex || "").trim(),
        prefix_not: (params.prefix_not || "").trim(),
        suffix_not: (params.suffix_not || "").trim(),
        regex_not: (params.regex_not || "").trim(),
        length_spec: String(params.length_spec || "").trim() || "8-",
      };
      const formData = new URLSearchParams();
      Object.entries(clean).forEach(([key, value]) => {
        formData.append(key, value);
      });
      const response = await axios.post("http://127.0.0.1:8000/api/query", formData);
      const res = response.data.results || [];
      const newRows = res.map((rec, idx) => ({
        id: String(idx + 1),
        word: rec[0],
        freq: rec[1],
        glen: rec[2],
        splits: rec[0],
        notes: "",
      }));
      console.log("[ui] query ok rows", newRows.length);
      setRows(newRows);
      setBaseline(newRows.map(r => r.splits));
    } catch (err) {
      console.error("[ui] query failed", err);
    }
    setLoading(false);
    console.log("[ui] submit done");
  };
  
  const updateRowField = (index, field, value) => {
    setRows(prev => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const applyReplace = () => {
    console.log("[ui] applyReplace find=", findText, "replace=", replaceText);
    if (!findText) return;
    setRows(prev => prev.map(r => ({ ...r, splits: r.splits.replace(findText, replaceText) })));
  };

  const loadSummary = async () => {
    console.log("[ui] load summary");
    try {
      const r = await axios.get("http://127.0.0.1:8000/api/summary");
      setSummary(r.data);
      console.log("[ui] summary ok");
    } catch (e) {
      console.error("[ui] summary failed", e);
    }
  };

  const commitEdits = async () => {
    console.log("[ui] commit start");
    try {
      const edited = rows
        .map((r, idx) => ({ r, idx }))
        .filter(({ r, idx }) => r.splits !== baseline[idx])
        .map(({ r }) => [r.id, r.word, r.splits, String(r.freq ?? ""), String(r.glen ?? ""), r.notes ?? ""]);
      if (edited.length === 0) {
        alert("No edits to commit.");
        return;
      }
      const bnForm = new URLSearchParams();
      bnForm.append("prefix", params.prefix);
      bnForm.append("suffix", params.suffix);
      bnForm.append("length_spec", params.length_spec);
      let batch = "";
      try {
        const bn = await axios.post("http://127.0.0.1:8000/api/generate_batch_name", bnForm);
        batch = bn.data.batch || "";
      } catch (_) {}

      const fd = new URLSearchParams();
      if (batch) fd.append("batch", batch);
      fd.append("edited_rows", JSON.stringify(edited));
      console.log("[ui] commit rows", edited.length, "batch?", !!batch);
      const resp = await axios.post("http://127.0.0.1:8000/api/commit", fd);
      alert(`Committed ${resp.data.rows} row(s)${batch ? ` in ${batch}` : ""}.`);
      console.log("[ui] commit ok", resp.data);
      setBaseline(rows.map(r => r.splits));
    } catch (e) {
      console.error("[ui] commit failed", e);
      alert("Commit failed: " + (e.response?.data?.detail || e.message));
    }
  };
  
  return (
    <div>
      <form onSubmit={handleSubmit}>
        <input type="text" placeholder="Prefix" value={params.prefix}
          onChange={e => setParams({ ...params, prefix: e.target.value })} />
        <input type="text" placeholder="Exclude Prefix" value={params.prefix_not}
          onChange={e => setParams({ ...params, prefix_not: e.target.value })} />
        <input type="text" placeholder="Suffix" value={params.suffix}
          onChange={e => setParams({ ...params, suffix: e.target.value })} />
        <input type="text" placeholder="Exclude Suffix" value={params.suffix_not}
          onChange={e => setParams({ ...params, suffix_not: e.target.value })} />
        <input type="text" placeholder="Regex" value={params.regex}
          onChange={e => setParams({ ...params, regex: e.target.value })} />
        <input type="text" placeholder="Exclude Regex" value={params.regex_not}
          onChange={e => setParams({ ...params, regex_not: e.target.value })} />
        <input type="text" placeholder="Length Spec" value={params.length_spec}
          onChange={e => setParams({ ...params, length_spec: e.target.value })} />
        <input type="number" placeholder="Limit" value={params.limit}
          onChange={e => setParams({ ...params, limit: e.target.value })} />
        <input type="number" min="0" max="100" placeholder="Curated %" value={params.curated_ratio}
          onChange={e => setParams({ ...params, curated_ratio: e.target.value })} />
        <button type="submit">Query</button>
        <button type="button" onClick={applyReplace}>Apply Replace</button>
        <input type="text" placeholder="Find" value={findText} onChange={e => setFindText(e.target.value)} />
        <input type="text" placeholder="Replace" value={replaceText} onChange={e => setReplaceText(e.target.value)} />
        <button type="button" onClick={commitEdits}>Commit</button>
        <button type="button" onClick={loadSummary}>Load Summary</button>
      </form>
      {loading ? <p>Loading...</p> :
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Word</th>
              <th>Splits</th>
              <th>Freq</th>
              <th>Glen</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={idx}>
                <td>{row.id}</td>
                <td>{row.word}</td>
                <td>
                  <input
                    type="text"
                    value={row.splits}
                    onChange={e => updateRowField(idx, "splits", e.target.value)}
                  />
                </td>
                <td>{row.freq}</td>
                <td>{row.glen}</td>
                <td>
                  <input
                    type="text"
                    value={row.notes}
                    onChange={e => updateRowField(idx, "notes", e.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
      {summary && (
        <div>
          <h3>Summary</h3>
          <p>Total words: {summary.total_words}</p>
          <p>Curated (distinct): {summary.curated_distinct}</p>
          <p>Remaining (distinct): {summary.remaining_distinct}</p>
          <p>Curation entries: {summary.curation_entries}</p>
          <h4>Length distribution</h4>
          <table>
            <thead><tr><th>glen</th><th>curated</th><th>remaining</th></tr></thead>
            <tbody>
              {Object.keys({
                ...summary.length_distribution.curated,
                ...summary.length_distribution.remaining
              }).sort((a,b)=>Number(a)-Number(b)).map(gl => (
                <tr key={gl}>
                  <td>{gl}</td>
                  <td>{summary.length_distribution.curated[gl] || 0}</td>
                  <td>{summary.length_distribution.remaining[gl] || 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default QueryForm;
