import json
import logging
from datetime import datetime
from typing import Any, List
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from app.models.inventory import RoomBundle

logger = logging.getLogger(__name__)

class PricingResult(BaseModel):
    """Schema for structured pricing output."""
    id: str = Field(description="The unique ID of the item provided in the input.")
    listing_price: float = Field(description="The suggested AUD listing price after urgency discount.")
    reasoning: str = Field(description="Short explanation including suburb demand.")

class PricingList(BaseModel):
    """Wrapper for a list of pricing results."""
    results: List[PricingResult]


class GeminiProcessor:
    def __init__(self, project_id: str):
        # 2026 Context: Specific Sydney Suburbs for Grounding
        system_instruction = """
        You are the ShiftReady Relocation Agent. You specialize in the Sydney 2026 
        resale market (Waterloo, Zetland, Alexandria, and Surry Hills). 
        Your goal is to ensure items are sold at maximum fair value before the 
        user's move-out deadline. Be precise, realistic, and market-aware.
        """
        
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location="global"
        )
        # Using the stabilized 2026 model
        self.model_id = "gemini-3.1-flash-lite-preview"
        self.system_instruction = system_instruction

    async def process_walkthrough(self, gcs_uri: str) -> tuple[list[RoomBundle], dict[str, Any]]:
        """
        Stage 1: Extraction & Temporal Anchoring.
        """
        prompt = """
        Analyze this video and identify sellable items. 
        Organize items into Room Bundles (e.g., 'Living Room', 'Kitchen').

        TEMPORAL RULES:
        - Identify the midpoint 'timestamp_label' in "MM:SS".
        - Focus on clarity. If an item is blurry, wait for a clear frame.

        DATING & PRICING:
        - Predict 'predicted_original_price' in AUD.
        - Predict 'predicted_year_of_purchase' based on design/ports (USB-C = 2020+).

        PHYSICAL ATTRIBUTES (For Relocation):
        - Estimate 'dimensions' (L x W x H in cm).
        - Identify 'material' (e.g., 'Oak', 'Velvet', 'Stainless Steel').
        - Flag 'is_fragile' (Boolean) and if 'disassembly_required' (Boolean).

        - IMPORTANT: Do not attempt to generate 'id' fields.
        """

        metadata: dict[str, Any] = {
            "model": self.model_id,
            "engine": "google-genai-sdk",
            "status": "processing",
            "video_uri": gcs_uri
        }

        bundle_schema = self._get_clean_schema(RoomBundle)
        
        response = await self.client.aio.models.generate_content(
            model=self.model_id,
            contents=[
                types.Part.from_uri(file_uri=gcs_uri, mime_type="video/mp4"),
                prompt
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                system_instruction=self.system_instruction,
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type="ARRAY",
                    items=bundle_schema
                )
            )
        )

        # Update metadata with actual usage
        metadata["usage"] = response.usage_metadata.model_dump() if hasattr(response, 'usage_metadata') else {}
        metadata["finish_reason"] = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        metadata["status"] = "success"

        try:
            # Handle cases where response.parsed might be a list or a dictionary
            raw_data = response.parsed if response.parsed is not None else json.loads(response.text)
            bundles = []
            for b_data in raw_data:
                for item in b_data.get("items", []):
                    # Convert label to float seconds for the video player
                    label = item.get("timestamp_label", "00:00")
                    try:
                        m, s = map(int, label.split(":"))
                        item["video_timestamp"] = float(m * 60 + s)
                    except (ValueError, AttributeError):
                        item["video_timestamp"] = 0.0
                
                bundles.append(RoomBundle(**b_data))
            return bundles, metadata
        except Exception as e:
            logger.error(f"Failed to parse walkthrough: {e}")
            raise e

    async def estimate_listing_prices(self, items: list[dict[str, Any]], move_out_date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Stage 2: Sydney Market Analysis with Urgency Logic.
        """
        # Define metadata outside try block to avoid UnboundLocalError in except
        metadata: dict[str, Any] = {
            "model": self.model_id,
            "engine": "google-genai-sdk",
            "status": "processing"
        }
        try:
            deadline = datetime.strptime(move_out_date, "%Y-%m-%d")
            days_remaining = (deadline - datetime.now()).days
        except (ValueError, TypeError):
            days_remaining = 14 # Default safety window

        # Urgency Calculation
        urgency_multiplier = 1.0
        if days_remaining <= 3:
            urgency_multiplier = 0.6  # 40% drop for fire sale
        elif days_remaining <= 7:
            urgency_multiplier = 0.8  # 20% drop

        # Using native 2026 Vertex SDK for Structured JSON
        prompt = f"""
            Analyze the following inventory for a move in Sydney. 
            Current Date: {datetime.now().strftime('%Y-%m-%d')}
            Move-out Deadline: {move_out_date} ({days_remaining} days left)
            Apply a {int((1 - urgency_multiplier) * 100)}% Urgency Discount.

            INVENTORY DATA:
            {json.dumps(items, indent=2)}
        """

        try:
            pricing_schema = self._get_clean_schema(PricingList, is_pricing=True)
            
            response = await self.client.aio.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    system_instruction=self.system_instruction,
                    response_mime_type="application/json",
                    response_schema=types.Schema(**pricing_schema)
                )
            )

            # Update usage metadata for LangSmith/GCP monitoring
            metadata["usage"] = response.usage_metadata.model_dump() if hasattr(response, 'usage_metadata') else {}
            
            parsed_data = response.parsed if hasattr(response, 'parsed') else json.loads(response.text)
            
            # Robust parsing for Pydantic objects or raw dicts
            if hasattr(parsed_data, "results"):
                results = [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in parsed_data.results]
            else:
                # Fallback for manual JSON parsing
                results = parsed_data.get("results", []) if isinstance(parsed_data, dict) else []

            metadata.update({"days_remaining": days_remaining, "status": "success"})
            return results, metadata
        except Exception as e:
            logger.error(f"Pricing Pipeline Error: {e}")
            return [], metadata

    def _get_clean_schema(self, model, is_pricing: bool = False) -> dict[str, Any]:
        """
        Cleans Pydantic schemas for Gemini (No $refs, no NULLs).
        """
        schema = model.model_json_schema()
        
        if "$defs" in schema:
            definitions = schema.pop("$defs")
            def inline_refs(obj):
                if isinstance(obj, dict):
                    if "$ref" in obj:
                        ref_name = obj["$ref"].split("/")[-1]
                        return inline_refs(definitions[ref_name])
                    return {k: inline_refs(v) for k, v in obj.items()}
                return [inline_refs(i) for i in obj] if isinstance(obj, list) else obj
            schema = inline_refs(schema)

        def clean_node(obj):
            if isinstance(obj, dict):
                if "anyOf" in obj:
                    non_null = [t for t in obj["anyOf"] if t.get("type") != "null"]
                    if non_null:
                        return clean_node(non_null[0])
                
                # These fields are managed by the Backend/User, not the AI
                forbidden = ["actual_original_price", 
                             "actual_year_of_purchase", "actual_listing_price", 
                             "pricing_reasoning"]
                
                if not is_pricing:
                    forbidden.extend(["id", "listing_price"])

                return {k: clean_node(v) for k, v in obj.items() if k not in forbidden}
            return [clean_node(i) for i in obj] if isinstance(obj, list) else obj

        return clean_node(schema)