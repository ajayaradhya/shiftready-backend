import os
import time
import subprocess
import requests
import json
import signal
from google.cloud import firestore

# --- Configuration ---
PROJECT_ID = "shiftready-test-project"
EMULATOR_HOST = "localhost:8089"
API_PORT = 8000
API_URL = f"http://localhost:{API_PORT}/api/v1/marketplace"

# Set environment variables so the seed client and the future server use the emulator
os.environ["FIRESTORE_EMULATOR_HOST"] = EMULATOR_HOST
os.environ["GCP_PROJECT_ID"] = PROJECT_ID
os.environ["GCP_UPLOAD_BUCKET"] = "test-bucket"

def start_docker_emulator():
    print("🐳 Starting Firestore Emulator via Docker...")
    # Using the gcloud SDK image to run the firestore emulator
    cmd = [
        "docker", "run", "-d",
        "--name", "sr-firestore-emulator",
        "-p", "8089:8089",
        "google/cloud-sdk:emulators",
        "gcloud", "beta", "emulators", "firestore", "start", "--host-port=0.0.0.0:8089"
    ]
    subprocess.run(["docker", "rm", "-f", "sr-firestore-emulator"], capture_output=True)
    subprocess.run(cmd, check=True)
    
    # Wait for emulator to be ready
    for _ in range(10):
        try:
            requests.get(f"http://{EMULATOR_HOST}")
            break
        except:
            time.sleep(2)
    print("✅ Emulator is live.")

def seed_marketplace_data():
    print("🌱 Seeding Firestore with LIVE sale data...")
    db = firestore.Client(project=PROJECT_ID)
    
    # 1. Create a LIVE sale event in Waterloo
    sale_ref = db.collection("saleEvents").document("test_event_123")
    sale_ref.set({
        "sellerId": "dev_seller_ace",
        "status": "live",
        "suburb": "Waterloo",
        "streetAddress": "123 O'Dea Ave",
        "createdAt": firestore.SERVER_TIMESTAMP
    })

    # 2. Add a Bundle
    bundle_ref = sale_ref.collection("bundles").document("bundle_living_room")
    bundle_ref.set({"name": "Living Room", "suggestedPrice": 500.0})

    # 3. Add Items
    items = [
        {
            "id": "item_sofa",
            "name": "Velvet Sofa",
            "brand": "West Elm",
            "condition": "Excellent",
            "actual_listing_price": 450.0,
            "actual_original_price": 1200.0,
            "actual_year_of_purchase": 2023,
            "confidence": 0.98
        },
        {
            "id": "item_lamp",
            "name": "Industrial Floor Lamp",
            "brand": "IKEA",
            "condition": "Good",
            "actual_listing_price": 50.0,
            "actual_original_price": 99.0,
            "actual_year_of_purchase": 2021,
            "confidence": 1.0
        }
    ]
    
    for item in items:
        item_id = item.pop("id")
        bundle_ref.collection("items").document(item_id).set(item)
    
    print("✅ Data seeded successfully.")
    return "test_event_123", "bundle_living_room", "item_sofa"

def run_tests(event_id, bundle_id, item_id):
    print("\n🔍 Running Marketplace API Tests...")
    
    # Test 1: Anonymous Search
    print("--- Test 1: Anonymous Search (Waterloo) ---")
    res = requests.get(f"{API_URL}/search", params={"suburb": "Waterloo"})
    data = res.json()
    assert res.status_code == 200
    assert data["count"] >= 1
    # Verify masking (Anonymous users shouldn't see originalPrice)
    assert data["items"][0]["metadata"]["originalPrice"] is None
    print(f"✅ Found {data['count']} items. Privacy masking verified.")

    # Test 2: Authenticated Search
    print("--- Test 2: Authenticated Search (Keyword: Velvet) ---")
    headers = {"Authorization": "Bearer dev_tester_2026"}
    res = requests.get(f"{API_URL}/search", params={"q": "Velvet"}, headers=headers)
    data = res.json()
    assert data["items"][0]["name"] == "Velvet Sofa"
    # Authenticated users see premium metadata
    assert data["items"][0]["metadata"]["year"] == 2023
    print("✅ Keyword search and auth-metadata verified.")

    # Test 3: Item Detail
    print(f"--- Test 3: Item Detail ({item_id}) ---")
    res = requests.get(f"{API_URL}/items/{event_id}/{bundle_id}/{item_id}")
    assert res.status_code == 200
    assert res.json()["name"] == "Velvet Sofa"
    print("✅ Item detail retrieval verified.")

if __name__ == "__main__":
    server_proc = None
    try:
        start_docker_emulator()
        eid, bid, iid = seed_marketplace_data()
        
        print(f"🚀 Starting FastAPI Server on port {API_PORT}...")
        server_proc = subprocess.Popen(
            ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(API_PORT)],
            env={**os.environ, "PYTHONPATH": "."}
        )
        time.sleep(5) # Give uvicorn a moment to bind
        
        run_tests(eid, bid, iid)
        print("\n🎉 ALL MARKETPLACE TESTS PASSED!")

    except Exception as e:
        print(f"❌ Testing Failed: {e}")
    finally:
        if server_proc:
            print("🛑 Shutting down server...")
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(server_proc.pid)])
            else:
                os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
        
        print("🗑️  Cleaning up Docker...")
        subprocess.run(["docker", "stop", "sr-firestore-emulator"], capture_output=True)