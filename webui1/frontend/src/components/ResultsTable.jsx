import React from 'react';

export default function ResultsTable({ rows, baseline, selected, toggleSelected, updateRowField }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="panel card table-wrap">
      <table className="table">
        <thead>
          <tr><th>Sel</th><th>#</th><th>Word</th><th>Splits</th><th>Freq</th><th>Glen</th><th>Notes</th></tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => {
            const changed = row.splits !== baseline[idx];
            return (
              <tr key={row.id} className={changed ? 'row-changed' : ''}>
                <td><input type="checkbox" checked={selected.has(row.id)} onChange={() => toggleSelected(row.id)} /></td>
                <td>{row.id}</td>
                <td>{row.word}</td>
                <td><input type="text" value={row.splits} onChange={(e) => updateRowField(idx, 'splits', e.target.value)} /></td>
                <td>{row.freq}</td>
                <td>{row.glen}</td>
                <td><input type="text" value={row.notes} onChange={(e) => updateRowField(idx, 'notes', e.target.value)} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
