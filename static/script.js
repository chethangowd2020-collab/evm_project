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
  const headers = { 'Content-Type': 'application/json' };
  const currentUsn = sessionStorage.getItem('student_usn');
  if (currentUsn) headers['X-Student-USN'] = currentUsn;

  const res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: headers,
    body: JSON.stringify(data)
  });
  return res.json();
}

async function apiGet(url) {
  const headers = {};
  const currentUsn = sessionStorage.getItem('student_usn');
  if (currentUsn) headers['X-Student-USN'] = currentUsn;

  const res = await fetch(url, {
    credentials: 'include',
    headers: headers
  });
  return res.json();
}

async function toggleResults(btn) {
  if (btn) setLoading(btn, true, 'Updating...');
  const data = await apiFetch('/api/admin/toggle_results', {});
  if (btn) setLoading(btn, false);

  if (data.success) {
    if (typeof loadVotingStatus === 'function') {
      loadVotingStatus();
    } else {
      alert(data.published ? "Results published!" : "Results hidden!");
    }
  } else {
    alert(data.message || "Failed to update results status.");
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
  const usnRegex = /^1JB\d{2}[A-Z]{2}\d{3}$/;

  if (!usn || !password) {
    alert("Please enter credentials");
    return;
  }

  // Validate format only for student login (not admin)
  if (usnInput.id === 'login-usn' && !usnRegex.test(usn)) {
    alert("Invalid USN format. Pattern: 1JB + 2 digits + 2 letters + 3 digits (e.g. 1JB21CS001)");
    return;
  }

  const data = await apiFetch('/api/login', { usn, password });

  if (data.success) {
    // ✅ mark session active (IMPORTANT)
    setAuthActive(true);
    
    if (data.role === 'student' && data.usn) {
      sessionStorage.setItem('student_usn', data.usn);
    }

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

// ─── USN Prefix Enforcement ───────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Targets 'usn' (Register) and 'login-usn' (Login student tab)
  ['usn', 'login-usn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      if (!el.value) el.value = '1JB';
      el.maxLength = 10;
      el.addEventListener('input', function() {
        if (!this.value.toUpperCase().startsWith('1JB')) {
          this.value = '1JB';
        }
        this.value = this.value.toUpperCase();
      });
    }
  });
});