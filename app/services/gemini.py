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