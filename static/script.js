// ─── Shared utilities ─────────────────────────────────

function showAlert(el, msg, type = 'error') {
  el.textContent = msg;
  el.className = 'alert alert-' + type;
  el.style.display = 'block';
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideAlert(el) {
  el.style.display = 'none';
}

function setLoading(btn, loading, text = '') {
  if (loading) {
    btn._origText = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span>${text || 'Please wait...'}`;
    btn.disabled = true;
  } else {
    btn.innerHTML = btn._origText || text;
    btn.disabled = false;
  }
}

const _evmSessionKey = 'evm_session_active';

function setAuthActive(active) {
  if (active) {
    localStorage.setItem(_evmSessionKey, '1');
  } else {
    localStorage.removeItem(_evmSessionKey);
  }
}

function isAuthActive() {
  return localStorage.getItem(_evmSessionKey) === '1';
}

function initLogoutOnExit() {
  let internalNav = false;

  document.addEventListener('click', event => {
    const anchor = event.target.closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href');
    if (!href) return;
    if (href.startsWith('/') || href.startsWith(window.location.origin)) {
      internalNav = true;
    }
    if (href === '/logout') {
      setAuthActive(false);
    }
  });

  window.addEventListener('beforeunload', () => {
    if (internalNav) return;
    setAuthActive(false);
    const payload = new Blob(['{}'], { type: 'application/json' });
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/logout', payload);
    } else {
      fetch('/api/logout', { method: 'POST', keepalive: true, body: payload });
    }
  });
}

function enforceAuthOnProtectedPages() {
  const publicPaths = ['/login', '/register', '/admin_login', '/'];
  const path = window.location.pathname;
  if (publicPaths.some(p => path === p || path.startsWith(p + '/'))) return;
  if (!isAuthActive()) {
    window.location.href = '/login';
  }
}

initLogoutOnExit();
enforceAuthOnProtectedPages();

async function apiFetch(url, data) {
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

async function apiGet(url) {
  const res = await fetch(url, {
    credentials: 'include'
  });
  return res.json();
}
