import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from app.models.inventory import RoomBundle
from typing import List
import json

class GeminiProcessor:
    def __init__(self, project_id: str, location: str = "australia-southeast1"):
        vertexai.init(project=project_id, location=location)
        self.model = GenerativeModel("gemini-1.5-flash")

    def process_walkthrough(self, gcs_uri: str) -> List[RoomBundle]:
        # Reference the video in GCS
        video_part = Part.from_uri(uri=gcs_uri, mime_type="video/mp4")
        
        # System Instruction for structured extraction
        prompt = """
        Analyze this home walkthrough video for a move-out sale. 
        1. Identify high-value items (Electronics, Furniture, Appliances).
        2. Group them into logical Room Bundles.
        3. Estimate the original retail price in AUD based on Sydney market standards.
        4. Detect brands and condition (Like-New, Good, Visible Wear).
        
        Return ONLY a JSON array of bundles.
        """

        # Ensure Gemini returns strictly valid JSON
        config = GenerationConfig(
            response_mime_type="application/json",
            candidate_count=1
        )

        response = self.model.generate_content(
            [video_part, prompt],
            generation_config=config
        )

        # Parse the raw string into our Pydantic models
        raw_data = json.loads(response.text)
        return [RoomBundle(**b) for b in raw_data]