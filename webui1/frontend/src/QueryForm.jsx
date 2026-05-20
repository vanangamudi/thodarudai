import React, { useState, useEffect, useRef, useMemo } from 'react';
import './theme.css';
import useGlobalShortcuts from './hooks/useGlobalShortcuts';
import { queryWords, generateBatchName, commitBatch, getSummary, getHealth, getReminders, getReminderResults, updateReminders } from './api';
import FiltersPanel from './components/FiltersPanel';
import OptionsPanel from './components/OptionsPanel';
import FindReplacePanel from './components/FindReplacePanel';
import ResultsTable from './components/ResultsTable';
import SummaryPanel from './components/SummaryPanel';
import FooterInfo from './components/FooterInfo';


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
  const UI_BUILD = useRef(new Date().toISOString()).current;
  const [health, setHealth] = useState(null);
  const [onlySelected, setOnlySelected] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const prefixRef = useRef(null);
  const suffixRef = useRef(null);
  const regexRef = useRef(null);
  const findRef = useRef(null);
  const replaceRef = useRef(null);
  const lengthRef = useRef(null);
  const limitRef = useRef(null);
  const queryBtnRef = useRef(null);
  
  const refs = useMemo(() => ({
    prefixRef, suffixRef, regexRef, findRef, replaceRef, lengthRef, limitRef, queryBtnRef
  }), [prefixRef, suffixRef, regexRef, findRef, replaceRef, lengthRef, limitRef, queryBtnRef]);

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();
    setLoading(true);
    try {
      const res = await queryWords(params);
      const newRows = res.map((rec, idx) => ({
        id: String(idx + 1),
        word: rec[0],
        freq: rec[1],
        glen: rec[2],
        splits: rec[0],
        notes: ''
      }));
      setRows(newRows);
      setBaseline(newRows.map(r => r.splits));
      setSelected(new Set());
    } catch (err) {
      console.error('[ui] query failed', err);
    }
    setLoading(false);
  };

  const updateRowField = (index, field, value) => {
    setRows(prev => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const applyReplace = () => {
    console.log("[ui] applyReplace find=", findText, "replace=", replaceText, "onlySelected=", onlySelected);
    if (!findText) return;
    let changed = 0;
    const applyToId = (id) => !onlySelected || selected.has(id);
    setRows(prev => prev.map(r => {
      if (!applyToId(r.id)) return r;
      const newSplits = (r.splits || "").replace(findText, replaceText);
      if (newSplits !== r.splits) changed += 1;
      return { ...r, splits: newSplits };
    }));
    console.log("[ui] applyReplace changed cells:", changed);
    if (changed === 0) {
      alert("No replacements were made (find text not found in selected scope).");
    }
  };

  const toggleSelected = (id) => {
    setSelected(prev => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id);
      else s.add(id);
      return s;
    });
  };

  const selectAll = () => {
    setSelected(new Set(rows.map(r => r.id)));
  };

  const clearSelection = () => {
    setSelected(new Set());
  };

  const showReminderBag = async () => {
    try {
      const res = await getReminderResults();
      const newRows = res.map((rec, idx) => ({
        id: String(idx + 1),
        word: rec[0],
        freq: rec[1],
        glen: rec[2],
        splits: rec[0],
        notes: ''
      }));
      setRows(newRows);
      setBaseline(newRows.map(r => r.splits));
      setSelected(new Set());
    } catch (e) { console.error('[ui] reminders bag failed', e); alert('Failed to load reminders.'); }
  };

  const toggleRemindersForSelected = async () => {
    const words = rows.filter(r => selected.has(r.id)).map(r => r.word);
    if (words.length === 0) { alert('No rows selected.'); return; }
    try {
      const cur = new Set(await getReminders());
      const add = words.filter(w => !cur.has(w));
      const rem = words.filter(w => cur.has(w));
      if (add.length) await updateReminders('add', add);
      if (rem.length) await updateReminders('remove', rem);
      alert(`Reminders updated: added ${add.length}, removed ${rem.length}.`);
    } catch (e) { console.error('[ui] reminders toggle failed', e); alert('Failed to update reminders.'); }
  };

  const loadSummary = async () => {
    try { setSummary(await getSummary()); } catch (e) { console.error('[ui] summary failed', e); }
  };

  const commitEdits = async () => {
    try {
      const edited = rows
        .map((r, idx) => ({ r, idx }))
        .filter(({ r, idx }) => r.splits !== baseline[idx])
        .map(({ r }) => [r.id, r.word, r.splits, String(r.freq ?? ''), String(r.glen ?? ''), r.notes ?? '']);
      if (edited.length === 0) { alert('No edits to commit.'); return; }
      let batch = '';
      try { batch = await generateBatchName(params); } catch (_) {}
      const resp = await commitBatch(edited, batch);
      alert(`Committed ${resp.rows} row(s)${batch ? ` in ${batch}` : ''}.`);
      setBaseline(rows.map(r => r.splits));
    } catch (e) {
      console.error('[ui] commit failed', e);
      alert('Commit failed: ' + (e.response?.data?.detail || e.message));
    }
  };

  useGlobalShortcuts({
    onCommit: commitEdits,
    onQuery: () => queryBtnRef.current?.click(),
    onApplyReplace: applyReplace,
    onSelectAll: () => setSelected(new Set(rows.map(r => r.id))),
    onClearSelection: () => setSelected(new Set()),
    onToggleReminders: toggleRemindersForSelected,
    onShowReminders: showReminderBag,
    refs: {
      prefix: () => prefixRef.current,
      suffix: () => suffixRef.current,
      regex: () => regexRef.current,
      find: () => findRef.current,
      replace: () => replaceRef.current,
      length: () => lengthRef.current,
      limit: () => limitRef.current
    }
  });

  useEffect(() => {
    (async () => { try { setHealth(await getHealth()); } catch (e) { console.error('[ui] health failed', e); } })();
  }, []);

  return (
    <div>
      <form onSubmit={handleSubmit}>
        <FiltersPanel params={params} setParams={setParams} refs={{ prefixRef, suffixRef, regexRef }} />
        <OptionsPanel params={params} setParams={setParams} onQuery={handleSubmit} onCommit={commitEdits} onSummary={loadSummary} refs={{ lengthRef, limitRef, queryBtnRef }} />
        <FindReplacePanel
          findText={findText} setFindText={setFindText}
          replaceText={replaceText} setReplaceText={setReplaceText}
          onlySelected={onlySelected} setOnlySelected={setOnlySelected}
          onApplyReplace={applyReplace}
          onSelectAll={() => setSelected(new Set(rows.map(r => r.id)))}
          onClearSelection={() => setSelected(new Set())}
          refs={{ findRef, replaceRef }}
        />
      </form>
      {loading ? <p>Loading...</p> :
        <ResultsTable 
          rows={rows} 
          baseline={baseline} 
          selected={selected} 
          toggleSelected={(id) => setSelected(prev => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; })} 
          updateRowField={updateRowField} 
        />
      }
      <SummaryPanel summary={summary} />
      <FooterInfo uiBuild={UI_BUILD} health={health} />
    </div>
  );
};

export default QueryForm;
