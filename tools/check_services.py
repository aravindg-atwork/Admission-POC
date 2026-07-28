"""Check which services are running."""
import urllib.request
import json
import os
import sys

# Check Ollama
try:
    req = urllib.request.Request("http://localhost:11434/api/tags")
    with urllib.request.urlopen(req, timeout=3) as f:
        print("Ollama is running")
        data = json.loads(f.read())
        for model in data.get("models", []):
            print(f"  - {model['name']}")
except Exception as e:
    print(f"Ollama not running: {e}")

# Check embedding service
try:
    req = urllib.request.Request(
        "http://localhost:8000/embed",
        data=b'{"texts":["test"]}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as f:
        print("Embedding service is running")
except Exception as e:
    print(f"Embedding service not running: {e}")

# Check .env file
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.example")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                print(f"  .env.example: {line.split('=')[0]}")

# Check SARVAM key
sarvam_key = os.environ.get("SARVAM_API_KEY", "")
print(f"SARVAM_API_KEY set in env: {bool(sarvam_key)}")
chat_primary = os.environ.get("CHAT_PRIMARY", "")
print(f"CHAT_PRIMARY: {chat_primary or 'sarvam (default)'}")

# Check if we can use the backend directly with a different approach
# The issue is the embedding service is down. Let's check if there's a fallback
print(f"\nChecking backend /api/chat directly...")
try:
    req = urllib.request.Request("http://localhost:5050/api/chat")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-Key", "aas_test")
    req.data = json.dumps({"question": "hello"}).encode("utf-8")
    req.method = "POST"
    with urllib.request.urlopen(req, timeout=5) as f:
        result = json.loads(f.read())
        print(f"Success: {result.get('answerText', '')[:100]}")
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode()[:200]}")
except Exception as e:
    print(f"Error: {e}")