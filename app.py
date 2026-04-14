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

    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
    id SERIAL PRIMARY KEY,
    usn TEXT UNIQUE,
    name TEXT,
    class TEXT,
    semester TEXT,
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
    return render_template('dashboard.html')

@app.route('/results')
def results():
    if 'usn' not in session:
        return redirect(url_for('login'))

    return render_template('results_public.html')

# ---------------- RESULTS ----------------


@app.route('/api/admin/publish_results', methods=['POST'])
def publish_results():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE settings SET value='1' WHERE key='results_published'")
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/results_public')
def results_public():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT value FROM settings WHERE key='results_published'")
    s = cur.fetchone()

    if not s or s['value'] != '1':
        return jsonify({'success': False})

    cur.execute("SELECT * FROM candidates ORDER BY votes DESC")
    data = cur.fetchall()

    return jsonify({'success': True, 'data': [dict(i) for i in data]})


if __name__ == '__main__':
    app.run(debug=True)