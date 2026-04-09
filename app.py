from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import hashlib
import random
import os
import smtplib
import tempfile
from email.message import EmailMessage
import string

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv('SECRET_KEY', 'evm_secret_key_2024')
ADMIN_USN = os.getenv('ADMIN_USN', 'ADMIN').upper()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

# Email settings (set as environment variables)
SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
EMAIL_FROM = os.getenv('EMAIL_FROM')

def resolve_db_path():
    configured_path = os.getenv('DATABASE_PATH')
    if configured_path:
        return configured_path

    render_disk_root = os.getenv('RENDER_DISK_ROOT')
    if render_disk_root:
        return os.path.join(render_disk_root, 'database.db')

    # Render and similar hosts may not allow reliable writes in the code directory.
    # Use the OS temp directory in production-like environments unless configured.
    if os.getenv('RENDER') or os.getenv('PORT'):
        return os.path.join(tempfile.gettempdir(), 'database.db')

    return os.path.join(BASE_DIR, 'database.db')


DB_PATH = resolve_db_path()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        usn TEXT PRIMARY KEY,
        name TEXT,
        phone TEXT,
        class TEXT,
        password TEXT,
        isVerified INTEGER DEFAULT 0,
        hasVoted INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usn TEXT UNIQUE,
        name TEXT,
        class TEXT,
        gender TEXT,
        votes INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usn TEXT,
        class TEXT,
        male_candidate_id INTEGER,
        female_candidate_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('voting_enabled', '0')")
    student_columns = [row[1] for row in c.execute("PRAGMA table_info(students)").fetchall()]
    if 'name' not in student_columns:
        c.execute("ALTER TABLE students ADD COLUMN name TEXT")
    conn.commit()
    conn.close()


init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# OTP storage (in-memory for demo)
otp_store = {}

# ─── ROUTES ───────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET'])
def register():
    return render_template('register.html')

@app.route('/login', methods=['GET'])
def login():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'usn' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/vote')
def vote():
    if 'usn' not in session:
        return redirect(url_for('login'))
    return render_template('vote.html')

@app.route('/candidate_register')
def candidate_register():
    if 'usn' not in session:
        return redirect(url_for('login'))
    return render_template('candidate_register.html')

@app.route('/admin')
def admin():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('admin.html')

@app.route('/admin_login')
def admin_login():
    return render_template('admin_login.html')

@app.route('/results')
def results():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('results.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

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
    
    otp_store[usn] = captcha_answer
    
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
    cls = data.get('class')
    otp = data.get('otp')
    password = data.get('password')

    if not name:
        return jsonify({'success': False, 'message': 'Name is required'})

    if otp_store.get(usn) != otp:
        return jsonify({'success': False, 'message': 'Invalid OTP'})

    conn = get_db()
    existing = conn.execute('SELECT usn FROM students WHERE usn=?', (usn,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'USN already registered'})

    conn.execute(
        'INSERT INTO students (usn, name, phone, class, password, isVerified, hasVoted) VALUES (?,?,?,?,?,1,0)',
        (usn, name, email, cls, hash_password(password))
    )
    conn.commit()
    conn.close()
    otp_store.pop(usn, None)
    return jsonify({'success': True, 'message': 'Registration successful!'})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    identifier = data.get('usn', '').upper()  # Can be USN or email
    password = data.get('password')

    if identifier == ADMIN_USN and password == ADMIN_PASSWORD:
        session['role'] = 'admin'
        session['usn'] = ADMIN_USN
        return jsonify({'success': True, 'role': 'admin'})

    conn = get_db()
    # Check if identifier is email or USN, and distinguish an unknown account
    # from a wrong password so the UI can guide first-time users.
    if '@' in identifier:
        student = conn.execute(
            'SELECT * FROM students WHERE phone=?',
            (identifier.lower(),)
        ).fetchone()
    else:
        student = conn.execute(
            'SELECT * FROM students WHERE usn=?',
            (identifier,)
        ).fetchone()
    conn.close()

    if not student:
        return jsonify({
            'success': False,
            'message': 'USN not registered please register your USN and then login'
        })

    if student['password'] != hash_password(password):
        return jsonify({'success': False, 'message': 'Invalid password'})

    session['usn'] = student['usn']
    session['class'] = student['class']
    session['role'] = 'student'
    return jsonify({'success': True, 'role': 'student'})

@app.route('/api/student_info')
def student_info():
    if 'usn' not in session:
        return jsonify({'success': False})
    conn = get_db()
    student = conn.execute(
        'SELECT usn, name, class, hasVoted FROM students WHERE usn=?',
        (session['usn'],)
    ).fetchone()
    is_candidate = conn.execute('SELECT id FROM candidates WHERE usn=?', (session['usn'],)).fetchone()
    conn.close()
    return jsonify({
        'success': True,
        'usn': student['usn'],
        'name': student['name'],
        'class': student['class'],
        'hasVoted': bool(student['hasVoted']),
        'isCandidate': bool(is_candidate)
    })

@app.route('/api/register_candidate', methods=['POST'])
def register_candidate():
    if 'usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    data = request.json
    usn = session['usn']
    gender = data.get('gender')

    conn = get_db()
    student = conn.execute('SELECT name, class FROM students WHERE usn=?', (usn,)).fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found'})

    name = (student['name'] or '').strip()
    cls = student['class']
    existing = conn.execute('SELECT id FROM candidates WHERE usn=?', (usn,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'Already registered as candidate'})

    if not name:
        conn.close()
        return jsonify({'success': False, 'message': 'Student name not found. Please update your registration first.'})

    count = conn.execute('SELECT COUNT(*) as c FROM candidates WHERE class=? AND gender=?', (cls, gender)).fetchone()
    if count['c'] >= 2:
        conn.close()
        return jsonify({'success': False, 'message': f'Maximum {gender} candidates reached for your class'})

    conn.execute('INSERT INTO candidates (usn, name, class, gender, votes) VALUES (?,?,?,?,0)',
                 (usn, name, cls, gender))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Registered as candidate successfully!'})

@app.route('/api/candidates')
def get_candidates():
    if 'usn' not in session:
        return jsonify({'success': False})
    cls = session.get('class')
    conn = get_db()
    males = [dict(r) for r in conn.execute('SELECT * FROM candidates WHERE class=? AND gender="Male"', (cls,)).fetchall()]
    females = [dict(r) for r in conn.execute('SELECT * FROM candidates WHERE class=? AND gender="Female"', (cls,)).fetchall()]
    setting = conn.execute("SELECT value FROM settings WHERE key='voting_enabled'").fetchone()
    conn.close()
    return jsonify({
        'success': True,
        'males': males,
        'females': females,
        'voting_enabled': setting['value'] == '1'
    })

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
    student = conn.execute('SELECT hasVoted FROM students WHERE usn=?', (usn,)).fetchone()
    if student['hasVoted']:
        conn.close()
        return jsonify({'success': False, 'message': 'You have already voted'})

    setting = conn.execute("SELECT value FROM settings WHERE key='voting_enabled'").fetchone()
    if setting['value'] != '1':
        conn.close()
        return jsonify({'success': False, 'message': 'Voting is not enabled'})

    conn.execute('INSERT INTO votes (usn, class, male_candidate_id, female_candidate_id) VALUES (?,?,?,?)',
                 (usn, cls, male_id, female_id))
    conn.execute('UPDATE candidates SET votes = votes + 1 WHERE id=?', (male_id,))
    conn.execute('UPDATE candidates SET votes = votes + 1 WHERE id=?', (female_id,))
    conn.execute('UPDATE students SET hasVoted=1 WHERE usn=?', (usn,))
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
    students = [
        dict(r) for r in conn.execute(
            'SELECT usn, name, phone AS email, class, isVerified, hasVoted FROM students ORDER BY class, usn'
        ).fetchall()
    ]
    conn.close()
    return jsonify({'success': True, 'students': students})

@app.route('/api/admin/candidates')
def admin_candidates():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    candidates = [dict(r) for r in conn.execute('SELECT * FROM candidates ORDER BY class, gender').fetchall()]
    conn.close()
    return jsonify({'success': True, 'candidates': candidates})

@app.route('/api/admin/toggle_voting', methods=['POST'])
def toggle_voting():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    current = conn.execute("SELECT value FROM settings WHERE key='voting_enabled'").fetchone()
    new_val = '0' if current['value'] == '1' else '1'
    conn.execute("UPDATE settings SET value=? WHERE key='voting_enabled'", (new_val,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'voting_enabled': new_val == '1'})

@app.route('/api/admin/voting_status')
def voting_status():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    setting = conn.execute("SELECT value FROM settings WHERE key='voting_enabled'").fetchone()
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
    
    conn = get_db()
    # Check if student has voted
    student = conn.execute('SELECT hasVoted FROM students WHERE usn=?', (usn,)).fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found'})
    
    if student['hasVoted']:
        # If voted, also delete their vote
        conn.execute('DELETE FROM votes WHERE usn=?', (usn,))
    
    # Delete candidate if they are one
    conn.execute('DELETE FROM candidates WHERE usn=?', (usn,))
    
    # Delete student
    conn.execute('DELETE FROM students WHERE usn=?', (usn,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

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
    student = conn.execute('SELECT usn FROM students WHERE usn=?', (usn,)).fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found'})

    conn.execute(
        'UPDATE students SET password=? WHERE usn=?',
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
    
    conn = get_db()
    # Get candidate info
    candidate = conn.execute('SELECT usn FROM candidates WHERE id=?', (candidate_id,)).fetchone()
    if not candidate:
        conn.close()
        return jsonify({'success': False, 'message': 'Candidate not found'})
    
    # Delete votes for this candidate
    conn.execute('DELETE FROM votes WHERE male_candidate_id=? OR female_candidate_id=?', (candidate_id, candidate_id))
    
    # Delete candidate
    conn.execute('DELETE FROM candidates WHERE id=?', (candidate_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/results')
def admin_results():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    candidates = [dict(r) for r in conn.execute('SELECT * FROM candidates ORDER BY class, gender, votes DESC').fetchall()]
    total_votes = conn.execute('SELECT COUNT(*) as c FROM votes').fetchone()['c']
    conn.close()

    classes = {}
    for c in candidates:
        cls = c['class']
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
