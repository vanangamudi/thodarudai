import React from 'react';

export default function OptionsPanel({ params, setParams, onQuery, onCommit, onSummary, refs }) {
  const set = (k) => (e) => setParams({ ...params, [k]: e.target.value });
  return (
    <div className="panel card">
      <div className="group">
        <div className="group-title">Options</div>
        <div className="grid-3">
          <label className="inline"><input type="text" placeholder="e.g. 8-" value={params.length_spec} onChange={set('length_spec')} ref={refs.lengthRef} /></label>
          <label className="inline"><input type="number" placeholder="Limit" value={params.limit} onChange={set('limit')} ref={refs.limitRef} /></label>
          <label className="inline"><input type="number" min="0" max="100" placeholder="Curated %" value={params.curated_ratio} onChange={set('curated_ratio')} /></label>
        </div>
        <div className="toolbar">
          <button type="button" className="btn btn-primary" onClick={onQuery} ref={refs.queryBtnRef}>Query</button>
          <button type="button" className="btn btn-accent" onClick={onCommit}>Commit</button>
          <button type="button" className="btn" onClick={onSummary}>Load Summary</button>
        </div>
      </div>
    </div>
  );
}
