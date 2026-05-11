"""
HealthSignal — Load test.
Sends batches of prediction requests to the local API.
Run after docker-compose up to see Grafana metrics populate.
Usage: python3 load_test.py
"""
import random
import time
import json
import urllib.request
import urllib.error

API_URL = "http://localhost:8000"

def random_employee():
    high_risk = random.random() < 0.25  # ~25% high risk
    return {
        "age": random.randint(22, 65),
        "tenure_years": random.randint(0, 30),
        "absences_last_year": random.randint(6, 15) if high_risk else random.randint(0, 3),
        "absences_last_3months": random.randint(3, 6) if high_risk else random.randint(0, 1),
        "department_stress_score": round(random.uniform(7.5, 10.0) if high_risk else random.uniform(1.0, 6.0), 1),
        "previous_long_term": 1 if high_risk and random.random() < 0.5 else 0,
        "part_time": random.randint(0, 1),
        "manager_support_score": round(random.uniform(1.0, 4.0) if high_risk else random.uniform(6.0, 10.0), 1),
    }

def post_json(url, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())

def check_health():
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=3) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return None

print("=" * 50)
print("HealthSignal — Load Test")
print("=" * 50)

# Wait for API
print("\nWaiting for API to be ready...")
for i in range(10):
    health = check_health()
    if health and health.get("status") == "ok":
        print(f"API ready! Model loaded: {health['model_loaded']}, ES: {health['elasticsearch']}")
        break
    print(f"  Attempt {i+1}/10...")
    time.sleep(3)
else:
    print("API not reachable. Make sure docker-compose is running.")
    exit(1)

# Run load test
total = 0
high_risk_count = 0
errors = 0
print(f"\nSending predictions... (Ctrl+C to stop)\n")

try:
    while True:
        emp = random_employee()
        try:
            result = post_json(f"{API_URL}/predict", emp)
            total += 1
            if result["risk_level"] == "HIGH":
                high_risk_count += 1
            icon = "🔴" if result["risk_level"] == "HIGH" else "🟢"
            print(f"{icon} [{total:4d}] risk={result['risk_level']:4s} prob={result['probability']:.3f} | {result['recommendation'][:55]}")
        except Exception as e:
            errors += 1
            print(f"❌ Error: {e}")

        time.sleep(0.5)

except KeyboardInterrupt:
    print(f"\n\n{'='*50}")
    print(f"Load test complete.")
    print(f"  Total predictions : {total}")
    print(f"  High risk flagged : {high_risk_count} ({high_risk_count/max(total,1)*100:.1f}%)")
    print(f"  Errors            : {errors}")
    print(f"\nCheck Grafana at http://localhost:3000 (admin/admin123)")
    print(f"Check Kibana   at http://localhost:5601")
    print(f"Check API docs at http://localhost:8000/docs")
