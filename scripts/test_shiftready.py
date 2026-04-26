import argparse
import random
import requests
import json
from websocket import create_connection

# Configuration
API_BASE_URL = "http://127.0.0.1:8080/api/v1"
WS_BASE_URL = "ws://127.0.0.1:8080/api/v1"
VIDEO_FILE = "test_video.mp4"
USER_ID = "dev_ajay_2026"

# Authentication header for local testing
AUTH_HEADERS = {"Authorization": f"Bearer {USER_ID}"}

def wait_for_notification(ws, target_status):
    """
    🔌 Listens on an EXISTING WebSocket for a specific status.
    """
    while True:
        message = ws.recv()
        data = json.loads(message)
        msg_type = data.get("type", "STATUS_UPDATE")
        
        if msg_type == "ITEM_UPDATED":
            print(f"   [WS Real-time]: Item {data['item_id']} was just updated!")
            continue

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

    if args.mode == "full":
        eid, ws = run_extraction_stage()
        if eid and ws:
            run_human_correction_stage(eid)
            run_estimation_stage(eid, ws)
            run_publish_stage(eid)
            ws.close()
    elif args.mode == "extract":
        run_extraction_stage()
    elif args.mode == "correct":
        run_human_correction_stage(args.id)
    elif args.mode == "estimate":
        run_estimation_stage(args.id)
    elif args.mode == "publish":
        run_publish_stage(args.id)