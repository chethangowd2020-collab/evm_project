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

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv('SECRET_KEY', 'evm_secret_key_2024')

# Session security and persistence configuration
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
ADMIN_USN = os.getenv('ADMIN_USN', 'ADMIN').upper()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

# Supabase Connection String (e.g., postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres)
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("WARNING: DATABASE_URL not found. Database features will fail.")

# Email settings (set as environment variables)
SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
EMAIL_FROM = os.getenv('EMAIL_FROM')

def get_db():
    if not DATABASE_URL:
        raise ConnectionError("DATABASE_URL environment variable is not set.")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
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
    try:
        # Ensure semester column exists if table was created previously
        c.execute('ALTER TABLE students ADD COLUMN IF NOT EXISTS semester TEXT')
    except Exception as e:
        print(f"Notice: Semester column check: {e}")
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id SERIAL PRIMARY KEY,
        usn TEXT UNIQUE,
        name TEXT,
        class TEXT,
        gender TEXT,
        votes INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
        id SERIAL PRIMARY KEY,
        usn TEXT,
        class TEXT,
        male_candidate_id INTEGER,
        female_candidate_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute("INSERT INTO settings (key, value) VALUES ('voting_enabled', '0') ON CONFLICT (key) DO NOTHING")
    conn.commit()
    conn.close()


try:
    init_db()
except Exception as e:
    print(f"Database initialization failed: {e}")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# OTP storage (in-memory for demo)
otp_store = {}

# ─── ROUTES ───────────────────────────────────────────────────

@app.route('/')
def index():
    if 'usn' in session:
        return redirect(url_for('admin' if session.get('role') == 'admin' else 'dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET'])
def register():
    if 'usn' in session:
        return redirect(url_for('admin' if session.get('role') == 'admin' else 'dashboard'))
    return render_template('register.html')

@app.route('/login', methods=['GET'])
def login():
    if 'usn' in session:
        return redirect(url_for('admin' if session.get('role') == 'admin' else 'dashboard'))
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'usn' not in session:
        return redirect(url_for('login'))
    session.permanent = True # Refresh session expiration on every activity
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
    return render_template('vote.html')

@app.route('/candidate_register')
def candidate_register():
    if 'usn' not in session:
        return redirect(url_for('login'))
    return render_template(
        'candidate_register.html',
        name=session.get('name', 'Student'),
        cls=session.get('class', '—'),
        sem=session.get('semester', '—'))

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
    sem = data.get('semester')
    otp = data.get('otp')
    password = data.get('password')

    if not name:
        return jsonify({'success': False, 'message': 'Name is required'})

    if otp_store.get(usn) != otp:
        return jsonify({'success': False, 'message': 'Invalid OTP'})

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT usn FROM students WHERE usn=%s', (usn,))
    if cur.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'USN already registered'})

    cur.execute(
        'INSERT INTO students (usn, name, phone, class, semester, password, isVerified, hasVoted) VALUES (%s,%s,%s,%s,%s,%s,1,0)',
        (usn, name, email, cls, sem, hash_password(password))
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
    session.permanent = True
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
        return jsonify({'success': False})
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT usn, name, class, semester, hasVoted FROM students WHERE usn=%s', (session['usn'],))
        student = cur.fetchone()
        if not student:
            conn.close()
            return jsonify({'success': False, 'message': 'Student record not found. Please log in again.'})

        cur.execute('SELECT id FROM candidates WHERE usn=%s', (session['usn'],))
        is_candidate = cur.fetchone()
        conn.close()
        return jsonify({
            'success': True,
            'usn': student['usn'],
            'name': student['name'],
            'class': student['class'],
            'semester': student['semester'],
            'hasVoted': bool(student['hasVoted']),
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
    cur.execute('SELECT name, class FROM students WHERE usn=%s', (usn,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found'})

    name = (student['name'] or '').strip()
    cls = student['class']
    cur.execute('SELECT id FROM candidates WHERE usn=%s', (usn,))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'Already registered as candidate'})

    if not name:
        conn.close()
        return jsonify({'success': False, 'message': 'Student name not found. Please update your registration first.'})

    cur.execute('SELECT COUNT(*) as c FROM candidates WHERE class=%s AND gender=%s', (cls, gender))
    count = cur.fetchone()
    if count['c'] >= 2:
        conn.close()
        return jsonify({'success': False, 'message': f'Maximum {gender} candidates reached for your class'})

    cur.execute('INSERT INTO candidates (usn, name, class, gender, votes) VALUES (%s,%s,%s,%s,0)',
                 (usn, name, cls, gender))
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
        cur.execute('SELECT class FROM students WHERE usn=%s', (session['usn'],))
        student = cur.fetchone()
        if not student:
            conn.close()
            return jsonify({'success': False, 'message': 'Student record not found'})
        
        cls = student['class']
        cur.execute('SELECT * FROM candidates WHERE class=%s AND gender=%s', (cls, 'Male'))
        males = cur.fetchall()
        cur.execute('SELECT * FROM candidates WHERE class=%s AND gender=%s', (cls, 'Female'))
        females = cur.fetchall()
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
    if student['hasVoted']:
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
    students = cur.fetchall()
    conn.close()
    return jsonify({'success': True, 'students': students})

@app.route('/api/admin/candidates')
def admin_candidates():
    if session.get('role') != 'admin':
        return jsonify({'success': False})
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM candidates ORDER BY class, gender')
    candidates = cur.fetchall()
    conn.close()
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
        if student_status and student_status['hasVoted']:
            cur.execute('SELECT male_candidate_id, female_candidate_id FROM votes WHERE usn=%s', (usn,))
            vote_rec = cur.fetchone()
            if vote_rec:
                if vote_rec['male_candidate_id']:
                    cur.execute('UPDATE candidates SET votes = votes - 1 WHERE id=%s', (vote_rec['male_candidate_id'],))
                if vote_rec['female_candidate_id']:
                    cur.execute('UPDATE candidates SET votes = votes - 1 WHERE id=%s', (vote_rec['female_candidate_id'],))

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
            # Decrement the count for the OTHER candidate in that same vote record
            other_id = vote['female_candidate_id'] if vote['male_candidate_id'] == int(candidate_id) else vote['male_candidate_id']
            if other_id:
                cur.execute('UPDATE candidates SET votes = votes - 1 WHERE id=%s', (other_id,))
            
            # Reset the student's voting status so they can vote again in the updated pool
            cur.execute('UPDATE students SET hasVoted=0 WHERE usn=%s', (vote['usn'],))

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
    cur.execute('SELECT * FROM candidates ORDER BY class, gender, votes DESC')
    candidates = cur.fetchall()
    cur.execute('SELECT COUNT(*) as c FROM votes')
    total_votes = cur.fetchone()['c']
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
