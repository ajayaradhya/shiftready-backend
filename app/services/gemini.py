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
        # 2026 Best Practice: Centralized System Instruction
        system_instruction = """
        You are the ShiftReady Relocation Agent. You specialize in the Sydney 2026 
        resale market (Waterloo/Zetland/Alexandria). 
        Your goal is to ensure items are sold at maximum fair value before the 
        user's move-out deadline. Be precise, realistic, and market-aware.
        """
        
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location="global"
        )
        self.model_id = "gemini-3.1-flash-lite-preview"
        self.system_instruction = system_instruction

    def process_walkthrough(self, gcs_uri: str) -> List[RoomBundle]:
        """
        Stage 1: Analyzes video with Clock-Time Anchoring to fix first-frame bias.
        """
        prompt = """
        You are a professional home inventory specialist in 2026.
        Analyze this video and identify sellable items.

        TEMPORAL LOCALIZATION RULES:
        1. For every item, identify the START and END time where it is visible.
        2. Provide a 'timestamp_label' in "MM:SS" format (e.g., "01:05") representing 
        the MIDPOINT of that visibility where the item is clearest.
        3. DO NOT default to "00:00" or "00:01". If an item appears at 7 seconds, 
        the label MUST be "00:07".
        4. If the video is empty for the first few seconds, ignore that timeframe.

        DATING CLUES for 'predicted_year_of_purchase':
        1. USB-C CHECK: If an electronic item has a USB-C port, it is almost certainly 2020-2026.
        2. DESIGN LOGIC: Look for matte finishes, thin bezels, and minimalist branding typical of 2022+ designs.
        3. LOGO ANCHOR: Use the 2026 versions of brand logos (e.g., the simplified Dyson or Samsung logos).
        4. HARD RULE: DO NOT default to 2010. If the item looks well-maintained but the age is unclear, guess between 2021 and 2025. 

        EXTRACTION:
        1. Identify Brands precisely.
        2. Predict 'predicted_original_price' in AUD.
        3. Predict 'predicted_year_of_purchase' using the Dating Clues above.
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
                ),
                tools=[types.Tool(google_search=types.GoogleSearch())]
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

    def estimate_listing_prices(self, items: List[Dict[str, Any]], move_out_date: str) -> List[Dict[str, Any]]:
        inventory_context = json.dumps(items, indent=2)
        days_remaining = (datetime.strptime(move_out_date, "%Y-%m-%d") - datetime.now()).days

        prompt = f"""
        Current Date: {datetime.now().strftime('%Y-%m-%d')}
        Move-out Deadline: {move_out_date} ({days_remaining} days remaining)

        TASK: Estimate listing prices for these items in the Sydney market.
        
        MARKET CONTEXT:
        - Waterloo/Zetland high-density apartment rules apply.
        - Urgency Factor: { 'EXTREME' if days_remaining < 7 else 'NORMAL' }.
        
        INVENTORY DATA:
        {inventory_context}

        For each item, provide a 'listing_price' (AUD) and a 'reasoning' string 
        explaining the price (e.g., "High demand in Waterloo" or "Heavy depreciation").
        """

        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction, # Persona efficiency
                temperature=0.3,
                response_mime_type="application/json",
                # ADDED: Search grounding for the Pricing Stage!
                tools=[types.Tool(google_search=types.GoogleSearch())] 
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