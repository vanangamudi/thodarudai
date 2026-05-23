import React from 'react';

export default function OptionsPanel({ params, setParams, onQuery, onCommit, onSummary, refs, loading }) {
  const set = (k) => (e) => setParams({ ...params, [k]: e.target.value });
  const setInt = (k, min = 0, max = Number.MAX_SAFE_INTEGER) => (e) => {
    const v = parseInt(e.target.value || '0', 10);
    const clamped = isNaN(v) ? 0 : Math.min(max, Math.max(min, v));
    setParams({ ...params, [k]: clamped });
  };
  return (
    <div className="panel card">
      <div className="group">
        <div className="group-title">Options</div>
        <div className="grid-3">
          <label className="inline"><input type="text" placeholder="e.g. 8-" value={params.length_spec} onChange={set('length_spec')} ref={refs.lengthRef} /></label>
          <label className="inline">
            <input type="number" placeholder="Limit" value={params.limit} onChange={setInt('limit', 1)} ref={refs.limitRef} />
          </label>
          <label className="inline">
            <input type="number" min="0" max="100" placeholder="Curated %" value={params.curated_ratio} onChange={setInt('curated_ratio', 0, 100)} />
          </label>
        </div>
        <div className="toolbar">
          <button type="button" className="btn btn-primary" onClick={onQuery} ref={refs.queryBtnRef} disabled={loading}>Query</button>
          <button type="button" className="btn btn-accent" onClick={onCommit} disabled={loading}>Commit</button>
          <button type="button" className="btn" onClick={onSummary} disabled={loading}>Load Summary</button>
        </div>
      </div>
    </div>
  );
}
