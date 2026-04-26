import argparse
import os
import sys
import time
import subprocess
import signal
import random
import requests
import json
from websocket import create_connection
from dotenv import load_dotenv

# Add the project root to the Python path for app imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables from .env file
load_dotenv()

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "shiftready-test-project")
EMULATOR_HOST = "localhost:8089"
API_PORT = 8080
API_BASE_URL = f"http://127.0.0.1:{API_PORT}/api/v1"
WS_BASE_URL = f"ws://127.0.0.1:{API_PORT}/api/v1"
VIDEO_FILE = "scripts/test_video.mp4"
USER_ID = "dev_ajay_2026"

# Authentication header for local testing
AUTH_HEADERS = {"Authorization": f"Bearer {USER_ID}"}

# Set environment variables for the emulator
os.environ["FIRESTORE_EMULATOR_HOST"] = EMULATOR_HOST
os.environ["GCP_PROJECT_ID"] = PROJECT_ID
if "GCP_UPLOAD_BUCKET" not in os.environ:
    os.environ["GCP_UPLOAD_BUCKET"] = "test-bucket"

def start_docker_emulator():
    print("🐳 Starting Firestore Emulator via Docker...")
    # Cleanup existing container if any
    subprocess.run(["docker", "rm", "-f", "sr-firestore-emulator"], capture_output=True)
    
    cmd = [
        "docker", "run", "-d",
        "--name", "sr-firestore-emulator",
        "-p", "8089:8089",
        "google/cloud-sdk:emulators",
        "gcloud", "beta", "emulators", "firestore", "start", "--host-port=0.0.0.0:8089"
    ]
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

def wait_for_notification(ws, target_status):
    """
    🔌 Listens on an EXISTING WebSocket for a specific status.
    """
    while True:
        try:
            message = ws.recv()
            data = json.loads(message)
            msg_type = data.get("type", "STATUS_UPDATE")
            
            if msg_type == "ITEM_UPDATED":
                print(f"   [WS Real-time]: Item {data['item_id']} was just updated!")
                continue
        except Exception as e:
            print(f"❌ WS Error: {e}")
            return False

        status = data.get("status")
        print(f"   [WS Notification]: {status} - {data.get('message', '')}")
        
        if status == target_status:
            return True
        if status == "failed":
            return False

def open_ws(event_id):
    ws_url = f"{WS_BASE_URL}/sales/{event_id}/ws?token={USER_ID}"
    print(f"🔌 Opening persistent WebSocket: {ws_url}")
    return create_connection(ws_url, timeout=60)

def get_inventory_item(event_id):
    summary = requests.get(f"{API_BASE_URL}/sales/{event_id}/summary", headers=AUTH_HEADERS).json()
    if not summary.get("bundles"):
        return None, None, None
    bundle = random.choice(summary["bundles"])
    item = random.choice(bundle["items"])
    return bundle["id"], item["id"], item

def run_extraction_stage():
    """Stage 1: AI Visual Extraction"""
    print("\n🚀 STAGE 1: AI Visual Extraction")
    print("-----------------------------------")
    init_res = requests.post(
        f"{API_BASE_URL}/sales/init", 
        json={"filename": VIDEO_FILE}, # USER_ID is now in header
        headers=AUTH_HEADERS
    ).json()
    event_id, upload_url = init_res["event_id"], init_res["upload_url"]

    print(f"📤 Uploading {VIDEO_FILE}...")
    with open(VIDEO_FILE, "rb") as f:
        requests.put(upload_url, data=f, headers={"Content-Type": "video/mp4"})
    
    requests.post(f"{API_BASE_URL}/sales/{event_id}/process", headers=AUTH_HEADERS)
    
    ws = open_ws(event_id) # <--- Open the WebSocket connection
    if wait_for_notification(ws, "ready_for_review"): # <--- Pass the ws object
        _, _, item = get_inventory_item(event_id)
        print(f"✅ Extraction Complete! AI found a [{item['name']}]")
        print(f"   AI Predicted Price: ${item['predicted_original_price']}")
        print(f"   Physicals: {item.get('material', 'N/A')} | {item.get('dimensions', 'N/A')}")
        print(f"   AI Predicted Year: {item['predicted_year_of_purchase']}")
        return event_id, ws # <--- Return the ws object
    ws.close() # <--- Close the websocket if the stage fails
    return None, None # <--- Return None for ws if failed

def run_human_correction_stage(event_id):
    """Stage 2: Human Fact Correction"""
    print("\n🛠️  STAGE 2: Human Fact Correction")
    print("-----------------------------------")
    b_id, i_id, item = get_inventory_item(event_id)
    
    # Simulation: User corrects the AI's guess with Ground Truth
    print(f"📝 Correcting facts for {item['name']}...")
    updates = {
        "brand": "Koala (Premium)", 
        "actual_original_price": 1200.0,
        "actual_year_of_purchase": 2023,
        "condition": "Like-New",
        "dimensions": "203 x 153 x 30 cm",
        "is_fragile": False
    }
    requests.patch(
        f"{API_BASE_URL}/sales/{event_id}/bundles/{b_id}/items/{i_id}", 
        json=updates,
        headers=AUTH_HEADERS
    )
    print("✅ User 'Ground Truth' saved to actual_* fields.")

def run_estimation_stage(event_id, ws):
    """Stage 3: AI Market Pricing"""
    print("\n🧠 STAGE 3: AI Market Pricing")
    print("-----------------------------------")
    print("Triggering LLM expert analysis based on human-verified facts...")
    requests.post(
        f"{API_BASE_URL}/sales/{event_id}/estimate", 
        json={"move_out_date": "2026-05-22"},
        headers=AUTH_HEADERS
    )
    
    if wait_for_notification(ws, "ready_for_review"):
        _, _, item = get_inventory_item(event_id)
        print(f"✅ AI Suggested Listing Price: ${item.get('predicted_listing_price')}")
        print(f"   AI Reasoning: {item.get('pricing_reasoning')}")

def run_publish_stage(event_id):
    """Stage 4: Final Polish & Publish"""
    print("\n🚀 STAGE 4: Final Polish & Publish")
    print("-----------------------------------")
    b_id, i_id, item = get_inventory_item(event_id)
    
    # Simulation: User agrees with AI or makes a final small tweak
    final_price = item.get('predicted_listing_price', 0) - 10 # Let's haggle
    print(f"📝 Finalizing {item['name']} price at ${final_price}...")
    
    requests.patch(
        f"{API_BASE_URL}/sales/{event_id}/bundles/{b_id}/items/{i_id}", 
        json={"actual_listing_price": final_price},
        headers=AUTH_HEADERS
    )
    
    payload = {
        "move_out_date": "2026-05-22",
        "street_address": "123 O'Dea Ave",
        "suburb": "Waterloo",
        "pincode": "2017"
    }
    
    res = requests.post(
        f"{API_BASE_URL}/sales/{event_id}/publish", 
        json=payload,
        headers=AUTH_HEADERS
    ).json()
    
    print(f"🎉 SUCCESS: Sale status is now {res.get('status')}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ShiftReady Production-Test CLI")
    parser.add_argument("--mode", choices=["full", "extract", "correct", "estimate", "publish"], required=True)
    parser.add_argument("--id", help="Event ID required for all modes except 'full' and 'extract'")
    args = parser.parse_args()

    server_proc = None
    try:
        if args.mode in ["full", "extract"]:
            start_docker_emulator()
            
            print(f"🚀 Starting FastAPI Server on port {API_PORT}...")
            server_proc = subprocess.Popen(
                ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT)],
                env={**os.environ, "PYTHONPATH": "."}
            )
            time.sleep(5) # Give the server time to bind

        if args.mode == "full":
            eid, ws = run_extraction_stage()
            if eid and ws:
                run_human_correction_stage(eid)
                run_estimation_stage(eid, ws)
                run_publish_stage(eid)
                ws.close()
                print("\n🎉 FULL RELOCATION PIPELINE SUCCESSFUL!")
        elif args.mode == "extract":
            run_extraction_stage()
            # Leave it running for manual inspection if needed or exit
        
    except Exception as e:
        print(f"❌ Test Execution Failed: {e}")
    finally:
        kill_process(server_proc)
        if args.mode in ["full", "extract"]:
            stop_docker_emulator()

    # Handling standalone modes that assume an external server/DB
    if args.mode == "correct":
        run_human_correction_stage(args.id)
    elif args.mode == "estimate":
        run_estimation_stage(args.id)
    elif args.mode == "publish":
        run_publish_stage(args.id)