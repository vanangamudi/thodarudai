import React from 'react';

export default function FindReplacePanel({
  findText, setFindText, replaceText, setReplaceText,
  onlySelected, setOnlySelected,
  onApplyReplace, onSelectAll, onClearSelection, refs
}) {
  return (
    <div className="panel card">
      <div className="group">
        <div className="group-title">Find &amp; Replace (Splits column)</div>
        <div className="toolbar">
          <label className="inline"><input type="text" placeholder="Find" value={findText} onChange={(e) => setFindText(e.target.value)} ref={refs.findRef} /></label>
          <label className="inline"><input type="text" placeholder="Replace" value={replaceText} onChange={(e) => setReplaceText(e.target.value)} ref={refs.replaceRef} /></label>
          <button type="button" className="btn" onClick={onApplyReplace}>Apply Replace</button>
          <label><input type="checkbox" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} /> Only selected rows</label>
          <button type="button" className="btn" onClick={onSelectAll}>Select All</button>
          <button type="button" className="btn" onClick={onClearSelection}>Clear Selection</button>
        </div>
      </div>
    </div>
  );
}
