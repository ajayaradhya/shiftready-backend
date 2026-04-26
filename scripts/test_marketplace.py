import os
import sys
import time
import subprocess
import requests
import json
import signal
from dotenv import load_dotenv

# Add the project root to the Python path so we can import from the 'app' directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables from .env file
load_dotenv()

from app.models.schemas import SaleStatus
from google.cloud import firestore

# --- Configuration ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "shiftready-test-project")
EMULATOR_HOST = "127.0.0.1:8089"
API_PORT = 8000
API_URL = f"http://127.0.0.1:{API_PORT}/api/v1/marketplace"

# Set environment variables so the seed client and the future server use the emulator
os.environ["FIRESTORE_EMULATOR_HOST"] = EMULATOR_HOST
os.environ["GCP_PROJECT_ID"] = PROJECT_ID
if "GCP_UPLOAD_BUCKET" not in os.environ:
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
    print("⏳ Waiting for emulator to initialize...")
    for _ in range(15):
        try:
            requests.get(f"http://{EMULATOR_HOST}")
            break
        except:
            time.sleep(2)
    print("✅ Emulator is live.")

def stop_docker_emulator():
    print("🗑️  Cleaning up Docker...")
    subprocess.run(["docker", "stop", "sr-firestore-emulator"], capture_output=True)

def kill_process(proc):
    if not proc:
        return
    print("🛑 Shutting down server...")
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
    else:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

def check_server_health():
    print("🩺 Checking server health...")
    for _ in range(10):
        try:
            res = requests.get(f"http://127.0.0.1:{API_PORT}/health")
            if res.status_code == 200:
                return True
        except:
            time.sleep(1)
    return False

def seed_marketplace_data():
    print("🌱 Seeding Firestore with LIVE sale data...")
    db = firestore.Client(project=PROJECT_ID)
    
    # 1. LIVE Sale (Waterloo)
    s1 = db.collection("saleEvents").document("event_waterloo")
    s1.set({
        "sellerId": "dev_seller_ace",
        "status": SaleStatus.LIVE,
        "suburb": "Waterloo",
        "createdAt": firestore.SERVER_TIMESTAMP
    })
    b1 = s1.collection("bundles").document("b1")
    b1.set({"name": "Living Room"})
    
    # 2. LIVE Sale (Zetland) - Test multi-suburb
    s2 = db.collection("saleEvents").document("event_zetland")
    s2.set({
        "sellerId": "dev_seller_bob",
        "status": SaleStatus.LIVE,
        "suburb": "Zetland",
        "createdAt": firestore.SERVER_TIMESTAMP
    })
    b2 = s2.collection("bundles").document("b2")
    b2.set({"name": "Bedroom"})

    # 3. PENDING Sale (Hidden) - Should not appear in search
    s3 = db.collection("saleEvents").document("event_hidden")
    s3.set({
        "sellerId": "dev_seller_ace",
        "status": SaleStatus.READY_FOR_REVIEW,
        "suburb": "Waterloo",
        "createdAt": firestore.SERVER_TIMESTAMP
    })
    s3.collection("bundles").document("b3").collection("items").document("ghost").set({"name": "Invisible Chair"})

    # Add Items to Live Sales
    items = [
        {"ref": b1, "id": "item_sofa", "name": "Velvet Sofa", "brand": "West Elm", "condition": "Excellent", "actual_listing_price": 450.0, "actual_original_price": 1200.0, "actual_year_of_purchase": 2023, "confidence": 0.98},
        {"ref": b1, "id": "item_lamp", "name": "Industrial Lamp", "brand": "IKEA", "condition": "Good", "actual_listing_price": 50.0, "actual_original_price": 99.0, "actual_year_of_purchase": 2021, "confidence": 1.0},
        {"ref": b2, "id": "item_bed", "name": "Queen Bed", "brand": "Koala", "condition": "New", "actual_listing_price": 800.0, "actual_original_price": 1500.0, "actual_year_of_purchase": 2024, "confidence": 0.95}
    ]
    
    for it in items:
        ref, iid = it.pop("ref"), it.pop("id")
        ref.collection("items").document(iid).set(it)
    
    print("✅ Data seeded: 2 Live Sales (Waterloo, Zetland), 1 Hidden Sale.")
    return "event_waterloo", "b1", "item_sofa"

def run_tests(event_id, bundle_id, item_id):
    print("\n🔍 Running Comprehensive Marketplace API Tests...")
    
    # Test 1: Anonymous Search - Privacy Check
    print("--- Test 1: Anonymous Privacy Masking ---")
    res = requests.get(f"{API_URL}/search", params={"suburb": "Waterloo"})
    data = res.json()
    assert data["count"] == 2
    assert data["items"][0]["metadata"]["originalPrice"] is None
    print("✅ Anonymous users cannot see sensitive metadata.")

    # Test 2: Suburb Filtering
    print("--- Test 2: Suburb Filtering (Zetland) ---")
    res = requests.get(f"{API_URL}/search", params={"suburb": "Zetland"})
    assert res.json()["count"] == 1
    assert res.json()["items"][0]["name"] == "Queen Bed"
    print("✅ Suburb filtering isolated Zetland inventory correctly.")

    # Test 3: Status Filtering (Security)
    print("--- Test 3: Status Visibility ---")
    res = requests.get(f"{API_URL}/search", params={"q": "Invisible"})
    assert res.json()["count"] == 0
    print("✅ Non-LIVE sales are correctly hidden from marketplace.")

    # Test 4: Authenticated Owner View (Confidence Score)
    print("--- Test 4: Owner-Only Metadata ---")
    headers = {"Authorization": "Bearer dev_seller_ace"}
    res = requests.get(f"{API_URL}/search", params={"q": "Sofa"}, headers=headers)
    item = res.json()["items"][0]
    assert item["metadata"]["confidence"] == 0.98
    
    headers_other = {"Authorization": "Bearer dev_buyer_99"}
    res_other = requests.get(f"{API_URL}/search", params={"q": "Sofa"}, headers=headers_other)
    assert res_other.json()["items"][0]["metadata"]["confidence"] is None
    print("✅ Confidence scores only visible to the item owner.")

    # Test 5: Keyword Matching (Case-Insensitive)
    print("--- Test 5: Keyword Search (ikea vs IKEA) ---")
    res = requests.get(f"{API_URL}/search", params={"q": "ikea"})
    assert res.json()["count"] == 1
    print("✅ Search is case-insensitive.")

    # Test 6: Item Detail
    print(f"--- Test 6: Item Detail Retrieval ---")
    res = requests.get(f"{API_URL}/items/{event_id}/{bundle_id}/{item_id}")
    assert res.status_code == 200
    assert res.json()["name"] == "Velvet Sofa"
    print("✅ Full item detail path verified.")

if __name__ == "__main__":
    server_proc = None
    try:
        start_docker_emulator()
        eid, bid, iid = seed_marketplace_data()
        
        print(f"🚀 Starting FastAPI Server on port {API_PORT}...")
        server_proc = subprocess.Popen(
            ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT)],
            env={**os.environ, "PYTHONPATH": "."}
        )

        if not check_server_health():
            print("❌ Server failed to start in time.")
            sys.exit(1)
        
        run_tests(eid, bid, iid)
        print("\n🎉 ALL MARKETPLACE TESTS PASSED!")

    except Exception as e:
        print(f"❌ Testing Failed: {e}")
        sys.exit(1)
    finally:
        kill_process(server_proc)
        stop_docker_emulator()