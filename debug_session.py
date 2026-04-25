from app import app, get_db, hash_password

client = app.test_client()
conn = get_db()
cur = conn.cursor()
cur.execute('SELECT usn FROM students WHERE usn=%s', ('TEST123',))
if not cur.fetchone():
    cur.execute(
        'INSERT INTO students (usn, name, phone, class, semester, password, isVerified, hasVoted) VALUES (%s,%s,%s,%s,%s,%s,1,0)',
        ('TEST123','Test User','test@example.com','CS','5',hash_password('password123'))
    )
    conn.commit()
conn.close()

login_resp = client.post('/api/login', json={'usn':'TEST123','password':'password123'})
print('login status', login_resp.status_code, login_resp.data.decode())
print('set-cookie', login_resp.headers.get('Set-Cookie'))
student_resp = client.get('/api/student_info')
print('student_info', student_resp.status_code, student_resp.data.decode())
