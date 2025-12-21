import requests
import os

# Assuming you set these in your session or .env, but for a script we need them explicit or loaded
# I'll use placeholders, please replace or ensure env vars are picked up if you run with `python -m ...` logic
# For now, I'll just write the script to use the URL hardcoded as per your logs.
url = "http://gandalf.home.arpa:3000/api/models"
key = "your-key-here" # REPLACE THIS

print(f"Testing {url}...")
try:
    resp = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=5)
    print(f"Status: {resp.status_code}")
    print(f"Content: {resp.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
