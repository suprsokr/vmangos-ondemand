/* vmangos-ondemand panel */

let currentTab = 'tasks';
let taskEventSource = null;
let logEventSource = null;
let lineCount = 0;
let activeTaskId = null;

// ── Bootstrap ──────────────────────────────────────────────────────

document.querySelectorAll('.btn').forEach(b =>
  b.classList.add('px-4', 'py-2', 'rounded-md', 'text-sm', 'transition-colors', 'cursor-pointer'));
document.querySelectorAll('.btn-sm').forEach(b =>
  b.classList.add('px-3', 'py-1.5'));

fetchStatus();
fetchSetupStatus();
setInterval(fetchStatus, 4000);
setInterval(fetchSetupStatus, 8000);
switchTab('tasks');

const savedPath = localStorage.getItem('vmangos-client-path');
if (savedPath) document.getElementById('client-path').value = savedPath;
document.getElementById('client-path').addEventListener('input', e => {
  localStorage.setItem('vmangos-client-path', e.target.value);
});

const savedBuild = localStorage.getItem('vmangos-client-build');
if (savedBuild) document.getElementById('client-build').value = savedBuild;
document.getElementById('client-build').addEventListener('change', e => {
  localStorage.setItem('vmangos-client-build', e.target.value);
});

// ── Status polling ─────────────────────────────────────────────────

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw new Error();
    const data = await res.json();
    if (data.error) throw new Error();
    setDockerStatus(true);
    updateService('db', data.db);
    updateService('mangosd', data.mangosd);
    updateService('realmd', data.realmd);
  } catch {
    setDockerStatus(false);
  }
}

async function fetchSetupStatus() {
  try {
    const res = await fetch('/api/setup-status');
    const data = await res.json();
    toggle('btn-clone', !data.core_cloned);
    toggle('btn-update', data.core_cloned);
  } catch { /* ignore */ }
}

// ── UI updaters ────────────────────────────────────────────────────

function setDockerStatus(ok) {
  const el = document.getElementById('docker-status');
  el.innerHTML = ok
    ? '<span class="dot dot-green"></span><span>Docker connected</span>'
    : '<span class="dot dot-red"></span><span>Docker unavailable</span>';
}

function updateService(name, info) {
  const s = info.state || 'exited';
  const h = info.health || '';
  document.getElementById(name + '-state').textContent = s + (h ? ` (${h})` : '');

  const dot = document.getElementById(name + '-dot');
  dot.className = 'dot ' + (s === 'running'
    ? (h === 'healthy' || !h ? 'dot-green' : 'dot-yellow')
    : 'dot-red');

  if (info.status) document.getElementById(name + '-detail').textContent = info.status;
}

function toggle(id, visible) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('hidden', !visible);
}

// ── Actions ────────────────────────────────────────────────────────

async function action(name) {
  switchTab('tasks');
  clearConsole();
  setTaskStatus('Starting...');
  const body = { action: name };
  if (name === 'compile' || name === 'compile-extractors') {
    body.client_build = document.getElementById('client-build').value || '5875';
  }
  try {
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.error) { addLine('Error: ' + data.error, 'text-red-400'); setTaskStatus('Error'); return; }
    streamTask(data.task_id, data.name);
  } catch (e) {
    addLine('Request failed: ' + e.message, 'text-red-400');
    setTaskStatus('Error');
  }
}

async function extract(step) {
  const clientPath = document.getElementById('client-path').value.trim();
  if (!clientPath) {
    switchTab('tasks');
    clearConsole();
    addLine('Enter the WoW client directory path first.', 'text-amber-400');
    document.getElementById('client-path').focus();
    return;
  }
  switchTab('tasks');
  clearConsole();
  setTaskStatus('Starting extraction...');
  try {
    const clientBuild = document.getElementById('client-build').value || '5875';
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: step === 'all' ? 'extract' : `extract-${step}`,
        client_path: clientPath,
        client_build: clientBuild,
      }),
    });
    const data = await res.json();
    if (data.error) { addLine('Error: ' + data.error, 'text-red-400'); setTaskStatus('Error'); return; }
    streamTask(data.task_id, data.name);
  } catch (e) {
    addLine('Request failed: ' + e.message, 'text-red-400');
    setTaskStatus('Error');
  }
}

// ── Streaming ──────────────────────────────────────────────────────

function streamTask(taskId, name) {
  if (taskEventSource) taskEventSource.close();
  activeTaskId = taskId;
  setTaskStatus(name);
  addLine(`=== ${name} ===`, 'text-blue-400 font-semibold');

  taskEventSource = new EventSource(`/api/tasks/${taskId}/stream`);
  taskEventSource.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.line) addLine(d.line);
  };
  taskEventSource.addEventListener('done', e => {
    const d = JSON.parse(e.data);
    const ok = d.status === 'success';
    addLine(
      `\n=== ${ok ? 'Completed' : 'Failed'} (exit code ${d.exit_code}) ===`,
      ok ? 'text-green-400 font-semibold' : 'text-red-400 font-semibold',
    );
    setTaskStatus(ok ? `${name} - Done` : `${name} - Failed`);
    taskEventSource.close();
    taskEventSource = null;
    fetchStatus();
    fetchSetupStatus();
  });
  taskEventSource.onerror = () => { taskEventSource.close(); taskEventSource = null; };
}

function streamLogs(service) {
  if (logEventSource) { logEventSource.close(); logEventSource = null; }
  setTaskStatus(`Logs: ${service}`);
  logEventSource = new EventSource(`/api/logs/${service}`);
  logEventSource.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.line) addLine(d.line);
  };
  logEventSource.onerror = () => {
    addLine('\n[Connection lost]', 'text-slate-500');
    logEventSource.close();
    logEventSource = null;
  };
}

// ── Console ────────────────────────────────────────────────────────

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.console-tab').forEach(el => {
    el.classList.remove('text-white', 'border-blue-500');
    el.classList.add('text-slate-400', 'border-transparent');
  });
  const active = document.getElementById('tab-' + tab);
  if (active) {
    active.classList.remove('text-slate-400', 'border-transparent');
    active.classList.add('text-white', 'border-blue-500');
  }
  const attachEl = document.getElementById('console-attach-cmd');
  if (tab === 'realmd') {
    attachEl.textContent = 'docker attach vmangos-realmd-1';
    attachEl.classList.remove('hidden');
  } else if (tab === 'mangosd') {
    attachEl.textContent = 'docker attach vmangos-mangosd-1';
    attachEl.classList.remove('hidden');
  } else {
    attachEl.textContent = '';
    attachEl.classList.add('hidden');
  }
  if (logEventSource) { logEventSource.close(); logEventSource = null; }
  clearConsole();
  if (tab === 'tasks') {
    if (activeTaskId && taskEventSource) setTaskStatus('Reconnecting...');
    else { addLine('Run an action above to see output here.', 'text-slate-500'); setTaskStatus('Idle'); }
  } else {
    streamLogs(tab);
  }
}

function clearConsole() {
  document.getElementById('console-output').innerHTML = '';
  lineCount = 0;
  updateLineCount();
}

function addLine(text, extraClass) {
  const c = document.getElementById('console-output');
  const atBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 60;
  const el = document.createElement('div');
  el.className = 'console-line' + (extraClass ? ' ' + extraClass : '');
  el.textContent = text.replace(/\n$/, '');
  c.appendChild(el);
  lineCount++;
  updateLineCount();
  if (lineCount > 5000) { c.removeChild(c.firstChild); lineCount--; }
  if (atBottom) c.scrollTop = c.scrollHeight;
}

function updateLineCount() {
  document.getElementById('console-line-count').textContent = lineCount + ' lines';
}

function setTaskStatus(text) {
  document.getElementById('console-task-name').textContent = text;
}

// ── Accounts ───────────────────────────────────────────────────────

const GM_LABELS = ['Player', 'GM 1', 'GM 2', 'GM 3', 'Admin'];
const GM_COLORS = [
  'bg-slate-700 text-slate-300',
  'bg-blue-900/70 text-blue-300',
  'bg-violet-900/70 text-violet-300',
  'bg-amber-900/70 text-amber-300',
  'bg-red-900/70 text-red-300',
];

function gmBadge(level) {
  const l = Math.min(Math.max(level, 0), 4);
  return `<span class="inline-block px-2 py-0.5 rounded text-xs font-medium ${GM_COLORS[l]}">${GM_LABELS[l]}</span>`;
}

async function loadAccounts() {
  const wrap = document.getElementById('accounts-wrap');
  wrap.innerHTML = '<p class="text-xs text-slate-500">Loading…</p>';
  hideAccountMsg();
  try {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    if (data.error) { wrap.innerHTML = `<p class="text-xs text-red-400">${data.error}</p>`; return; }
    renderAccountsTable(data);
  } catch (e) {
    wrap.innerHTML = `<p class="text-xs text-red-400">Failed to load accounts: ${e.message}</p>`;
  }
}

function renderAccountsTable(accounts) {
  const wrap = document.getElementById('accounts-wrap');
  if (!accounts.length) {
    wrap.innerHTML = '<p class="text-xs text-slate-500">No accounts found.</p>';
    return;
  }
  const rows = accounts.map(a => {
    const login = a.last_login ? a.last_login.replace('T', ' ').slice(0, 16) : '—';
    const onlineDot = a.online
      ? '<span class="inline-block w-2 h-2 rounded-full bg-green-400 shadow-sm shadow-green-500"></span>'
      : '<span class="inline-block w-2 h-2 rounded-full bg-slate-600"></span>';
    const lockedBadge = a.locked
      ? '<span class="inline-block px-1.5 py-0.5 rounded text-xs bg-red-950/60 text-red-400 border border-red-900/40">locked</span>'
      : '';
    return `<tr class="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
      <td class="py-2.5 px-3 font-mono text-slate-200 text-sm">${a.username} ${lockedBadge}</td>
      <td class="py-2.5 px-3">${gmBadge(a.gmlevel)}</td>
      <td class="py-2.5 px-3 text-xs text-slate-400 font-mono tabular-nums">${login}</td>
      <td class="py-2.5 px-3">${onlineDot}</td>
      <td class="py-2.5 px-3">
        <div class="flex gap-3">
          <button onclick="openEditModal('${a.username}', ${a.gmlevel})"
            class="text-xs text-blue-400 hover:text-blue-300 transition-colors cursor-pointer">Edit</button>
          <button onclick="deleteAccount('${a.username}')"
            class="text-xs text-red-400 hover:text-red-300 transition-colors cursor-pointer">Delete</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  wrap.innerHTML = `<div class="overflow-x-auto rounded-md border border-slate-800">
    <table class="w-full text-sm">
      <thead class="bg-slate-800/40">
        <tr>
          <th class="py-2 px-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Username</th>
          <th class="py-2 px-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Level</th>
          <th class="py-2 px-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Last Login</th>
          <th class="py-2 px-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Online</th>
          <th class="py-2 px-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

async function createAccount() {
  const username = document.getElementById('new-username').value.trim().toUpperCase();
  const password = document.getElementById('new-password').value;
  hideAccountMsg();

  if (!username || !password) {
    showAccountMsg('Username and password are required.', 'error');
    return;
  }
  try {
    const res = await fetch('/api/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (data.error) { showAccountMsg(data.error, 'error'); return; }
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    showAccountMsg(`Account "${username}" created.`, 'ok');
    loadAccounts();
  } catch (e) {
    showAccountMsg('Request failed: ' + e.message, 'error');
  }
}

function openEditModal(username, gmlevel) {
  document.getElementById('modal-username').value = username;
  document.getElementById('modal-display-name').textContent = username;
  document.getElementById('modal-gmlevel').value = String(gmlevel);
  document.getElementById('modal-password').value = '';
  document.getElementById('modal-error').classList.add('hidden');
  document.getElementById('modal-error').textContent = '';
  document.getElementById('account-modal').classList.remove('hidden');
  document.getElementById('modal-password').focus();
}

function closeModal() {
  document.getElementById('account-modal').classList.add('hidden');
}

async function saveAccount() {
  const username = document.getElementById('modal-username').value;
  const password = document.getElementById('modal-password').value.trim();
  const gmlevel  = parseInt(document.getElementById('modal-gmlevel').value, 10);
  const errEl    = document.getElementById('modal-error');

  errEl.classList.add('hidden');
  errEl.textContent = '';

  const saves = [];

  if (password) {
    saves.push(
      fetch(`/api/accounts/${encodeURIComponent(username)}/password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      }).then(r => r.json())
    );
  }

  saves.push(
    fetch(`/api/accounts/${encodeURIComponent(username)}/gmlevel`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gmlevel }),
    }).then(r => r.json())
  );

  try {
    const results = await Promise.all(saves);
    const failed = results.find(r => r.error);
    if (failed) {
      errEl.textContent = failed.error;
      errEl.classList.remove('hidden');
      return;
    }
    closeModal();
    loadAccounts();
  } catch (e) {
    errEl.textContent = 'Request failed: ' + e.message;
    errEl.classList.remove('hidden');
  }
}

async function deleteAccount(username) {
  if (!confirm(`Delete account "${username}"? This cannot be undone.`)) return;
  hideAccountMsg();
  try {
    const res = await fetch(`/api/accounts/${encodeURIComponent(username)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.error) { showAccountMsg(data.error, 'error'); return; }
    loadAccounts();
  } catch (e) {
    showAccountMsg('Request failed: ' + e.message, 'error');
  }
}

function showAccountMsg(text, type) {
  const el = document.getElementById('account-msg');
  el.textContent = text;
  if (type === 'error') {
    el.className = 'text-xs rounded-md px-3 py-2 border bg-red-950/50 border-red-900/50 text-red-300';
  } else {
    el.className = 'text-xs rounded-md px-3 py-2 border bg-emerald-950/50 border-emerald-900/50 text-emerald-300';
  }
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 5000);
}

function hideAccountMsg() {
  document.getElementById('account-msg').classList.add('hidden');
}
