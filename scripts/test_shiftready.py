import argparse
import random
import requests
import json
import os
import time
from websocket import create_connection
from datetime import datetime

# Configuration
API_BASE_URL = "http://127.0.0.1:8000/api/v1"
WS_BASE_URL = "ws://127.0.0.1:8000/api/v1"
VIDEO_FILE = "test_video.mp4"
USER_ID = "ajay_dev_test"

# Authentication header for local testing
AUTH_HEADERS = {"X-User-ID": USER_ID}

def wait_for_notification(event_id, target_status):
    """
    🔌 WebSocket Client: Listens for the server to push a status update.
    """
    ws_url = f"{WS_BASE_URL}/sales/{event_id}/ws?token={USER_ID}"
    print(f"🔌 Connecting to WebSocket: {ws_url}")
    ws = create_connection(ws_url, timeout=60) # Fail if no message in 60s
    try:
        while True:
            message = ws.recv()
            data = json.loads(message)
            status = data.get("status")
            print(f"   [WS Notification]: {status} - {data.get('message', '')}")
            
            if status == target_status:
                return True
            if status == "failed":
                print(f"❌ Pipeline failed: {data.get('error')}")
                return False
    finally:
        ws.close()

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
    if wait_for_notification(event_id, "ready_for_review"):
        _, _, item = get_inventory_item(event_id)
        print(f"✅ Extraction Complete! AI found a [{item['name']}]")
        print(f"   AI Predicted Price: ${item['predicted_original_price']}")
        print(f"   AI Predicted Year: {item['predicted_year_of_purchase']}")
        return event_id
    return None

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
        "condition": "Like-New"
    }
    requests.patch(
        f"{API_BASE_URL}/sales/{event_id}/bundles/{b_id}/items/{i_id}", 
        json=updates,
        headers=AUTH_HEADERS
    )
    print("✅ User 'Ground Truth' saved to actual_* fields.")

def run_estimation_stage(event_id):
    """Stage 3: AI Market Pricing"""
    print("\n🧠 STAGE 3: AI Market Pricing")
    print("-----------------------------------")
    print("Triggering LLM expert analysis based on human-verified facts...")
    requests.post(f"{API_BASE_URL}/sales/{event_id}/estimate", headers=AUTH_HEADERS)
    
    if wait_for_notification(event_id, "ready_for_review"):
        _, _, item = get_inventory_item(event_id)
        print(f"✅ AI Suggested Listing Price: ${item.get('predicted_listing_price')}")

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
    
    payload = {"move_out_date": "2026-05-22"}
    
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

    if args.mode == "full":
        eid = run_extraction_stage()
        if eid:
            run_human_correction_stage(eid)
            run_estimation_stage(eid)
            run_publish_stage(eid)
    elif args.mode == "extract":
        run_extraction_stage()
    elif args.mode == "correct":
        run_human_correction_stage(args.id)
    elif args.mode == "estimate":
        run_estimation_stage(args.id)
    elif args.mode == "publish":
        run_publish_stage(args.id)