import React from 'react';

export default function FooterInfo({ uiBuild, health }) {
  return (
    <div className="panel card" style={{ padding: 8 }}>
      <small>
        UI {uiBuild}
        {health ? (
          <> | API {health.build_tag} | {health.app_file} mtime {new Date(health.app_mtime * 1000).toLocaleString()} | words {health.word_count} | curated {health.curated_count}</>
        ) : ' | API: …'}
      </small>
    </div>
  );
}
