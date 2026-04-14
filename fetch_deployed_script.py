import urllib.request
url='https://smart-evm.onrender.com/static/script.js'
print('Fetching', url)
with urllib.request.urlopen(url, timeout=15) as r:
    data = r.read().decode('utf-8')
print(data[:1800])