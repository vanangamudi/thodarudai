import React from 'react';

export default function FiltersPanel({ params, setParams, refs }) {
  const set = (k) => (e) => setParams({ ...params, [k]: e.target.value });
  return (
    <div className="panel card">
      <div className="group">
        <div className="group-title">Filters</div>
        <div className="grid-2">
          <label className="inline"><input type="text" placeholder="Prefix" value={params.prefix} onChange={set('prefix')} ref={refs.prefixRef} /></label>
          <label className="inline"><input type="text" placeholder="Exclude Prefix" value={params.prefix_not} onChange={set('prefix_not')} /></label>
          <label className="inline"><input type="text" placeholder="Suffix" value={params.suffix} onChange={set('suffix')} ref={refs.suffixRef} /></label>
          <label className="inline"><input type="text" placeholder="Exclude Suffix" value={params.suffix_not} onChange={set('suffix_not')} /></label>
          <label className="inline"><input type="text" placeholder="Regex" value={params.regex} onChange={set('regex')} ref={refs.regexRef} /></label>
          <label className="inline"><input type="text" placeholder="Exclude Regex" value={params.regex_not} onChange={set('regex_not')} /></label>
        </div>
      </div>
    </div>
  );
}
