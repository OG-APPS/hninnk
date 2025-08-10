import requests
def test_health():
    # assumes running
    r = requests.get("http://127.0.0.1:8000/health", timeout=2)
    assert r.status_code == 200
