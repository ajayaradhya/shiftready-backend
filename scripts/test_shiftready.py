import argparse
import random

import requests
import os
import time


# Configuration
API_BASE_URL = "http://127.0.0.1:8000"
VIDEO_FILE = "test_video.mp4"
USER_ID = "ajay_dev_test"


def get_summary(event_id):
    print(f"🔍 Fetching summary for: {event_id}...")
    res = requests.get(f"{API_BASE_URL}/sales/{event_id}/summary")
    if res.status_code != 200:
        print(f"❌ Failed to fetch summary: {res.text}")
        return None
    return res.json()

def edit_random_item(event_id):
    summary = get_summary(event_id)
    if not summary or not summary.get("bundles"):
        print("❌ No bundles found to edit.")
        return None, None

    # Pick a random bundle and a random item
    bundle = random.choice(summary["bundles"])
    if not bundle.get("items"):
        print(f"❌ Bundle {bundle.get('bundle_name')} has no items.")
        return None, None
        
    item = random.choice(bundle["items"])
    
    new_price = round(random.uniform(10, 500), 2)
    print(f"🛠️  Editing Item: [{item.get('name')}] in Bundle: [{bundle.get('bundle_name')}]")
    print(f"💰 Changing price from ${item.get('listing_price')} to ${new_price}")

    # Step: PATCH update
    update_url = f"{API_BASE_URL}/sales/{event_id}/bundles/{bundle.get('id')}/items/{item.get('id')}"
    patch_res = requests.patch(update_url, json={"listing_price": new_price})
    
    if patch_res.status_code == 200:
        print("✅ Item updated successfully.")
        return bundle.get('id'), item.get('id')
    else:
        print(f"❌ Patch failed: {patch_res.text}")
        return None, None

def publish_sale(event_id):
    print(f"🚀 Publishing sale: {event_id}...")
    res = requests.post(f"{API_BASE_URL}/sales/{event_id}/publish")
    if res.status_code == 200:
        print("🎉 Sale is now LIVE!")
    else:
        print(f"❌ Failed to publish: {res.text}")

def run_full_flow():
    if not os.path.exists(VIDEO_FILE):
        print(f"❌ Error: {VIDEO_FILE} not found in current directory.")
        return

    print("🚀 Step 1: Initializing Sale and getting Signed URL...")
    init_payload = {
        "user_id": USER_ID,
        "filename": VIDEO_FILE
    }
    
    # 1. Call /sales/init
    response = requests.post(f"{API_BASE_URL}/sales/init", json=init_payload)
    if response.status_code != 200:
        print(f"❌ Init failed: {response.text}")
        return
    
    data = response.json()
    event_id = data["event_id"]
    upload_url = data["upload_url"]
    print(f"✅ Event Created: {event_id}")

    # 2. Upload Video to GCS using the Signed URL
    print(f"📤 Step 2: Uploading {VIDEO_FILE} to GCS (Direct Put)...")
    with open(VIDEO_FILE, "rb") as f:
        # Note: We must match the content-type defined in gcs.py (video/mp4)
        upload_res = requests.put(
            upload_url, 
            data=f, 
            headers={"Content-Type": "video/mp4"}
        )
    
    if upload_res.status_code == 200:
        print("✅ Upload Successful!")
    else:
        print(f"❌ Upload Failed: {upload_res.status_code}")
        print(upload_res.text)
        return

    # 3. Trigger the AI Pipeline
    print("🧠 Step 3: Triggering Gemini 1.5 Flash Processing...")
    process_res = requests.post(f"{API_BASE_URL}/sales/{event_id}/process")
    print(f"✅ AI Response: {process_res.json()['message']}")

    # 4. Poll for results
    print("⏳ Step 4: Polling for results (this may take 20-40 seconds)...")
    attempts = 0
    while attempts < 10:
        status_res = requests.get(f"{API_BASE_URL}/sales/{event_id}/status")
        status = status_res.json()["status"]
        print(f"Current Status: {status}")
        
        if status == "ready_for_review":
            print("\n🎉 SUCCESS! Gemini has finished extracting your inventory.")
            print(f"Check your Firestore console for Event ID: {event_id}")
            break
        elif status == "failed":
            print("❌ AI Processing failed. Check server logs.")
            break
            
        time.sleep(10)
        attempts += 1

    if status != "failed":
        print("\n🔧 Step 5: Editing a random item and publishing the sale...")
        edit_random_item(event_id)
        print("✅ Item edited. Now publishing the sale...")
        publish_sale(event_id)
        print("🎉 Full flow test completed successfully!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ShiftReady Test CLI")
    parser.add_argument("--mode", choices=["full", "manage"], required=True, help="Run full pipeline or just management")
    parser.add_argument("--id", help="Event ID (required for manage mode)")
    
    args = parser.parse_args()

    if args.mode == "manage":
        if not args.id:
            print("❌ Error: --id is required for manage mode.")
        else:
            # 1. Fetch & Edit
            b_id, i_id = edit_random_item(args.id)
            if b_id:
                # 2. Finalize
                publish_sale(args.id)
    
    elif args.mode == "full":
        print("Running full video pipeline...")
        run_full_flow()