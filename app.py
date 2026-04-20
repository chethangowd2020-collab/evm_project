from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response
import psycopg2
from datetime import datetime, timedelta
from psycopg2.extras import RealDictCursor
import hashlib
import random
import os
import smtplib # type: ignore
import tempfile
from email.message import EmailMessage
import string
import re
import sqlite3
import csv
import io
from functools import wraps

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY and not app.debug:
    raise ValueError("No SECRET_KEY set for production environment")
app.secret_key = SECRET_KEY or 'dev_key_only'
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
try:
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
except ValueError:
    print("WARNING: SMTP_PORT environment variable is not a valid integer. Defaulting to 587.")
    SMTP_PORT = 587
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
    return {k.lower(): (v if v is not None and v != "" else "--") for k, v in dict(row).items()}


def send_email(to_email, subject, content):
    """Helper to send emails using SMTP settings"""
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM]):
        print("SMTP settings are not fully configured in environment variables.")
        return False
    try:
        msg = EmailMessage()
        msg.set_content(content)
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = to_email

        if SMTP_PORT == 465:
            print(f"DEBUG: Attempting SSL connection on port {SMTP_PORT}")
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            print(f"DEBUG: Attempting STARTTLS connection on port {SMTP_PORT}")
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
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

    # Migration: Ensure expires_at exists in the otps table
    try:
        if USE_SQLITE:
            c.execute("ALTER TABLE otps ADD COLUMN expires_at TIMESTAMP")
        else:
            c.execute("ALTER TABLE otps ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP")
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
        # DEBUG: Print the admin_usn value from the session
        print(f"DEBUG: admin_required check - admin_usn in session: {session.get('admin_usn')}")
        if not session.get('admin_usn'):
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def get_auth_student_usn():
    """Helper to retrieve the namespaced USN from headers and session."""
    # PERMANENT FIX: If an admin is active, this cannot be a student session
    if session.get('admin_usn'):
        return None
    header_usn = request.headers.get('X-Student-USN')
    if header_usn and session.get(f"auth_{header_usn.upper()}"):
        return header_usn.upper()
    # Fallback to the most recent login for standard page loads
    return session.get('student_usn')


@app.route('/')
def index():
    # Always redirect to login on fresh entry to the root URL
    return redirect(url_for('login'))

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('univote_logo.jpg')


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if not get_auth_student_usn() and 'admin_usn' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/candidate_register')
def candidate_register():
    if not get_auth_student_usn() and 'admin_usn' not in session:
        return redirect(url_for('login'))
    return render_template('candidate_register.html')

@app.route('/cr-feedback')
def cr_feedback():
    if not get_auth_student_usn() and 'admin_usn' not in session:
        return redirect(url_for('login'))
    return render_template('cr_feedback.html')

@app.route('/api/submit_feedback', methods=['POST'])
def submit_feedback():
    usn = get_auth_student_usn()
    if not usn:
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
        """, (usn, cr_name, feedback_text))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Feedback submitted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/register_candidate', methods=['POST'])
def register_candidate():
    try:
        usn = get_auth_student_usn()
        if not usn:
            return jsonify({'success': False, 'message': 'Not logged in'})

        data = request.get_json()

        conn = get_db()
        cur = conn.cursor()

        # Get student info
        cur.execute("SELECT * FROM students WHERE usn=%s", (usn,))
        student = cur.fetchone()

        if not student:
            return jsonify({'success': False, 'message': 'Student not found'})

        # Check if voting has already started - cannot register as candidate during voting
        cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
        if row_get(cur.fetchone(), 'value') == '1':
            conn.close()
            return jsonify({'success': False, 'message': 'Registration is closed. Voting session has already started.'})

        # Check if already voted - cannot register as candidate after voting
        cur.execute("SELECT * FROM votes WHERE usn=%s", (usn,))
        if cur.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Cannot register as candidate after voting'})

        # Check if already candidate
        cur.execute("SELECT * FROM candidates WHERE usn=%s", (usn,))
        existing = cur.fetchone()

        if existing:
            return jsonify({'success': False, 'message': 'Already registered as candidate'})

        # Insert candidate
        cur.execute("""
            INSERT INTO candidates (usn, name, class, semester, gender)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            usn,
            row_get(student, 'name'),
            row_get(student, 'class'),
            row_get(student, 'semester'),
            row_get(student, 'gender')
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
        usn = get_auth_student_usn()
        if not usn:
            return jsonify({'success': False, 'message': 'Not logged in'})

        conn = get_db()
        cur = conn.cursor()

        # Fetch the logged-in student's class and semester to filter candidates
        cur.execute("SELECT class, semester FROM students WHERE usn=%s", (usn,))
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
        # Join with students table to retrieve the candidate's email
        cur.execute("""
            SELECT c.*, s.email 
            FROM candidates c 
            LEFT JOIN students s ON c.usn = s.usn
        """)
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
    if not get_auth_student_usn() and 'admin_usn' not in session:
        return redirect(url_for('login'))

    return render_template('vote.html')

@app.route('/api/student_info')
def student_info():
    usn = get_auth_student_usn()
    if not usn:
        return jsonify({'success': False, 'message': 'Not logged in'})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE usn=%s", (usn,))
    student = cur.fetchone()

    if not student:
        return jsonify({'success': False, 'message': 'Student not found'})

    cur.execute("SELECT * FROM votes WHERE usn=%s", (usn,))
    vote = cur.fetchone()

    cur.execute("SELECT * FROM candidates WHERE usn=%s", (usn,))
    candidate = cur.fetchone()

    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    voting_enabled = row_get(cur.fetchone(), 'value') == '1'

    cur.execute("SELECT value FROM settings WHERE key='results_published'")
    results_published = row_get(cur.fetchone(), 'value') == '1'
    conn.close()

    student_data = format_row(student)
    return jsonify({
        'success': True,
        **student_data,
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
    if not get_auth_student_usn() and 'admin_usn' not in session:
        return redirect(url_for('login'))

    return render_template('results_public.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    identifier = data.get('usn', '').strip()
    password = data.get('password', '')

    # Admin login check
    if identifier.upper() == ADMIN_USN and password == ADMIN_PASSWORD:
        session.clear() # Clear any existing student/admin data
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
        return jsonify({'success': False, 'message': 'User not registered.Please register first'})

    if row_get(user, 'password') != hash_password(password):
        return jsonify({'success': False, 'message': 'Wrong password'})

    usn = row_get(user, 'usn')
    session.clear() # Clear any existing admin/stale student data
    # Create namespaced authentication entry
    session[f"auth_{usn}"] = True
    session['student_usn'] = usn  # Keep as fallback
    session.permanent = True
    return jsonify({'success': True, 'role': 'student', 'usn': usn})
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
            ORDER BY cr_semester ASC, cr_class ASC, f.created_at DESC
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

@app.route('/api/admin/export_results')
@admin_required
def export_results():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT semester, class, gender, name, usn, votes FROM candidates ORDER BY semester, class, gender, votes DESC")
        rows = cur.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Semester', 'Class', 'Gender', 'Candidate Name', 'USN', 'Votes'])
        
        for row in rows:
            r = format_row(row)
            writer.writerow([r['semester'], r['class'], r['gender'], r['name'], r['usn'], r['votes']])

        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=election_results.csv"
        response.headers["Content-type"] = "text/csv"
        return response
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/results')
@admin_required
def admin_results():
    try:
        conn = get_db()
        cur = conn.cursor()

        classes = {}
        semesters = ['1', '2', '3', '4', '5', '6', '7', '8']
        class_names = [
            'CSE A', 'CSE B', 'CSE C', 'CSE D', 'ISE E', 'ISE F', 
            'AIML H', 'CSE(DS) I', 'ECE J', 'ECE K', 'ECE L', 
            'EEE N', 'CIVIL M', 'MECH O'
        ]
        
        for sem in semesters:
            for cls in class_names:
                cls_key = f"Sem {sem} - {cls}"
                classes[cls_key] = {'males': [], 'females': []}

        # Step 2: Fetch all candidates
        cur.execute("SELECT * FROM candidates ORDER BY semester, class, gender, votes DESC")
        rows = cur.fetchall()
        
        # Calculate total votes
        cur.execute("SELECT COUNT(*) as total FROM votes")
        total = cur.fetchone()
        conn.close()

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
@app.route('/api/admin/update_gender', methods=['POST'])
@admin_required
def update_gender():
    try:
        data = request.get_json()
        usn = data.get('usn')
        new_gender = data.get('gender')
        if not usn or new_gender not in ['Male', 'Female']:
            return jsonify({'success': False, 'message': 'Invalid data'})
            
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE students SET gender=%s WHERE usn=%s", (new_gender, usn))
        cur.execute("UPDATE candidates SET gender=%s WHERE usn=%s", (new_gender, usn))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Gender updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/send_otp', methods=['POST'])
def send_otp():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
            
        usn = data.get('usn', '').upper()
        email = data.get('email', '').strip()

        if not email or not usn:
            return jsonify({'success': False, 'message': 'Email and USN are required to send OTP'})

        # Numeric 6-digit OTP
        q = ''.join(random.choices(string.digits, k=6))
        
        expires_at_dt = datetime.now() + timedelta(minutes=5) # OTP valid for 5 minutes
        # Pass datetime object directly; database driver handles conversion
        conn = get_db()
        cur = conn.cursor()
        if USE_SQLITE:
            cur.execute("INSERT OR REPLACE INTO otps (usn, otp, expires_at) VALUES (?, ?, ?)", (usn, q, expires_at_dt))
        else:
            cur.execute("INSERT INTO otps (usn, otp, expires_at) VALUES (%s, %s, %s) ON CONFLICT (usn) DO UPDATE SET otp=EXCLUDED.otp, expires_at=EXCLUDED.expires_at", (usn, q, expires_at_dt))
        conn.commit()
        conn.close()

        if send_email(email, "Uni-Vote Verification Code", f"Your verification code for Uni-Vote registration is: {q}"):
            return jsonify({'success': True, 'message': 'OTP sent to your email successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to send email. Please check SMTP configuration.'})
    except Exception as e:
        print(f"ERROR in /api/send_otp: {e}")
        return jsonify({'success': False, 'message': 'An unexpected server error occurred while generating OTP.'}), 500

@app.route('/api/register', methods=['POST'])
def api_register():
    try:
        data = request.get_json()
        usn = data.get('usn', '').strip().upper()
        otp_entered = data.get('otp', '').strip()
        gender = data.get('gender')
        password = data.get('password', '')

        # Server-side validation
        if not re.match(r'^1JB\d{2}[A-Z]{2}\d{3}$', usn):
            return jsonify({'success': False, 'message': 'Invalid USN format'})
        if len(password) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters'})

        conn = get_db()
        cur = conn.cursor()
        
        if not gender:
            return jsonify({'success': False, 'message': 'Gender is required'})

        # Verify OTP and check for expiration
        cur.execute("SELECT otp, expires_at FROM otps WHERE usn=%s", (usn,))
        record = cur.fetchone()
        
        if not record or row_get(record, 'otp') != otp_entered: # OTP mismatch
            return jsonify({'success': False, 'message': 'Invalid OTP'})
        
        stored_expires_at_raw = row_get(record, 'expires_at')
        
        if stored_expires_at_raw is None:
            return jsonify({'success': False, 'message': 'OTP record is corrupted. Please resend.'})

        # Convert to datetime object if it's a string (SQLite)
        if isinstance(stored_expires_at_raw, str):
            stored_expires_at = datetime.fromisoformat(stored_expires_at_raw)
        elif isinstance(stored_expires_at_raw, datetime):
            stored_expires_at = stored_expires_at_raw
        else:
            return jsonify({'success': False, 'message': 'Internal error with OTP expiration.'})

        if datetime.now() > stored_expires_at: # OTP expired
            return jsonify({'success': False, 'message': 'OTP expired. Please request a new one.'})

        # Create student
        cur.execute("""
            INSERT INTO students (usn, name, email, class, semester, gender, password)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (usn, data.get('name'), data.get('email'), data.get('class'), data.get('semester'), gender, hash_password(data.get('password'))))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': "USN already registered or error: " + str(e)})

@app.route('/api/submit_vote', methods=['POST'])
def submit_vote():
    usn = get_auth_student_usn()
    if not usn:
        return jsonify({'success': False, 'message': 'Not logged in'})

    conn = get_db()
    cur = conn.cursor()

    # Check if voting enabled
    cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
    if row_get(cur.fetchone(), 'value') != '1':
        return jsonify({'success': False, 'message': 'Voting is closed'})

    # Check if already voted
    cur.execute("SELECT * FROM votes WHERE usn=%s", (usn,))
    if cur.fetchone():
        return jsonify({'success': False, 'message': 'Already voted'})

    data = request.get_json()
    m_id = data.get('male_id')
    f_id = data.get('female_id')

    # Record vote
    cur.execute("SELECT class FROM students WHERE usn=%s", (usn,))
    cls = row_get(cur.fetchone(), 'class')
    
    cur.execute("""
        INSERT INTO votes (usn, class, male_candidate_id, female_candidate_id)
        VALUES (%s, %s, %s, %s)
    """, (usn, cls, m_id, f_id))

    # Increment candidate counts
    cur.execute("UPDATE candidates SET votes = votes + 1 WHERE id=%s", (m_id,))
    cur.execute("UPDATE candidates SET votes = votes + 1 WHERE id=%s", (f_id,))
    
    # Mark student as voted
    cur.execute("UPDATE students SET hasVoted=1 WHERE usn=%s", (usn,))

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
        cur.execute("DELETE FROM votes WHERE usn=%s", (usn,))
        cur.execute("DELETE FROM feedback WHERE student_usn=%s", (usn,))
        cur.execute("DELETE FROM candidates WHERE usn=%s", (usn,))
        cur.execute("DELETE FROM students WHERE usn=%s", (usn,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Student and related records deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get total students
        cur.execute("SELECT COUNT(*) as total FROM students")
        total_students = row_get(cur.fetchone(), 'total', 0)
        
        # Get total candidates
        cur.execute("SELECT COUNT(*) as total FROM candidates")
        total_candidates = row_get(cur.fetchone(), 'total', 0)
        
        # Get total votes cast
        cur.execute("SELECT COUNT(*) as total FROM votes")
        total_votes = row_get(cur.fetchone(), 'total', 0)
        
        conn.close()
        
        turnout = 0
        if total_students > 0:
            turnout = round((total_votes / total_students) * 100)
            
        return jsonify({
            'success': True,
            'students': total_students,
            'candidates': total_candidates,
            'votes': total_votes,
            'turnout': turnout
        })
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

@app.route('/api/admin/delete_feedback/<int:id>', methods=['POST'])
@admin_required
def delete_feedback(id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM feedback WHERE id=%s", (id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Feedback deleted'})
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
    # session.clear() is the only way to guarantee a clean slate
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/results_public')
def results_public():
    usn = get_auth_student_usn()
    if not usn and 'admin_usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT value FROM settings WHERE key='results_published'")
    s = cur.fetchone()
    if not s or row_get(s, 'value') != '1':
        conn.close()
        return jsonify({'success': False})

    classes = {}
    if 'admin_usn' in session:
        # Admin View: Initialize all classes from student database to show empty ones
        semesters = ['1', '2', '3', '4', '5', '6', '7', '8']
        class_names = [
            'CSE A', 'CSE B', 'CSE C', 'CSE D', 'ISE E', 'ISE F', 
            'AIML H', 'CSE(DS) I', 'ECE J', 'ECE K', 'ECE L', 
            'EEE N', 'CIVIL M', 'MECH O'
        ]
        for sem in semesters:
            for cls in class_names:
                cls_key = f"Sem {sem} - {cls}"
                classes[cls_key] = {'males': [], 'females': []}

        cur.execute("SELECT * FROM candidates ORDER BY semester, class, gender, votes DESC")
    else:
        # Student View: Determine specific class/semester
        cur.execute("SELECT class, semester FROM students WHERE usn=%s", (usn,))
        student = cur.fetchone()
        if student:
            row = format_row(student)
            cls_key = f"Sem {row['semester']} - {row['class']}"
            classes[cls_key] = {'males': [], 'females': []}
            cur.execute("SELECT * FROM candidates WHERE class=%s AND semester=%s ORDER BY gender, votes DESC", 
                        (row_get(student, 'class'), row_get(student, 'semester')))
        else:
            cur.execute("SELECT * FROM candidates WHERE usn='NONE'") # Empty set

    rows = cur.fetchall()
    conn.close()
    for r in rows:
        row = format_row(r)
        cls_key = f"Sem {row['semester']} - {row['class']}"
        if cls_key in classes:
            classes[cls_key]['males' if row['gender'] == 'Male' else 'females'].append(row)

    return jsonify({'success': True, 'classes': classes})


if __name__ == '__main__':
    app.run(debug=True)