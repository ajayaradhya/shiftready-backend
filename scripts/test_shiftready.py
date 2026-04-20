import argparse
import random
import requests
import os
import time

# Configuration
API_BASE_URL = "http://127.0.0.1:8000"
VIDEO_FILE = "test_video.mp4"
USER_ID = "ajay_dev_test"

def poll_for_status(event_id, target_status="ready_for_review"):
    print(f"⏳ Polling for status: {target_status}...")
    attempts = 0
    while attempts < 15:
        res = requests.get(f"{API_BASE_URL}/sales/{event_id}/status").json()
        status = res.get("status")
        print(f"   Current Status: {status}")
        if status == target_status:
            return True
        if status == "failed":
            return False
        time.sleep(10)
        attempts += 1
    return False

def get_random_item_ids(event_id):
    res = requests.get(f"{API_BASE_URL}/sales/{event_id}/summary").json()
    bundle = random.choice(res["bundles"])
    item = random.choice(bundle["items"])
    return bundle["id"], item["id"]

def run_extraction_stage():
    """Stage 1: Video -> Extraction (No Pricing)"""
    print("🚀 Stage 1: Initializing & Uploading...")
    init_res = requests.post(f"{API_BASE_URL}/sales/init", json={"user_id": USER_ID, "filename": VIDEO_FILE}).json()
    event_id, upload_url = init_res["event_id"], init_res["upload_url"]

    with open(VIDEO_FILE, "rb") as f:
        requests.put(upload_url, data=f, headers={"Content-Type": "video/mp4"})
    
    requests.post(f"{API_BASE_URL}/sales/{event_id}/process")
    if poll_for_status(event_id):
        print(f"✅ Extraction Complete! Event ID: {event_id}")
        return event_id
    return None

def run_estimate_stage(event_id):
    """Stage 2: Human Edit -> AI Price Estimation"""
    print(f"🛠️  Stage 2: Editing facts & triggering AI Pricing for {event_id}...")
    b_id, i_id = get_random_item_ids(event_id)
    
    # Simulate a user correction (e.g., they realized it's a better brand)
    updates = {
        "brand": "Koala (Premium)",
        "estimated_year_of_purchase": 2024,
        "original_price": 1500.0
    }
    requests.patch(f"{API_BASE_URL}/sales/{event_id}/bundles/{b_id}/items/{i_id}", json=updates)
    
    print("🧠 Triggering LLM Market Analysis...")
    requests.post(f"{API_BASE_URL}/sales/{event_id}/estimate")
    
    if poll_for_status(event_id):
        print("✅ AI Pricing Estimates Updated!")

def run_publish_stage(event_id):
    """Stage 3: Final Price Polish -> Live"""
    print(f"🚀 Stage 3: Finalizing and Publishing {event_id}...")
    b_id, i_id = get_random_item_ids(event_id)
    
    # Simulate user setting the final listing price manually
    requests.patch(f"{API_BASE_URL}/sales/{event_id}/bundles/{b_id}/items/{i_id}", json={"listing_price": 950.0})
    
    res = requests.post(f"{API_BASE_URL}/sales/{event_id}/publish").json()
    print(f"🎉 {res['message']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "extract", "estimate", "publish"], required=True)
    parser.add_argument("--id", help="Required for estimate and publish modes")
    args = parser.parse_args()

    if args.mode == "full":
        eid = run_extraction_stage()
        if eid:
            run_estimate_stage(eid)
            run_publish_stage(eid)
    elif args.mode == "extract":
        run_extraction_stage()
    elif args.mode == "estimate":
        run_estimate_stage(args.id)
    elif args.mode == "publish":
        run_publish_stage(args.id)