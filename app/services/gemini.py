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
        self.model = GenerativeModel("gemini-1.5-flash")

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

        # Generate the JSON schema directly from the Pydantic model
        # Gemini expects a dictionary representation of the OpenAPI/JSON schema
        response_schema = {
            "type": "array",
            "items": RoomBundle.model_json_schema()
        }

        # The 'Production-First' magic: The model is forced to follow this schema
        response = self.model.generate_content(
            [video_part, prompt],
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.1,  # Low temperature for deterministic output
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