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

function exportResultsCSV() {
  window.location.href = '/api/admin/export_results';
}

async function loadVoteStats() {
  const container = document.getElementById('vote-stats-widget');
  if (!container) return;

  try {
    const data = await apiGet('/api/vote_stats');
    if (data.success) {
      const pct = data.percentage;
      container.innerHTML = `
        <div class="card" style="padding: 1.5rem; margin-bottom: 2rem; animation: cardFadeIn 0.5s ease-out;">
          <div class="section-title" style="margin-bottom: 0.5rem;">
            <span>📊 Class Voting Participation</span>
            <span style="margin-left: auto; color: var(--primary); font-weight: 800;">${pct}%</span>
          </div>
          <div class="vote-bar" style="height: 12px; margin: 12px 0; background: var(--bg);">
            <div class="vote-bar-fill" style="width: ${pct}%; box-shadow: 0 0 10px rgba(91,108,249,0.3);"></div>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: var(--text-soft); font-weight: 500;">
            <span>${data.voted} students voted</span>
            <span>Class Size: ${data.total}</span>
          </div>
        </div>
      `;
    }
  } catch (e) { console.error("Stats Error:", e); }
}

async function handleLogin() {
  // Note: login.html uses admin-usn and admin-password for admin tab
  const usnInput = document.getElementById('login-usn') || document.getElementById('admin-usn');
  const pwdInput = document.getElementById('login-password') || document.getElementById('admin-password');
  
  if (!usnInput || !pwdInput) return;

  // Determine which alert box to use based on the active tab
  const alertEl = (usnInput.id === 'login-usn') 
    ? document.getElementById('login-alert') 
    : document.getElementById('admin-alert');

  const usn = usnInput.value.trim().toUpperCase();
  const password = pwdInput.value;
  const usnRegex = /^1JB\d{2}[A-Z]{2}\d{3}$/;

  if (!usn || !password) {
    if (alertEl) showAlert(alertEl, "Please enter credentials"); else alert("Please enter credentials");
    return;
  }

  // Validate format only for student login (not admin)
  if (usnInput.id === 'login-usn' && !usnRegex.test(usn)) {
    if (alertEl) showAlert(alertEl, "Invalid USN format."); else alert("Invalid USN format.");
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
    if (alertEl) showAlert(alertEl, data.message || "Login failed"); else alert(data.message || "Login failed");
  }
}

// ─── USN Prefix Enforcement ───────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Targets 'usn' (Register) and 'login-usn' (Login student tab)
  ['usn', 'login-usn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      const alertEl = id === 'usn' ? document.getElementById('alertBox') : document.getElementById('login-alert');
      const usnRegex = /^1JB\d{2}[A-Z]{2}\d{3}$/;

      if (!el.value) el.value = '1JB';
      el.maxLength = 10;

      el.addEventListener('input', function() {
        if (!this.value.toUpperCase().startsWith('1JB')) {
          this.value = '1JB';
        }
        this.value = this.value.toUpperCase();

        // Instant validation when full length is reached
        if (this.value.length === 10) {
          if (!usnRegex.test(this.value)) {
            if (alertEl) showAlert(alertEl, 'Invalid USN format.');
          } else if (alertEl) {
            hideAlert(alertEl);
          }
        }
      });
    }
  });

  // Auto-uppercase for Student Name field
  const nameInput = document.getElementById('name');
  if (nameInput) {
    nameInput.addEventListener('input', function() {
      this.value = this.value.toUpperCase();
    });
  }

  // Initialize dashboard widget if on dashboard page
  if (window.location.pathname.includes('dashboard')) {
    loadVoteStats();
    setInterval(loadVoteStats, 15000); // Refresh every 15 seconds
  }
});