from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import psycopg2
from datetime import timedelta
from psycopg2.extras import RealDictCursor
import hashlib
import random
import os
import smtplib
import tempfile
from email.message import EmailMessage
import string
import sqlite3

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv('SECRET_KEY', 'evm_secret_key_2024')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Session security and persistence configuration
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() in ('1', 'true', 'yes')
ADMIN_USN = os.getenv('ADMIN_USN', 'ADMIN').upper()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

# Supabase Connection String (e.g., postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres)
DATABASE_URL = os.getenv('DATABASE_URL')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'database.db')

USE_SQLITE = not DATABASE_URL

if not DATABASE_URL:
    print("WARNING: DATABASE_URL not found. Using local SQLite database.")

# Email settings (set as environment variables)
SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
EMAIL_FROM = os.getenv('EMAIL_FROM')

class SQLiteCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
    
    def execute(self, query, params=None):
        query = query.replace('%s', '?')
        return self.cursor.execute(query, params or ())
    
    def fetchone(self):
        return self.cursor.fetchone()
    
    def fetchall(self):
        return self.cursor.fetchall()
    
    def __iter__(self):
        return iter(self.cursor)

class SQLiteConnection:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
    
    def cursor(self):
        return SQLiteCursorWrapper(self.conn.cursor())
    
    def commit(self):
        return self.conn.commit()
    
    def close(self):
        return self.conn.close()

def get_db():
    if USE_SQLITE:
        return SQLiteConnection(DATABASE_PATH)
    else:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn


def row_get(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        if key in row:
            return row[key]
        lower = key.lower()
        if lower in row:
            return row[lower]
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        if hasattr(row, 'get'):
            lower = key.lower()
            return row.get(lower, default)
        return default


def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Students table
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        usn TEXT PRIMARY KEY,
        name TEXT,
        phone TEXT,
        class TEXT,
        semester TEXT,
        password TEXT,
        isVerified INTEGER DEFAULT 0,
        hasVoted INTEGER DEFAULT 0
    )''')
    
    if USE_SQLITE:
        # Add missing columns to students table
        try:
            c.execute('ALTER TABLE students ADD COLUMN name TEXT')
        except Exception as e:
            pass
        try:
            c.execute('ALTER TABLE students ADD COLUMN semester TEXT')
        except Exception as e:
            pass
    
    # Candidates table
    if USE_SQLITE:
        c.execute('''CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usn TEXT UNIQUE,
            name TEXT,
            class TEXT,
            semester TEXT,
            gender TEXT,
            votes INTEGER DEFAULT 0
        )''')
        # Try to add semester column if it doesn't exist
        try:
            c.execute('ALTER TABLE candidates ADD COLUMN semester TEXT')
        except Exception as e:
            pass  # Column might already exist
    else:
        c.execute('''CREATE TABLE IF NOT EXISTS candidates (
            id SERIAL PRIMARY KEY,
            usn TEXT UNIQUE,
            name TEXT,
            class TEXT,
            semester TEXT,
            gender TEXT,
            votes INTEGER DEFAULT 0
        )''')
    
    # Votes table
    if USE_SQLITE:
        c.execute('''CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usn TEXT,
            class TEXT,
            male_candidate_id INTEGER,
            female_candidate_id INTEGER
        )''')
    else:
        c.execute('''CREATE TABLE IF NOT EXISTS votes (
            id SERIAL PRIMARY KEY,
            usn TEXT,
            class TEXT,
            male_candidate_id INTEGER,
            female_candidate_id INTEGER
        )''')
    
    # OTPS table
    c.execute('''CREATE TABLE IF NOT EXISTS otps (
        usn TEXT PRIMARY KEY,
        otp TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Settings table
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # Insert default voting_enabled setting
    if USE_SQLITE:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('voting_enabled', '0')")
    else:
        c.execute("INSERT INTO settings (key, value) VALUES ('voting_enabled', '0') ON CONFLICT (key) DO NOTHING")
    
    conn.commit()
    conn.close()
    # Results published setting
    if USE_SQLITE:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('results_published', '0')")
    else:
        c.execute("INSERT INTO settings (key, value) VALUES ('results_published', '0') ON CONFLICT (key) DO NOTHING")


try:
    init_db()
except Exception as e:
    print(f"Database initialization failed: {e}")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.after_request
def add_header(response):
    """
    Add headers to prevent the browser from caching sensitive pages.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Vary"] = "Cookie"
    return response

# ─── ROUTES ───────────────────────────────────────────────────

@app.route('/')
def index():
    if request.args.get('force_login') == '1':
        session.clear()
        return redirect(url_for('login'))
    if 'usn' in session:
        return redirect(url_for('admin' if session.get('role') == 'admin' else 'dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET'])
def register():
    if request.args.get('force_login') == '1':
        session.clear()
    return render_template('register.html')

@app.route('/login', methods=['GET'])
def login():
    if request.args.get('force_login') == '1':
        session.clear()

    if request.args.get('force_admin') == '1':
        return render_template(
            'login.html',
            alert_message='Please sign in as admin to continue.',
            active_tab='admin'
        )

    return render_template('login.html')

@app.route('/force_login')
def force_login():
    session.clear()
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'usn' not in session:
        return redirect(url_for('login'))
    # Redirect admins away from student dashboard
    if session.get('role') == 'admin':
        return redirect(url_for('admin'))
        
    return render_template(
        'dashboard.html', 
        name=session.get('name', 'Student'),
        cls=session.get('class', '—'),
        sem=session.get('semester', '—'))

@app.route('/vote')
def vote():
    if 'usn' not in session:
        return redirect(url_for('login'))
    # Role guard: Admins cannot vote
    if session.get('role') == 'admin':
        return redirect(url_for('admin'))
    return render_template('vote.html')

@app.route('/candidate_register')
def candidate_register():
    if 'usn' not in session:
        return redirect(url_for('login'))
    # Role guard: Admins cannot register as candidates
    if session.get('role') == 'admin':
        return redirect(url_for('admin'))
    return render_template(
        'candidate_register.html',
        name=session.get('name', 'Student'),
        cls=session.get('class', '—'),
        sem=session.get('semester', '—'))

@app.route('/admin')
def admin():
    if session.get('role') == 'admin':
        return render_template('admin.html')

    if request.args.get('force_admin') == '1':
        return render_template(
            'login.html',
            alert_message='Please sign in as admin to access the admin portal.',
            active_tab='admin'
        )

    return redirect(url_for('login'))

@app.route('/force_admin')
def force_admin():
    if session.get('role') == 'admin':
        return redirect(url_for('admin', force_admin='1'))

    return render_template(
        'login.html',
        alert_message='Please sign in as admin to access the admin portal.',
        active_tab='admin'
    )

@app.route('/admin_login')
def admin_login():
    return render_template('admin_login.html')

@app.route('/results')
def results():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('results.html')
@app.route('/results_public_page')
def results_public_page():
    return render_template('results_public.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/manifest.json')
def serve_manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')


# ─── API ENDPOINTS ────────────────────────────────────────────

def send_email(destination, subject, body):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = destination
    msg.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

@app.route('/api/send_otp', methods=['POST'])
def send_otp():
    data = request.json
    email = data.get('email')
    usn = data.get('usn')
    
    # Generate alphanumeric captcha
    captcha_text = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    captcha_question = f"Type this code: {captcha_text}"
    captcha_answer = captcha_text
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO otps (usn, otp) VALUES (%s, %s) ON CONFLICT (usn) DO UPDATE SET otp = EXCLUDED.otp, created_at = CURRENT_TIMESTAMP',
        (usn.upper(), captcha_answer)
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True, 
        'captcha_question': captcha_question, 
        'message': 'Captcha generated!'
    })

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    usn = data.get('usn', '').upper()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    cls = data.get('class', '').strip()
    sem = data.get('semester', '').strip()
    otp = data.get('otp')
    password = data.get('password')

    if not name:
        return jsonify({'success': False, 'message': 'Name is required'})

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT otp FROM otps WHERE usn=%s', (usn,))
    otp_rec = cur.fetchone()
    
    if not otp_rec or otp_rec['otp'] != otp:
        conn.close()
        return jsonify({'success': False, 'message': 'Invalid OTP'})

    cur.execute('SELECT usn FROM students WHERE usn=%s', (usn,))
    if cur.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'USN already registered'})

    cur.execute(
        'INSERT INTO students (usn, name, phone, class, semester, password, isVerified, hasVoted) VALUES (%s,%s,%s,%s,%s,%s,1,0)',
        (usn, name, email, cls, sem, hash_password(password))
    )
    conn.commit()
    cur.execute('DELETE FROM otps WHERE usn=%s', (usn,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Registration successful!'})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    identifier = data.get('usn', '').upper()  # Can be USN or email
    password = data.get('password')

    if identifier == ADMIN_USN and password == ADMIN_PASSWORD:
        session.clear() # Clear any old session data
        session.permanent = True
        session['role'] = 'admin'
        session['usn'] = ADMIN_USN
        return jsonify({'success': True, 'role': 'admin'})

    conn = get_db()
    cur = conn.cursor()
    if '@' in identifier:
        cur.execute('SELECT * FROM students WHERE phone=%s', (identifier.lower(),))
    else:
        cur.execute('SELECT * FROM students WHERE usn=%s', (identifier,))
    
    student = cur.fetchone()
    conn.close()

    if not student:
        return jsonify({
            'success': False,
            'message': 'USN not registered please register your USN and then login'
        })

    if student['password'] != hash_password(password):
        return jsonify({'success': False, 'message': 'Invalid password'})

    session.clear() # Clear any old session data
    session.permanent = False
    session['usn'] = str(student['usn']).upper()
    session['name'] = student['name']
    session['class'] = student['class']
    session['semester'] = student['semester']
    session['role'] = 'student'
    session.modified = True # Force Flask to save the session
    return jsonify({'success': True, 'role': 'student'})

@app.route('/api/student_info')
def student_info():
    if 'usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT usn, name, class, semester, hasVoted FROM students WHERE usn=%s', (session['usn'],))
        student = cur.fetchone()
        if not student:
            conn.close()
            return jsonify({'success': False, 'message': 'Student record not found. Please log in again.'}), 401

        cur.execute('SELECT id FROM candidates WHERE usn=%s', (session['usn'],))
        is_candidate = cur.fetchone()
        conn.close()

        has_voted = row_get(student, 'hasVoted', False)
        if isinstance(has_voted, str):
            has_voted = has_voted.strip() not in ('', '0', 'false', 'False')
        else:
            has_voted = bool(has_voted)

        return jsonify({
            'success': True,
            'usn': student['usn'],
            'name': student['name'],
            'class': student['class'],
            'semester': student['semester'],
            'hasVoted': has_voted,
            'isCandidate': bool(is_candidate)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/register_candidate', methods=['POST'])
def register_candidate():
    if 'usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    data = request.json
    usn = session['usn']
    gender = data.get('gender')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT name, class, semester FROM students WHERE usn=%s', (usn,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found'})

    name = (student['name'] or '').strip()
    cls = (student['class'] or '').strip()
    sem = (student['semester'] or '').strip()
    cur.execute('SELECT id FROM candidates WHERE usn=%s', (usn,))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'Already registered as candidate'})

    if not name:
        conn.close()
        return jsonify({'success': False, 'message': 'Student name not found. Please update your registration first.'})

    cur.execute('SELECT COUNT(*) as c FROM candidates WHERE TRIM(class)=%s AND TRIM(semester)=%s AND gender=%s', (cls, sem, gender))
    count = cur.fetchone()
    if count['c'] >= 2:
        conn.close()
        return jsonify({'success': False, 'message': f'Maximum {gender} candidates reached for your class'})

    cur.execute('INSERT INTO candidates (usn, name, class, semester, gender, votes) VALUES (%s,%s,%s,%s,%s,0)',
                 (usn, name, cls, sem, gender))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Registered as candidate successfully!'})

@app.route('/api/candidates')
def get_candidates():
    if 'usn' not in session:
        return jsonify({'success': False})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        # Fetch class from DB to ensure it matches candidates table perfectly
        cur.execute('SELECT class, semester FROM students WHERE usn=%s', (session['usn'],))
        student = cur.fetchone()
        if not student:
            conn.close()
            return jsonify({'success': False, 'message': 'Student record not found'})
        
        cls = (student['class'] or '').strip()
        sem = student['semester']
        if isinstance(sem, str):
            sem = sem.strip()
            if sem == '':
                sem = None
        
        placeholder = '?' if USE_SQLITE else '%s'
        if sem is None:
            male_query = f"SELECT * FROM candidates WHERE class={placeholder} AND (semester IS NULL OR TRIM(semester) = '' OR semester={placeholder}) AND gender={placeholder}"
            female_query = f"SELECT * FROM candidates WHERE class={placeholder} AND (semester IS NULL OR TRIM(semester) = '' OR semester={placeholder}) AND gender={placeholder}"
            params_male = (cls, '', 'Male')
            params_female = (cls, '', 'Female')
        else:
            male_query = f"SELECT * FROM candidates WHERE class={placeholder} AND TRIM(semester)={placeholder} AND gender={placeholder}"
            female_query = f"SELECT * FROM candidates WHERE class={placeholder} AND TRIM(semester)={placeholder} AND gender={placeholder}"
            params_male = (cls, sem, 'Male')
            params_female = (cls, sem, 'Female')
        
        cur.execute(male_query, params_male)
        males = [dict(row) for row in cur.fetchall()]
        cur.execute(female_query, params_female)
        females = [dict(row) for row in cur.fetchall()]
        cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
        setting = cur.fetchone()
        conn.close()
        return jsonify({
            'success': True,
            'males': males,
            'females': females,
            'voting_enabled': setting['value'] == '1' if setting else False
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/submit_vote', methods=['POST'])
def submit_vote():
    if 'usn' not in session or session.get('role') != 'student':
        return jsonify({'success': False, 'message': 'Not logged in'})
    data = request.json
    usn = session['usn']
    cls = session['class']
    male_id = data.get('male_id')
    female_id = data.get('female_id')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT hasVoted FROM students WHERE usn=%s', (usn,))
    student = cur.fetchone()
    if row_get(student, 'hasVoted'):
        conn.close()
        return jsonify({'success': False, 'message': 'You have already voted'})

    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    setting = cur.fetchone()
    if setting['value'] != '1':
        conn.close()
        return jsonify({'success': False, 'message': 'Voting is not enabled'})

    cur.execute('INSERT INTO votes (usn, class, male_candidate_id, female_candidate_id) VALUES (%s,%s,%s,%s)',
                 (usn, cls, male_id, female_id))
    cur.execute('UPDATE candidates SET votes = votes + 1 WHERE id=%s', (male_id,))
    cur.execute('UPDATE candidates SET votes = votes + 1 WHERE id=%s', (female_id,))
    cur.execute('UPDATE students SET hasVoted=1 WHERE usn=%s', (usn,))
    conn.commit()
    conn.close()
    session['hasVoted'] = True
    return jsonify({'success': True, 'message': 'Vote submitted successfully!'})

# ─── ADMIN API ────────────────────────────────────────────────

@app.route('/api/admin/students')
def admin_students():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'SELECT usn, name, phone AS email, class, semester, hasVoted FROM students ORDER BY class, usn'
    )
    rows = cur.fetchall()
    conn.close()

    students = []
    for row in rows:
        student = dict(row)
        if 'hasvoted' in student and 'hasVoted' not in student:
            student['hasVoted'] = student['hasvoted']
        students.append(student)

    return jsonify({'success': True, 'students': students})

@app.route('/api/admin/candidates')
def admin_candidates():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM candidates ORDER BY class, semester, gender')
    rows = cur.fetchall()
    conn.close()

    # Convert DB row objects to plain dictionaries for JSON serialization
    candidates = [dict(row) if not isinstance(row, dict) else row for row in rows]
    return jsonify({'success': True, 'candidates': candidates})

@app.route('/api/admin/toggle_voting', methods=['POST'])
def toggle_voting():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    current = cur.fetchone()
    new_val = '0' if current['value'] == '1' else '1'
    cur.execute("UPDATE settings SET value=%s WHERE key='voting_enabled'", (new_val,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'voting_enabled': new_val == '1'})

@app.route('/api/admin/publish_results', methods=['POST'])
def publish_results():
    if session.get('role') != 'admin':
        return jsonify({'success': False})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE result_status SET published=1 WHERE id=1")

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Results published successfully!'})

@app.route('/api/results_public')
def results_public():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT published FROM result_status WHERE id=1")
    status = cur.fetchone()

    if not status or status['published'] != 1:
        conn.close()
        return jsonify({'success': False})

    cur.execute('SELECT * FROM candidates ORDER BY votes DESC')
    candidates = cur.fetchall()

    conn.close()

    return jsonify({
        'success': True,
        'classes': [dict(c) for c in candidates]
    })

@app.route('/api/admin/publish_results', methods=['POST'])
def publish_results():
    if session.get('role') != 'admin':
        return jsonify({'success': False})

    conn = get_db()
    cur = conn.cursor()

    # ONLY ALLOW IF VOTING IS STOPPED
    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    voting = cur.fetchone()

    if voting and voting['value'] == '1':
        conn.close()
        return jsonify({'success': False, 'message': 'Stop voting before publishing results'})

    cur.execute("UPDATE settings SET value='1' WHERE key='results_published'")
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Results published successfully'})

@app.route('/api/admin/voting_status')
def voting_status():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    setting = cur.fetchone()
    conn.close()
    return jsonify({'success': True, 'voting_enabled': setting['value'] == '1'})

@app.route('/api/admin/delete_student', methods=['POST'])
def delete_student():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    data = request.json
    usn = data.get('usn')
    if not usn:
        return jsonify({'success': False, 'message': 'USN required'})
    
    try:
        conn = get_db()
        cur = conn.cursor()

        # Check if student exists
        cur.execute('SELECT usn FROM students WHERE usn=%s', (usn,))
        if not cur.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Student not found'})

        # 0. If the student has already voted, decrement the counts for candidates they voted for
        cur.execute('SELECT hasVoted FROM students WHERE usn=%s', (usn,))
        student_status = cur.fetchone()
        if student_status and row_get(student_status, 'hasVoted'):
            cur.execute('SELECT male_candidate_id, female_candidate_id FROM votes WHERE usn=%s', (usn,))
            vote_rec = cur.fetchone()
            if vote_rec:
                male_id = row_get(vote_rec, 'male_candidate_id')
                female_id = row_get(vote_rec, 'female_candidate_id')
                if male_id:
                    cur.execute('UPDATE candidates SET votes = votes - 1 WHERE id=%s', (male_id,))
                if female_id:
                    cur.execute('UPDATE candidates SET votes = votes - 1 WHERE id=%s', (female_id,))

        # 1. Clean up candidate data and associated votes received
        cur.execute('SELECT id FROM candidates WHERE usn=%s', (usn,))
        candidate = cur.fetchone()
        if candidate:
            candidate_id = candidate['id']
            cur.execute('DELETE FROM votes WHERE male_candidate_id=%s OR female_candidate_id=%s', (candidate_id, candidate_id))
            cur.execute('DELETE FROM candidates WHERE id=%s', (candidate_id,))

        # 2. Clean up votes cast by the student and the student record
        cur.execute('DELETE FROM votes WHERE usn=%s', (usn,))
        # Delete student
        cur.execute('DELETE FROM students WHERE usn=%s', (usn,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})

@app.route('/api/admin/reset_student_password', methods=['POST'])
def reset_student_password():
    if session.get('role') != 'admin':
        return jsonify({'success': False})

    data = request.json
    usn = (data.get('usn') or '').upper().strip()
    new_password = data.get('new_password') or ''

    if not usn:
        return jsonify({'success': False, 'message': 'USN required'})

    if len(new_password) < 6:
        return jsonify({'success': False, 'message': 'New password must be at least 6 characters'})

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT usn FROM students WHERE usn=%s', (usn,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found'})

    cur.execute(
        'UPDATE students SET password=%s WHERE usn=%s',
        (hash_password(new_password), usn)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Password reset successfully'})

@app.route('/api/admin/delete_candidate', methods=['POST'])
def delete_candidate():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    data = request.json
    candidate_id = data.get('id')
    if not candidate_id:
        return jsonify({'success': False, 'message': 'Candidate ID required'})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        # Get candidate info
        cur.execute('SELECT usn FROM candidates WHERE id=%s', (candidate_id,))
        candidate = cur.fetchone()
        if not candidate:
            conn.close()
            return jsonify({'success': False, 'message': 'Candidate not found'})
        
        # 1. Find all votes involving this candidate to clean up properly
        cur.execute('SELECT usn, male_candidate_id, female_candidate_id FROM votes WHERE male_candidate_id=%s OR female_candidate_id=%s', (candidate_id, candidate_id))
        affected_votes = cur.fetchall()

        for vote in affected_votes:
            male_id = row_get(vote, 'male_candidate_id')
            female_id = row_get(vote, 'female_candidate_id')
            if male_id == int(candidate_id):
                other_id = female_id
            else:
                other_id = male_id
            if other_id:
                cur.execute('UPDATE candidates SET votes = votes - 1 WHERE id=%s', (other_id,))
            
            # Reset the student's voting status so they can vote again in the updated pool
            cur.execute('UPDATE students SET hasVoted=0 WHERE usn=%s', (row_get(vote, 'usn'),))

        # 2. Delete the specific vote records
        cur.execute('DELETE FROM votes WHERE male_candidate_id=%s OR female_candidate_id=%s', (candidate_id, candidate_id))
        
        # 3. Finally, delete the candidate
        cur.execute('DELETE FROM candidates WHERE id=%s', (candidate_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})

@app.route('/api/admin/results')
def admin_results():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM candidates ORDER BY class, semester, gender, votes DESC')
    candidates = cur.fetchall()
    cur.execute('SELECT COUNT(*) as c FROM votes')
    total_votes = cur.fetchone()['c']
    conn.close()

    classes = {}
    for c in candidates:
        cls = f"{c['class']} (Sem {c.get('semester', '—')})"
        if cls not in classes:
            classes[cls] = {'males': [], 'females': []}
        if c['gender'] == 'Male':
            classes[cls]['males'].append(c)
        else:
            classes[cls]['females'].append(c)

    return jsonify({'success': True, 'classes': classes, 'total_votes': total_votes})

if __name__ == '__main__':
    init_db()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', debug=False, port=port)

@app.route('/api/results_public')
def results_public():
    conn = get_db()
    cur = conn.cursor()

    # CHECK IF PUBLISHED
    cur.execute("SELECT value FROM settings WHERE key='results_published'")
    setting = cur.fetchone()

    if not setting or setting['value'] != '1':
        conn.close()
        return jsonify({'success': False, 'message': 'not_published'})

    cur.execute('SELECT * FROM candidates ORDER BY class, semester, gender, votes DESC')
    candidates = cur.fetchall()
    conn.close()

    classes = {}

    for c in candidates:
        cls = f"{c['class']} (Sem {c.get('semester', '—')})"
        if cls not in classes:
            classes[cls] = {'males': [], 'females': []}

        if c['gender'] == 'Male':
            classes[cls]['males'].append(dict(c))
        else:
            classes[cls]['females'].append(dict(c))

    return jsonify({'success': True, 'classes': classes})
