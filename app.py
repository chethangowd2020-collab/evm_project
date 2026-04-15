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

    conn.commit()
    conn.close()


init_db()


def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin'):
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    if 'usn' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'usn' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/api/register_candidate', methods=['POST'])
def register_candidate():
    try:
        if 'usn' not in session:
            return jsonify({'success': False, 'message': 'Not logged in'})

        data = request.get_json()
        gender = data.get('gender')

        conn = get_db()
        cur = conn.cursor()

        # Get student info
        cur.execute("SELECT * FROM students WHERE usn=%s", (session['usn'],))
        student = cur.fetchone()

        if not student:
            return jsonify({'success': False, 'message': 'Student not found'})

        # Check if already candidate
        cur.execute("SELECT * FROM candidates WHERE usn=%s", (session['usn'],))
        existing = cur.fetchone()

        if existing:
            return jsonify({'success': False, 'message': 'Already registered as candidate'})

        # Insert candidate
        cur.execute("""
            INSERT INTO candidates (usn, name, class, semester, gender)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            session['usn'],
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
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM candidates ORDER BY votes DESC")
        data = cur.fetchall()
        conn.close()

        return jsonify({
            'success': True,
            'data': [dict(row) for row in data]
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
            'data': [dict(row) for row in data]
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
            'data': [dict(row) for row in data]
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
        cur.execute("SELECT value FROM settings WHERE key='voting_enabled'")
        data = cur.fetchone()
        conn.close()
        
        enabled = row_get(data, 'value') == '1'
        
        return jsonify({
            'success': True,
            'enabled': enabled
        })
    except Exception as e:
        print("Voting Status Error:", str(e))
        return jsonify({'success': False, 'message': str(e)})

@app.route('/vote')
def vote():
    if 'usn' not in session:
        return redirect(url_for('login'))

    return render_template('vote.html')

@app.route('/api/student_info')
def student_info():
    if 'usn' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE usn=%s", (session['usn'],))
    student = cur.fetchone()

    if not student:
        return jsonify({'success': False, 'message': 'Student not found'})

    cur.execute("SELECT * FROM votes WHERE usn=%s", (session['usn'],))
    vote = cur.fetchone()

    cur.execute("SELECT * FROM candidates WHERE usn=%s", (session['usn'],))
    candidate = cur.fetchone()
    conn.close()

    return jsonify({
        'success': True,
        'usn': row_get(student, 'usn'),
        'name': row_get(student, 'name'),
        'class': row_get(student, 'class'),
        'semester': row_get(student, 'semester'),
        'hasVoted': True if vote else False,
        'isCandidate': True if candidate else False
    })



@app.route('/admin')
def admin():
    if not session.get('admin'):
        return redirect('/login')  # or '/admin_login_page'

    return render_template('admin.html')

@app.route('/results')
def results():
    if 'usn' not in session:
        return redirect(url_for('login'))

    return render_template('results_public.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    usn = data.get('usn', '').strip().upper()
    password = data.get('password', '')

    # Admin login check
    if usn == ADMIN_USN and password == ADMIN_PASSWORD:
        session['usn'] = usn
        session['role'] = 'admin'
        session.permanent = True
        session['admin'] = True
        return jsonify({'success': True, 'role': 'admin'})

    # Student login check
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE usn=%s", (usn,))
    user = cur.fetchone()
    conn.close()

    if not user:
        return jsonify({'success': False, 'message': 'User not found'})

    if row_get(user, 'password') != hash_password(password):
        return jsonify({'success': False, 'message': 'Wrong password'})

    session['usn'] = usn
    session['role'] = 'student'
    session.permanent = True
    return jsonify({'success': True, 'role': 'student'})
# ---------------- RESULTS ----------------


@app.route('/api/admin/publish_results', methods=['POST'])
@admin_required
def publish_results():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE settings SET value='1' WHERE key='results_published'")
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/results')
@admin_required
def admin_results():
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM candidates ORDER BY votes DESC")
        data = cur.fetchall()
        conn.close()

        return jsonify({
            'success': True,
            'data': [dict(row) for row in data]
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

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
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/results_public')
def results_public():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT value FROM settings WHERE key='results_published'")
    s = cur.fetchone()

    if not s or s['value'] != '1':
        conn.close()
        return jsonify({'success': False})

    cur.execute("SELECT * FROM candidates ORDER BY votes DESC")
    data = cur.fetchall()
    conn.close()

    return jsonify({'success': True, 'data': [dict(row) for row in data]})


if __name__ == '__main__':
    app.run(debug=True)