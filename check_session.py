import http.client
import json
import ssl
url = 'smart-evm.onrender.com'
conn = http.client.HTTPSConnection(url, context=ssl.create_default_context())
conn.request('POST', '/api/login', json.dumps({'usn': 'ADMIN', 'password': 'admin123'}), {'Content-Type': 'application/json'})
resp = conn.getresponse()
print('status', resp.status)
print('headers:')
for k, v in resp.getheaders():
    if k.lower() == 'set-cookie':
        print('SET-COOKIE:', v)
print('body:', resp.read().decode())
