import requests

# Use the exact URL from your logs
base_url = "http://gandalf.home.arpa:3000"
# Use a dummy key to probe endpoints
api_key = "sk-dummy-key" 

endpoints_to_test = [
    f"{base_url}/api/models",       # Open WebUI native
    f"{base_url}/v1/models",        # OpenAI compatibility
]

print(f"Testing connectivity to {base_url}...")

for url in endpoints_to_test:
    print(f"\n--- Testing {url} ---")
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type', 'Unknown')}")
        print(f"Preview: {resp.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")