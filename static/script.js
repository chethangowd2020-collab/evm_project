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

let _resultsSortMode = 'sem'; // 'sem' or 'class'

function setResultsSort(mode) {
  _resultsSortMode = mode;
  loadAdminResults();
}

async function loadAdminResults() {
  const container = document.getElementById('admin-results-container') || document.getElementById('public-results-container');
  if (!container) return;

  try {
    const endpoint = window.location.pathname.includes('admin') ? '/api/admin/results' : '/api/results_public';
    const data = await apiGet(endpoint);
    if (!data.success) return;

    // Add sort controls at the top
    container.innerHTML = `
      <div class="results-sort-controls" style="margin-bottom: 2rem; display: flex; align-items: center; gap: 15px; padding: 12px 20px; background: var(--surface); border-radius: var(--radius-sm); border: 1px solid var(--border); box-shadow: var(--shadow);">
        <span style="font-weight: 600; font-size: 0.9rem; color: var(--text-soft);">Sort / Group:</span>
        <button class="btn btn-sm ${_resultsSortMode === 'sem' ? 'btn-primary' : 'btn-secondary'}" onclick="setResultsSort('sem')" style="min-width: 100px;">Semester</button>
        <button class="btn btn-sm ${_resultsSortMode === 'class' ? 'btn-primary' : 'btn-secondary'}" onclick="setResultsSort('class')" style="min-width: 100px;">Section Letter</button>
        <button class="btn btn-sm ${_resultsSortMode === 'votes' ? 'btn-primary' : 'btn-secondary'}" onclick="setResultsSort('votes')" style="min-width: 100px;">Votes</button>
        <button class="btn btn-sm ${_resultsSortMode === 'name' ? 'btn-primary' : 'btn-secondary'}" onclick="setResultsSort('name')" style="min-width: 100px;">Name</button>
        <button class="btn btn-sm ${_resultsSortMode === 'usn' ? 'btn-primary' : 'btn-secondary'}" onclick="setResultsSort('usn')" style="min-width: 100px;">USN</button>
      </div>
    `;

    let sortedKeys = Object.keys(data.classes);

    if (_resultsSortMode === 'class') {
      // Sort primarily by Section Letter (A, B, C...) then by Semester
      sortedKeys.sort((a, b) => {
        const partA = a.split(' - '); // ["Sem 1", "CSE A"]
        const partB = b.split(' - ');
        const letterA = partA[1].slice(-1); // e.g. "A"
        const letterB = partB[1].slice(-1);
        
        if (letterA !== letterB) return letterA.localeCompare(letterB);
        // If same class, compare the Semester part (index 0)
        return partA[0].localeCompare(partB[0]);
      });
    } else {
      // Default: Sort by Semester (1-8) then by Class Section Letter (A-O)
      sortedKeys.sort((a, b) => {
        const partA = a.split(' - ');
        const partB = b.split(' - ');
        // Compare semester first
        if (partA[0] !== partB[0]) return partA[0].localeCompare(partB[0]);
        // Then compare the section letter (A, B, C...)
        return partA[1].slice(-1).localeCompare(partB[1].slice(-1));
      });
    }

    for (const clsKey of sortedKeys) {
      let males = [...(data.classes[clsKey].males || [])];
      let females = [...(data.classes[clsKey].females || [])];

      // Internal sorting of candidates based on selected mode
      if (_resultsSortMode === 'name') {
        males.sort((a, b) => a.name.localeCompare(b.name));
        females.sort((a, b) => a.name.localeCompare(b.name));
      } else if (_resultsSortMode === 'usn') {
        males.sort((a, b) => a.usn.localeCompare(b.usn));
        females.sort((a, b) => a.usn.localeCompare(b.usn));
      } else {
        // Default or explicit votes sorting (Descending)
        males.sort((a, b) => b.votes - a.votes);
        females.sort((a, b) => b.votes - a.votes);
      }
      
      const classDiv = document.createElement('div');
      classDiv.className = 'results-class';
      classDiv.innerHTML = `
        <div class="results-class-header">📍 ${clsKey}</div>
        <div class="results-grid">
          <div class="results-gender-col">
            <h4>Male Candidates</h4>
            ${males.length > 0 ? renderResultRows(males) : '<p style="color: var(--text-soft); font-size: 0.85rem; padding: 10px;">no candidate have been registered</p>'}
          </div>
          <div class="results-gender-col">
            <h4>Female Candidates</h4>
            ${females.length > 0 ? renderResultRows(females) : '<p style="color: var(--text-soft); font-size: 0.85rem; padding: 10px;">no candidate have been registered</p>'}
          </div>
        </div>
      `;
      container.appendChild(classDiv);
    }
  } catch (e) { console.error("Admin Results Error:", e); }
}

function renderResultRows(list) {
  // Calculate the highest vote count to correctly identify the winner(s) 
  // when the list is sorted by Name or USN instead of Votes.
  const maxVotes = list.length > 0 ? Math.max(...list.map(c => c.votes)) : 0;

  return list.map((c, i) => `
    <div class="result-row ${c.votes > 0 && c.votes === maxVotes ? 'winner' : ''}">
      <span class="rank">${c.votes > 0 && c.votes === maxVotes ? '👑' : (i + 1)}</span>
      <span class="rname">${c.name}</span>
      <span class="rvotes">${c.votes} votes</span>
    </div>
  `).join('');
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
    // Permanent Fix: Clear client-side storage before setting new identity
    const prevSplash = sessionStorage.getItem('uni_vote_splash_shown');
    sessionStorage.clear();
    if (prevSplash) sessionStorage.setItem('uni_vote_splash_shown', prevSplash);

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

  // Initialize results if on admin or results page
  if (window.location.pathname.includes('admin') || window.location.pathname.includes('results')) {
    loadAdminResults();
  }

  // Initialize dashboard widget if on dashboard page
  if (window.location.pathname.includes('dashboard')) {
    loadVoteStats();
    setInterval(loadVoteStats, 15000); // Refresh every 15 seconds
  }
});