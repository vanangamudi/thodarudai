import { useEffect } from 'react';

export default function useGlobalShortcuts(deps) {
  useEffect(() => {
    const onKeyDown = (e) => {
      const k = (e.key || '').toLowerCase();
      if (e.ctrlKey && !e.shiftKey && !e.altKey && k === 's') { e.preventDefault(); deps.onCommit(); return; }
      if (e.altKey && !e.ctrlKey && !e.shiftKey) {
        if (k === 'q') { e.preventDefault(); deps.onQuery(); return; }
        if (k === 'p') { e.preventDefault(); deps.refs.prefix?.()?.focus(); return; }
        if (k === 's') { e.preventDefault(); deps.refs.suffix?.()?.focus(); return; }
        if (k === 'r') { e.preventDefault(); deps.refs.regex?.()?.focus(); return; }
        if (k === 'f') { e.preventDefault(); deps.refs.find?.()?.focus(); return; }
        if (k === 'g') { e.preventDefault(); deps.refs.replace?.()?.focus(); return; }
        if (k === 'l') { e.preventDefault(); deps.refs.length?.()?.focus(); return; }
        if (k === 'i') { e.preventDefault(); deps.refs.limit?.()?.focus(); return; }
        if (k === 'e') { e.preventDefault(); deps.onApplyReplace(); return; }
        if (k === 'a') { e.preventDefault(); deps.onSelectAll(); return; }
        if (k === 'c') { e.preventDefault(); deps.onClearSelection(); return; }
        if (k === 'm') { e.preventDefault(); deps.onToggleReminders(); return; }
        if (k === 'b') { e.preventDefault(); deps.onShowReminders(); return; }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [deps]);
}
