import urllib.request
for url in ['https://smart-evm.onrender.com/login', 'https://smart-evm.onrender.com/vote']:
    with urllib.request.urlopen(url, timeout=15) as r:
        html = r.read().decode('utf-8')
    print('URL:', url)
    for needle in ['credentials: \'include\'', 'credentials: \'same-origin\'', 'function apiFetch']:
        idx=html.find(needle)
        if idx!=-1:
            print(needle, 'found at', idx)
    print('---')
