import React from 'react';

export default function SummaryPanel({ summary }) {
  if (!summary) return null;
  const keys = Object.keys({ ...summary.length_distribution.curated, ...summary.length_distribution.remaining })
    .sort((a, b) => Number(a) - Number(b));
  return (
    <div className="panel card">
      <h3>Summary</h3>
      <p>Total words: {summary.total_words}</p>
      <p>Curated (distinct): {summary.curated_distinct}</p>
      <p>Remaining (distinct): {summary.remaining_distinct}</p>
      <p>Curation entries: {summary.curation_entries}</p>
      <h4>Length distribution</h4>
      <table className="table">
        <thead><tr><th>glen</th><th>curated</th><th>remaining</th></tr></thead>
        <tbody>
          {keys.map((gl) => (
            <tr key={gl}>
              <td>{gl}</td>
              <td>{summary.length_distribution.curated[gl] || 0}</td>
              <td>{summary.length_distribution.remaining[gl] || 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
