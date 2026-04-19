import requests
import os
import time

# Configuration
API_BASE_URL = "http://127.0.0.1:8000"
VIDEO_FILE = "test_video.mp4"
USER_ID = "ajay_dev_test"

def run_e2e_test():
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

if __name__ == "__main__":
    run_e2e_test()