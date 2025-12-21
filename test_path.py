import requests
try:
    resp = requests.get('http://gandalf.home.arpa:3000/api/v1/models', headers={'Authorization': 'Bearer dummy'}, timeout=5)
    print(f"Status: {resp.status_code}")
    print(f"Content: {resp.text[:100]}")
except Exception as e:
    print(e)
