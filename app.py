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
from functools import wraps

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv('SECRET_KEY', 'evm_secret_key_2024')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() in ('1', 'true', 'yes')

ADMIN_USN = os.getenv('ADMIN_USN', 'ADMIN').upper()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

DATABASE_URL = os.getenv('DATABASE_URL')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'database.db')

USE_SQLITE = not DATABASE_URL

if not DATABASE_URL:
    print("WARNING: DATABASE_URL not found. Using local SQLite database.")

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
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def row_get(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, row.get(key.lower(), default))
    try:
        return row[key]
    except:
        return default

def format_row(row):
    """Helper to ensure consistent lowercase keys for JS compatibility across DBs"""
    if not row:
        return {}
    return {k.lower(): v for k, v in dict(row).items()}


def init_db():
    conn = get_db()
    c = conn.cursor()

    id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if USE_SQLITE else "SERIAL PRIMARY KEY"

    c.execute('''CREATE TABLE IF NOT EXISTS students (
        usn TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        phone TEXT,
        class TEXT,
        semester TEXT,
        gender TEXT,
        password TEXT,
        isVerified INTEGER DEFAULT 1,
        hasVoted INTEGER DEFAULT 0
    )''')

    c.execute(f'''CREATE TABLE IF NOT EXISTS candidates (
    id {id_type},
    usn TEXT UNIQUE,
    name TEXT,
    class TEXT,
    semester TEXT,
    gender TEXT,
    votes INTEGER DEFAULT 0
    )''')

    

    

    c.execute(f'''CREATE TABLE IF NOT EXISTS votes (
        id {id_type},
        usn TEXT,
        class TEXT,
        male_candidate_id INTEGER,
        female_candidate_id INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS otps (
        usn TEXT PRIMARY KEY,
        otp TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    if USE_SQLITE:
        c.execute("INSERT OR IGNORE INTO settings VALUES ('voting_enabled','0')")
        c.execute("INSERT OR IGNORE INTO settings VALUES ('results_published','0')")
    else:
        c.execute("INSERT INTO settings VALUES ('voting_enabled','0') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO settings VALUES ('results_published','0') ON CONFLICT DO NOTHING")

    c.execute(f'''CREATE TABLE IF NOT EXISTS feedback (
        id {id_type},
        student_usn TEXT,
        cr_name TEXT,
        feedback_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Migration: Ensure columns exist if the table was created with an older schema
    for col_name, col_type in [('email', 'TEXT'), ('phone', 'TEXT'), ('semester', 'TEXT'), ('gender', 'TEXT')]:
        try:
            if USE_SQLITE:
                c.execute(f"ALTER TABLE students ADD COLUMN {col_name} {col_type}")
            else:
                c.execute(f"ALTER TABLE students ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
        except Exception:
            pass # Column already exists

    conn.commit()
    conn.close()


init_db()


def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_usn'):
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    # Always redirect to login on fresh entry to the root URL
    return redirect(url_for('login'))


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'student_usn' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/candidate_register')
def candidate_register():
    if 'student_usn' not in session:
        return redirect(url_for('login'))
    return render_template('candidate_register.html')

@app.route('/cr-feedback')
def cr_feedback():
    if 'student_usn' not in session:
        return redirect(url_for('login'))
    return render_template('cr_feedback.html')

@app.route('/api/submit_feedback', methods=['POST'])
def submit_feedback():
    if 'student_usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    try:
        data = request.get_json()
        cr_name = data.get('cr_name')
        feedback_text = data.get('feedback')

        if not cr_name or not feedback_text:
            return jsonify({'success': False, 'message': 'Please fill in all fields'})

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO feedback (student_usn, cr_name, feedback_text)
            VALUES (%s, %s, %s)
        """, (session['student_usn'], cr_name, feedback_text))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Feedback submitted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/register_candidate', methods=['POST'])
def register_candidate():
    try:
        if 'student_usn' not in session:
            return jsonify({'success': False, 'message': 'Not logged in'})

        data = request.get_json()
        gender = data.get('gender')

        conn = get_db()
        cur = conn.cursor()

        # Get student info
        cur.execute("SELECT * FROM students WHERE usn=%s", (session['student_usn'],))
        student = cur.fetchone()

        if not student:
            return jsonify({'success': False, 'message': 'Student not found'})

        # Check if voting has already started - cannot register as candidate during voting
        cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
        if row_get(cur.fetchone(), 'value') == '1':
            conn.close()
            return jsonify({'success': False, 'message': 'Registration is closed. Voting session has already started.'})

        # Check if already voted - cannot register as candidate after voting
        cur.execute("SELECT * FROM votes WHERE usn=%s", (session['student_usn'],))
        if cur.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Cannot register as candidate after voting'})

        # Check if already candidate
        cur.execute("SELECT * FROM candidates WHERE usn=%s", (session['student_usn'],))
        existing = cur.fetchone()

        if existing:
            return jsonify({'success': False, 'message': 'Already registered as candidate'})

        # Insert candidate
        cur.execute("""
            INSERT INTO candidates (usn, name, class, semester, gender)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            session['student_usn'],
            row_get(student, 'name'),
            row_get(student, 'class'),
            row_get(student, 'semester'),
            gender
        ))

        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Registered successfully'})

    except Exception as e:
        print("ERROR:", str(e))
        return jsonify({'success': False, 'message': str(e)})
    
@app.route('/api/candidates')
def get_candidates():
    try:
        if 'student_usn' not in session:
            return jsonify({'success': False, 'message': 'Not logged in'})

        conn = get_db()
        cur = conn.cursor()

        # Fetch the logged-in student's class and semester to filter candidates
        cur.execute("SELECT class, semester FROM students WHERE usn=%s", (session['student_usn'],))
        student = cur.fetchone()

        if student:
            # Display only candidates matching the student's specific class and semester
            cur.execute("SELECT * FROM candidates WHERE class=%s AND semester=%s ORDER BY votes DESC", 
                        (row_get(student, 'class'), row_get(student, 'semester')))
        else:
            # Fallback for admin users who might not have a student record
            cur.execute("SELECT * FROM candidates ORDER BY votes DESC")
            
        data = cur.fetchall()

        # Fetch voting status using the existing cursor before closing connection
        cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
        status_row = cur.fetchone()
        conn.close()

        return jsonify({
            'success': True,
            'data': [format_row(row) for row in data],
            # Grouping for vote.html/dashboard
            'males': [format_row(row) for row in data if row_get(row, 'gender') == 'Male'],
            'females': [format_row(row) for row in data if row_get(row, 'gender') == 'Female'],
            'voting_enabled': row_get(status_row, 'value') == '1'
        })

    except Exception as e:
        print("ERROR:", str(e))
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/candidates', methods=['GET', 'POST'])
@admin_required
def admin_candidates():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM candidates")
        data = cur.fetchall()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': [format_row(row) for row in data]
        })
    except Exception as e:
        print("Admin Candidates Error:", str(e))
        return jsonify({'success': False, 'message': str(e)})
    
@app.route('/api/admin/students', methods=['GET', 'POST'])
@admin_required
def admin_students():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM students")
        data = cur.fetchall()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': [format_row(row) for row in data]
        })
    except Exception as e:
        print("Admin Students Error:", str(e))
        return jsonify({'success': False, 'message': str(e)})
    
@app.route('/api/admin/voting_status', methods=['GET', 'POST'])
@admin_required
def voting_status():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings WHERE key IN ('voting_enabled', 'results_published')")
        rows = cur.fetchall()
        conn.close()
        
        status_map = {row_get(r, 'key'): row_get(r, 'value') == '1' for r in rows}
        
        return jsonify({
            'success': True,
            'enabled': status_map.get('voting_enabled', False),
            'results_published': status_map.get('results_published', False)
        })
    except Exception as e:
        print("Voting Status Error:", str(e))
        return jsonify({'success': False, 'message': str(e)})

@app.route('/vote')
def vote():
    if 'student_usn' not in session:
        return redirect(url_for('login'))

    return render_template('vote.html')

@app.route('/api/student_info')
def student_info():
    if 'student_usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE usn=%s", (session['student_usn'],))
    student = cur.fetchone()

    if not student:
        return jsonify({'success': False, 'message': 'Student not found'})

    cur.execute("SELECT * FROM votes WHERE usn=%s", (session['student_usn'],))
    vote = cur.fetchone()

    cur.execute("SELECT * FROM candidates WHERE usn=%s", (session['student_usn'],))
    candidate = cur.fetchone()

    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    voting_enabled = row_get(cur.fetchone(), 'value') == '1'

    cur.execute("SELECT value FROM settings WHERE key='results_published'")
    results_published = row_get(cur.fetchone(), 'value') == '1'
    conn.close()

    return jsonify({
        'success': True,
        'usn': row_get(student, 'usn'),
        'name': row_get(student, 'name'),
        'class': row_get(student, 'class'),
        'semester': row_get(student, 'semester'),
        'gender': row_get(student, 'gender'),
        'hasvoted': True if vote else False,
        'iscandidate': True if candidate else False,
        'voting_enabled': voting_enabled,
        'results_published': results_published
    })



@app.route('/admin')
def admin():
    if not session.get('admin_usn'):
        return redirect('/login')  # or '/admin_login_page'

    return render_template('admin.html')

@app.route('/results')
def results():
    if 'student_usn' not in session:
        return redirect(url_for('login'))

    return render_template('results_public.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    identifier = data.get('usn', '').strip()
    password = data.get('password', '')

    # Admin login check
    if identifier.upper() == ADMIN_USN and password == ADMIN_PASSWORD:
        session['admin_usn'] = identifier.upper()
        session.permanent = True
        return jsonify({'success': True, 'role': 'admin'})

    # Student login check
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE usn=%s OR email=%s", (identifier.upper(), identifier.lower()))
    user = cur.fetchone()
    conn.close()

    if not user:
        return jsonify({'success': False, 'message': 'User not found'})

    if row_get(user, 'password') != hash_password(password):
        return jsonify({'success': False, 'message': 'Wrong password'})

    session['student_usn'] = row_get(user, 'usn')
    session.permanent = True
    return jsonify({'success': True, 'role': 'student'})
# ---------------- RESULTS ----------------


@app.route('/api/admin/toggle_results', methods=['POST'])
@admin_required
def toggle_results():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='results_published'")
        row = cur.fetchone()
        current = row_get(row, 'value') == '1'
        new_val = '0' if current else '1'
        cur.execute("UPDATE settings SET value=%s WHERE key='results_published'", (new_val,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'published': new_val == '1'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/feedback')
@admin_required
def admin_feedback():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT f.*, 
                   (SELECT class FROM candidates WHERE name = f.cr_name LIMIT 1) as cr_class,
                   (SELECT semester FROM candidates WHERE name = f.cr_name LIMIT 1) as cr_semester
            FROM feedback f
            ORDER BY f.created_at DESC
        """)
        rows = cur.fetchall()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': [format_row(row) for row in rows]
        })
    except Exception as e:
        print("Admin Feedback Error:", str(e))
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/results')
@admin_required
def admin_results():
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM candidates ORDER BY semester, class, gender, votes DESC")
        rows = cur.fetchall()
        
        # Calculate total votes
        cur.execute("SELECT COUNT(*) as total FROM votes")
        total = cur.fetchone()
        conn.close()

        # Structure the data as the frontend expects
        classes = {}
        for r in rows:
            row = format_row(r)
            cls_key = f"Sem {row['semester']} - {row['class']}"
            if cls_key not in classes:
                classes[cls_key] = {'males': [], 'females': []}
            
            if row['gender'] == 'Male':
                classes[cls_key]['males'].append(row)
            else:
                classes[cls_key]['females'].append(row)

        return jsonify({
            'success': True,
            'classes': classes,
            'total_votes': row_get(total, 'total', 0)
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/send_otp', methods=['POST'])
def send_otp():
    data = request.get_json()
    usn = data.get('usn', '').upper()
    
    # Alphanumeric Captcha Generator
    q = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute("INSERT OR REPLACE INTO otps (usn, otp) VALUES (?, ?)", (usn, q))
    else:
        cur.execute("INSERT INTO otps (usn, otp) VALUES (%s, %s) ON CONFLICT (usn) DO UPDATE SET otp=EXCLUDED.otp", (usn, q))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'captcha_question': f"Enter this code: {q}"})

@app.route('/api/register', methods=['POST'])
def api_register():
    try:
        data = request.get_json()
        usn = data.get('usn', '').strip().upper()
        otp_entered = data.get('otp', '').strip()

        conn = get_db()
        cur = conn.cursor()
        
        # Verify Captcha
        cur.execute("SELECT otp FROM otps WHERE usn=%s", (usn,))
        record = cur.fetchone()
        if not record or row_get(record, 'otp') != otp_entered:
            return jsonify({'success': False, 'message': 'Invalid Captcha'})

        # Create student
        cur.execute("""
            INSERT INTO students (usn, name, email, class, semester, gender, password)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (usn, data.get('name'), data.get('email'), data.get('class'), data.get('semester'), data.get('gender'), hash_password(data.get('password'))))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': "USN already registered or error: " + str(e)})

@app.route('/api/submit_vote', methods=['POST'])
def submit_vote():
    if 'student_usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})

    conn = get_db()
    cur = conn.cursor()

    # Check if voting enabled
    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    if row_get(cur.fetchone(), 'value') != '1':
        return jsonify({'success': False, 'message': 'Voting is closed'})

    # Check if already voted
    cur.execute("SELECT * FROM votes WHERE usn=%s", (session['student_usn'],))
    if cur.fetchone():
        return jsonify({'success': False, 'message': 'Already voted'})

    data = request.get_json()
    m_id = data.get('male_id')
    f_id = data.get('female_id')

    # Record vote
    cur.execute("SELECT class FROM students WHERE usn=%s", (session['student_usn'],))
    cls = row_get(cur.fetchone(), 'class')
    
    cur.execute("""
        INSERT INTO votes (usn, class, male_candidate_id, female_candidate_id)
        VALUES (%s, %s, %s, %s)
    """, (session['student_usn'], cls, m_id, f_id))

    # Increment candidate counts
    cur.execute("UPDATE candidates SET votes = votes + 1 WHERE id=%s", (m_id,))
    cur.execute("UPDATE candidates SET votes = votes + 1 WHERE id=%s", (f_id,))
    
    # Mark student as voted
    cur.execute("UPDATE students SET hasVoted=1 WHERE usn=%s", (session['student_usn'],))

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/toggle_voting', methods=['POST'])
@admin_required
def toggle_voting():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
        row = cur.fetchone()
        current = row_get(row, 'value') == '1'
        new_val = '0' if current else '1'
        cur.execute("UPDATE settings SET value=%s WHERE key='voting_enabled'", (new_val,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'enabled': new_val == '1'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/delete_student/<usn>', methods=['POST'])
@admin_required
def delete_student(usn):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM students WHERE usn=%s", (usn,))
        cur.execute("DELETE FROM candidates WHERE usn=%s", (usn,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Student deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/delete_candidate/<int:id>', methods=['POST'])
@admin_required
def delete_candidate(id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM candidates WHERE id=%s", (id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Candidate removed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/reset_password', methods=['POST'])
@admin_required
def reset_password():
    try:
        data = request.get_json()
        usn = data.get('usn')
        new_pwd = data.get('password')
        if not usn or not new_pwd:
            return jsonify({'success': False, 'message': 'Missing data'})
            
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE students SET password=%s WHERE usn=%s", (hash_password(new_pwd), usn))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Password reset successful'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/logout')
def logout():
    role = request.args.get('role')
    if role == 'admin':
        session.pop('admin_usn', None)
    elif role == 'student':
        session.pop('student_usn', None)
    else:
        # Fallback for general logout
        session.clear()
    return redirect(url_for('login'))


@app.route('/api/results_public')
def results_public():
    if 'student_usn' not in session and 'admin_usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT value FROM settings WHERE key='results_published'")
    s = cur.fetchone()
    if not s or row_get(s, 'value') != '1':
        conn.close()
        return jsonify({'success': False})

    # Filter by student's class and semester
    cur.execute("SELECT class, semester FROM students WHERE usn=%s", (session.get('student_usn'),))
    student = cur.fetchone()

    if student:
        cur.execute("SELECT * FROM candidates WHERE class=%s AND semester=%s ORDER BY gender, votes DESC", 
                    (row_get(student, 'class'), row_get(student, 'semester')))
    else:
        # Admin or special users without a student record can see all results
        cur.execute("SELECT * FROM candidates ORDER BY semester, class, gender, votes DESC")

    rows = cur.fetchall()
    conn.close()

    classes = {}
    for r in rows:
        row = format_row(r)
        cls_key = f"Sem {row['semester']} - {row['class']}"
        if cls_key not in classes: classes[cls_key] = {'males': [], 'females': []}
        classes[cls_key]['males' if row['gender'] == 'Male' else 'females'].append(row)

    return jsonify({'success': True, 'classes': classes})


if __name__ == '__main__':
    app.run(debug=True)