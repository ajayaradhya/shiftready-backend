import os
import json
from datetime import datetime
from typing import List, Dict, Any

from google import genai
from google.genai import types
from dotenv import load_dotenv

from app.models.inventory import RoomBundle

load_dotenv()

class GeminiProcessor:
    def __init__(self, project_id: str):
        """
        Initializes the 2026 Unified Gen AI Client.
        Using vertexai=True anchors this to your GCP infrastructure in Sydney.
        """
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=os.getenv("GCP_REGION", "australia-southeast1")
        )
        # 2026 Standard Model
        self.model_id = "gemini-2.5-flash"

    def process_walkthrough(self, gcs_uri: str) -> List[RoomBundle]:
        """
        Stage 1: Analyzes video with Clock-Time Anchoring to fix first-frame bias.
        """
        prompt = """
        You are a professional home inventory specialist. 
        Analyze this walkthrough video and identify high-value sellable items.

        TEMPORAL LOCALIZATION RULES (CRITICAL):
        1. For every item, identify the START and END time where it is visible.
        2. Provide a 'timestamp_label' in "MM:SS" format (e.g., "01:05") representing 
        the MIDPOINT of that visibility where the item is clearest.
        3. DO NOT default to "00:00" or "00:01". If an item appears at 7 seconds, 
        the label MUST be "00:07".
        4. If the video is empty for the first few seconds, ignore that timeframe.

        EXTRACTION RULES:
        1. Group items into 'Room Bundles'.
        2. Identify brands (Dyson, Koala, Samsung, IKEA) precisely.
        3. Predict 'predicted_original_price' and 'predicted_year_of_purchase'.
        """

        bundle_schema = self._get_clean_schema(RoomBundle)
        
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=[
                types.Part.from_uri(file_uri=gcs_uri, mime_type="video/mp4"),
                prompt
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type="ARRAY",
                    items=bundle_schema
                )
            )
        )

        try:
            raw_data = json.loads(response.text)
            bundles = []
            for b_data in raw_data:
                # --- Temporal Conversion Logic ---
                for item in b_data.get("items", []):
                    label = item.get("timestamp_label")
                    if label and ":" in label:
                        # Convert "MM:SS" to total seconds
                        minutes, seconds = map(int, label.split(":"))
                        item["video_timestamp"] = float(minutes * 60 + seconds)
                    else:
                        item["video_timestamp"] = 0.0
                
                bundles.append(RoomBundle(**b_data))
            return bundles
        except Exception as e:
            print(f"Error: {e}")
            raise e

    def estimate_listing_prices(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Stage 3: Market Analysis. Provides suggested listing prices 
        based on current Sydney market data and user-provided facts.
        """
        inventory_context = json.dumps(items, indent=2)

        prompt = f"""
        Context: You are a Sydney-based resale expert (Facebook Marketplace, Gumtree).
        Current Year: {datetime.now().year}

        Task: Analyze the inventory and provide a competitive 'listing_price' in AUD.
        
        Pricing Rules:
        1. Prioritize 'actual' fields (User Ground Truth) over 'predicted' fields.
        2. Sydney Demand: Fridges, Washing Machines, and Bed Frames are high-demand.
        3. Depreciation: Tech drops ~30%/year; Designer furniture drops ~20%/year.
        4. Target: Quick 7-day sale for a move-out relocation.

        Inventory:
        {inventory_context}

        Output: Return a JSON array of objects with 'id', 'bundle_id', and 'listing_price'.
        """

        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2, # Added intuition for market fluctuation
                response_mime_type="application/json"
            )
        )

        try:
            return json.loads(response.text)
        except Exception as e:
            print(f"Error parsing pricing response: {e}")
            return []

    def _get_clean_schema(self, model) -> Dict[str, Any]:
        """
        Internal Helper: Converts Pydantic models to Gemini-compatible 
        schemas by inlining definitions and removing NULL types.
        """
        schema = model.model_json_schema()
        
        # 1. Inline $defs (Gemini doesn't support references)
        if "$defs" in schema:
            definitions = schema.pop("$defs")
            def inline_refs(obj):
                if isinstance(obj, dict):
                    if "$ref" in obj:
                        ref_name = obj["$ref"].split("/")[-1]
                        return inline_refs(definitions[ref_name])
                    return {k: inline_refs(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [inline_refs(i) for i in obj]
                return obj
            schema = inline_refs(schema)

        # 2. Strip NULL and Forbidden types
        def clean_node(obj):
            if isinstance(obj, dict):
                # Handle Pydantic's 'anyOf' [type, null] pattern
                if "anyOf" in obj:
                    non_null_types = [t for t in obj["anyOf"] if t.get("type") != "null"]
                    if len(non_null_types) == 1:
                        return clean_node(non_null_types[0])
                
                # Filter out ID fields the AI shouldn't generate
                forbidden = ["id", "listing_price", "actual_original_price", 
                             "actual_year_of_purchase", "actual_listing_price"]
                return {k: clean_node(v) for k, v in obj.items() if k not in forbidden}
            elif isinstance(obj, list):
                return [clean_node(i) for i in obj]
            return obj

        return clean_node(schema)