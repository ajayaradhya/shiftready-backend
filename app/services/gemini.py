from datetime import datetime
import os
import json
from typing import List
from dotenv import load_dotenv
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from app.models.inventory import RoomBundle

load_dotenv()

class GeminiProcessor:
    def __init__(self, project_id: str):
        # Using the flash model for high-speed, long-context video processing
        self.model = GenerativeModel("gemini-2.5-flash")

    # Helper to remove $defs and $ref for Vertex AI compatibility
    @staticmethod
    def get_gemini_compatible_schema(model):
        # Use 'mode="validation"' to get the schema used for input
        schema = model.model_json_schema()
        
        # 1. Inline definitions (as we did before)
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

        # 2. STRIP NULL TYPES (Fix for the 400 error)
        def clean_nulls(obj):
            if isinstance(obj, dict):
                # If we see an 'anyOf' with a null type, force it to just the non-null type
                if "anyOf" in obj:
                    types = [t for t in obj["anyOf"] if t.get("type") != "null"]
                    if len(types) == 1:
                        return clean_nulls(types[0])
                
                # Explicitly remove fields Gemini shouldn't touch
                # We don't want the AI generating IDs or the final listing price
                forbidden = ["id", "listing_price"]
                return {k: clean_nulls(v) for k, v in obj.items() if k not in forbidden}
            elif isinstance(obj, list):
                return [clean_nulls(i) for i in obj]
            return obj

        return clean_nulls(schema)

    def process_walkthrough(self, gcs_uri: str) -> List[RoomBundle]:
        """
        Processes a video walkthrough from GCS and returns a validated list of RoomBundles.
        Uses constrained output to ensure the response matches the Pydantic model.
        """
        video_part = Part.from_uri(uri=gcs_uri, mime_type="video/mp4")
        
        # This prompt defines the 'Persona' and 'Logic' for the extraction
        prompt = """
        You are a professional home inventory specialist in Sydney, Australia. 
        Analyze this move-out walkthrough video and identify all high-value sellable items.
        
        Rules:
        1. Group items into logical 'Room Bundles' based on their location or category.
        2. Identify brands (e.g., Dyson, Samsung, Koala, IKEA) wherever possible.
        3. Assign a condition based on visual inspection: 'Like-New', 'Good', or 'Visible Wear'.
        4. Estimate the original retail price in AUD based on current Sydney market values.
        5. Provide a confidence score for each identification.
        """

        # Generate the inlined schema
        bundle_schema = self.get_gemini_compatible_schema(RoomBundle)

        response_schema = {
            "type": "array",
            "items": bundle_schema
        }

        # The 'Production-First' magic: The model is forced to follow this schema
        response = self.model.generate_content(
            [video_part, prompt],
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.1,
            )
        )

        try:
            # Because of constrained output, we can trust the JSON structure
            raw_data = json.loads(response.text)
            return [RoomBundle(**b) for b in raw_data]
        except Exception as e:
            # In production, you'd log this to Cloud Logging
            print(f"Error parsing Gemini response: {e}")
            print(f"Raw Response: {response.text}")
            raise e
        
    def estimate_listing_prices(self, items: List[dict]) -> List[dict]:
        """
        Takes the current inventory and asks Gemini to provide 
        listing price estimates based on Sydney's resale market.
        """
        # Convert items to a clean string for the prompt
        inventory_context = json.dumps(items, indent=2)

        prompt = f"""
        Context: You are a professional resale expert in Sydney, Australia. 
        Current Year: {datetime.now().year}

        Task: Analyze the following inventory and provide a 'listing_price' for every item.
        
        Guidelines for Pricing:
        1. Brand Value: High-end brands (Dyson, Samsung, Koala) retain value better.
        2. Age: Use the 'estimated_year_of_purchase' to calculate depreciation.
        3. Condition: 'Like-New' should be priced near 60-80% of original, 'Visible Wear' 20-40%.
        4. Local Demand: Factor in Sydney's high demand for whitegoods and furniture in rental hubs like Waterloo.

        Inventory:
        {inventory_context}

        Output: Return the SAME JSON array but with the 'listing_price' field populated for every item.
        """

        # We use a simplified schema here: just a list of items with IDs and Prices
        response = self.model.generate_content(
            prompt,
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.2 # Slightly higher than 0.1 to allow for 'market intuition'
            )
        )
        
        return json.loads(response.text)