// Every <form data-api="/api/..."> is sent as JSON to the same API scripts use.
// Fields named "x[]" become arrays. The response decides what the user/agent sees:
//   200 -> go to redirect (flag decisions show a yellow banner with Undo)
//   202 -> paused, waiting for approval (blue banner)
//   403 -> blocked by Sentinel (red banner)
(function () {
  function banner(kind, text, extra) {
    const el = document.getElementById('sentinel-banner');
    if (!el) return alert(text);
    const styles = {
      block: 'bg-red-50 border-red-300 text-red-800',
      pause: 'bg-blue-50 border-blue-300 text-blue-800',
      flag: 'bg-amber-50 border-amber-300 text-amber-900',
      error: 'bg-gray-100 border-gray-300 text-gray-800',
      ok: 'bg-green-50 border-green-300 text-green-800',
    };
    const titles = {
      block: 'Blocked by Sentinel', pause: 'Paused by Sentinel – waiting for approval',
      flag: 'Flagged by Sentinel', error: 'Error', ok: 'Done',
    };
    el.className = 'sticky top-0 z-50 mx-4 mt-3 border rounded px-4 py-3 text-sm shadow ' + styles[kind];
    el.innerHTML = '<strong>' + titles[kind] + ':</strong> <span></span> ' + (extra || '');
    el.querySelector('span').textContent = text || '';
    el.hidden = false;
    window.scrollTo({ top: 0 });
  }
  window.sentinelBanner = banner;

  // flash from previous page (flag decisions)
  try {
    const f = JSON.parse(sessionStorage.getItem('flash') || 'null');
    if (f) {
      sessionStorage.removeItem('flash');
      const undo = f.event_id ? '<button type="button" class="ml-2 underline font-medium" data-undo="' + f.event_id + '">Undo</button>' : '';
      banner(f.kind, f.text, undo);
    }
  } catch (e) {}

  // ---- click-level UI log (page views are logged server-side) ----
  function uiLog(payload) {
    payload.path = location.pathname + location.search;
    const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
    if (!(navigator.sendBeacon && navigator.sendBeacon('/api/ui', blob))) {
      fetch('/api/ui', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), keepalive: true });
    }
  }
  window.uiLog = uiLog;
  document.addEventListener('click', function (e) {
    const el = e.target.closest('button, a, summary, [role=button], input[type=checkbox], input[type=radio], input[type=submit]');
    if (!el) return;
    let label = (el.getAttribute('aria-label') || el.innerText || el.value || el.name || '').trim().split('\n')[0];
    if (el.type === 'checkbox' || el.type === 'radio') return; // logged as field_set on change
    const form = el.closest('form');
    uiLog({ kind: 'click', label: label.slice(0, 60), href: el.getAttribute('href') || '', form: form ? (form.dataset.api || form.action || '') : '' });
  }, true);
  document.addEventListener('change', function (e) {
    const el = e.target;
    if (!el.name || el.type === 'password') return;
    let value = el.value;
    if (el.type === 'checkbox' || el.type === 'radio') value = (el.checked ? 'checked:' : 'unchecked:') + el.value;
    const form = el.closest('form');
    uiLog({ kind: 'field_set', field: el.name.replace(/\[\]$/, ''), value: value, form: form ? (form.dataset.api || '') : '' });
  }, true);

  document.addEventListener('click', async function (e) {
    const b = e.target.closest('[data-undo]');
    if (!b) return;
    const r = await fetch('/api/events/' + b.dataset.undo + '/undo', { method: 'POST' });
    if (r.ok) { banner('ok', 'Change undone.'); setTimeout(() => location.reload(), 600); }
    else banner('error', 'Undo failed');
  });

  document.addEventListener('submit', async function (e) {
    const f = e.target;
    if (!f.dataset.api) return;
    e.preventDefault();
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) return;
    const body = {};
    for (const [k, v] of new FormData(f).entries()) {
      if (k.endsWith('[]')) { const kk = k.slice(0, -2); (body[kk] = body[kk] || []).push(v); }
      else body[k] = v;
    }
    const btns = f.querySelectorAll('button[type=submit]');
    btns.forEach(x => x.disabled = true);
    let r, j = {};
    try {
      r = await fetch(f.dataset.api, { method: f.dataset.method || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      try { j = await r.json(); } catch (_) {}
    } catch (err) { banner('error', String(err)); btns.forEach(x => x.disabled = false); return; }
    btns.forEach(x => x.disabled = false);
    const d = j.detail || j;
    if (r.status === 403) return banner('block', d.reason || 'Action blocked.');
    if (r.status === 202) return banner('pause', (d.reason || 'Waiting for approval') + '. Nothing was sent or saved yet.');
    if (!r.ok) return banner('error', typeof d === 'string' ? d : (d.detail || JSON.stringify(d)));
    if (j.decision === 'flag') sessionStorage.setItem('flash', JSON.stringify({ kind: 'flag', text: j.reason || 'Unusual change saved.', event_id: j.event_id }));
    else if (f.dataset.flash) sessionStorage.setItem('flash', JSON.stringify({ kind: 'ok', text: f.dataset.flash }));
    if (j.redirect) location.href = j.redirect; else location.reload();
  });
})();
