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
    sessionStorage.setItem(_evmSessionKey, '1');
  } else {
    sessionStorage.removeItem(_evmSessionKey);
  }
}

function isAuthActive() {
  return sessionStorage.getItem(_evmSessionKey) === '1';
}

function enforceAuthOnProtectedPages() {
  const publicPaths = ['/login', '/register', '/admin_login', '/'];
  const path = window.location.pathname;
  if (publicPaths.some(p => path === p || path.startsWith(p + '/'))) return;
  if (!isAuthActive()) {
    window.location.href = '/login';
  }
}

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

async function publishResults() {
  const data = await apiFetch('/api/admin/publish_results', {});
  if (data.success) {
    alert(data.message || "Results published!");
    location.reload(); // Refresh the page to show updated status
  } else {
    alert(data.message || "Failed to publish results.");
  }
}

function checkResults() {
  fetch('/api/results_public')
    .then(res => res.json())
    .then(data => {
      if (!data.success) {
        alert("Results have not yet published !!");
        return;
      }

      // if published → go to results page
      window.location.href = "/results";
    })
    .catch(() => {
      alert("Something went wrong");
    });
}



function viewResults() {
  window.location.href = "/results";
}

async function handleLogin() {
  // Note: login.html uses admin-usn and admin-password for admin tab
  const usnInput = document.getElementById('login-usn') || document.getElementById('admin-usn');
  const pwdInput = document.getElementById('login-password') || document.getElementById('admin-password');
  
  if (!usnInput || !pwdInput) return;

  const usn = usnInput.value.trim().toUpperCase();
  const password = pwdInput.value;

  if (!usn || !password) {
    alert("Please enter credentials");
    return;
  }

  const data = await apiFetch('/api/login', { usn, password });

  if (data.success) {
    // ✅ mark session active (IMPORTANT)
    setAuthActive(true);

    // ✅ redirect based on role
    if (data.role === 'admin') {
      window.location.href = '/admin';
    } else {
      window.location.href = '/dashboard';
    }
  } else {
    alert(data.message || "Login failed");
  }
}