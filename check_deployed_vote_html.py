import urllib.request
url='https://smart-evm.onrender.com/vote'
with urllib.request.urlopen(url, timeout=15) as r:
    html = r.read().decode('utf-8')
start = html.find('function apiFetch')
print(html[start:start+800])
print('---')
pos = html.find('credentials:')
print(html[pos:pos+80])
