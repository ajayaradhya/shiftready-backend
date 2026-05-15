import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.ai.schema_utils import get_clean_schema
from app.models.inventory import RoomBundle

logger = logging.getLogger(__name__)

_FRAMES_PROMPT = """
You are analyzing photos of household items for a home relocation sale.
Each image shows one item the seller confirmed they want to list.

For each image, identify the item and create a listing entry.
Group items into appropriate Room Bundles (e.g., 'Living Room', 'Kitchen').

PRICING:
- Predict 'predicted_original_price' in AUD.
- Predict 'predicted_year_of_purchase' based on design and port types.

PHYSICAL ATTRIBUTES:
- Estimate 'dimensions' (L x W x H in cm).
- Identify 'material' (e.g., 'Oak', 'Velvet', 'Stainless Steel').
- Flag 'is_fragile' and 'disassembly_required'.

Set 'timestamp_label' to "" (no video involved).
Do not generate 'id' fields.
"""

_PROMPT = """
Analyze this video and identify sellable items.
Organize items into Room Bundles (e.g., 'Living Room', 'Kitchen').

TEMPORAL RULES:
- Set 'timestamp_label' (format "MM:SS") to the single moment the item is MOST clearly
  visible: camera stationary or slow-panning, item centered in frame, well-lit, unobstructed
  by hands or other objects, no motion blur. This timestamp is used to extract a still frame
  that will be shown to buyers, so accuracy matters.
- If an item appears multiple times, choose the clearest appearance.

DATING & PRICING:
- Predict 'predicted_original_price' in AUD.
- Predict 'predicted_year_of_purchase' based on design/ports (USB-C = 2020+).

PHYSICAL ATTRIBUTES (For Relocation):
- Estimate 'dimensions' (L x W x H in cm).
- Identify 'material' (e.g., 'Oak', 'Velvet', 'Stainless Steel').
- Flag 'is_fragile' (Boolean) and if 'disassembly_required' (Boolean).

- IMPORTANT: Do not attempt to generate 'id' fields.
"""


class ExtractionService:
    def __init__(self, client: genai.Client, model_id: str, system_instruction: str):
        self._client = client
        self._model_id = model_id
        self._system_instruction = system_instruction

    async def process_walkthrough(
        self, gcs_uri: str
    ) -> tuple[list[RoomBundle], dict[str, Any]]:
        metadata: dict[str, Any] = {
            "model": self._model_id,
            "engine": "google-genai-sdk",
            "status": "processing",
            "video_uri": gcs_uri,
        }

        bundle_schema = get_clean_schema(RoomBundle)

        response = await self._client.aio.models.generate_content(
            model=self._model_id,
            contents=[
                types.Part.from_uri(file_uri=gcs_uri, mime_type="video/mp4"),
                _PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                system_instruction=self._system_instruction,
                response_mime_type="application/json",
                response_schema=types.Schema(type="ARRAY", items=bundle_schema),
            ),
        )

        metadata["usage"] = (
            response.usage_metadata.model_dump()
            if hasattr(response, "usage_metadata")
            else {}
        )
        metadata["finish_reason"] = (
            response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        )
        metadata["status"] = "success"

        try:
            raw_data = (
                response.parsed
                if response.parsed is not None
                else json.loads(response.text)
            )
            bundles = []
            for b_data in raw_data:
                for item in b_data.get("items", []):
                    label = item.get("timestamp_label", "00:00")
                    try:
                        m, s = map(int, label.split(":"))
                        item["video_timestamp"] = float(m * 60 + s)
                    except (ValueError, AttributeError):
                        item["video_timestamp"] = 0.0
                bundles.append(RoomBundle(**b_data))
            return bundles, metadata
        except Exception as exc:
            logger.error(f"Failed to parse walkthrough response: {exc}")
            raise

    async def process_frames(
        self, gcs_uris: list[str]
    ) -> tuple[list[RoomBundle], dict[str, Any]]:
        metadata: dict[str, Any] = {
            "model": self._model_id,
            "engine": "google-genai-sdk",
            "status": "processing",
            "frame_count": len(gcs_uris),
        }

        bundle_schema = get_clean_schema(RoomBundle)

        parts: list[Any] = [
            types.Part.from_uri(file_uri=uri, mime_type="image/jpeg")
            for uri in gcs_uris
        ]
        parts.append(_FRAMES_PROMPT)

        response = await self._client.aio.models.generate_content(
            model=self._model_id,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.1,
                system_instruction=self._system_instruction,
                response_mime_type="application/json",
                response_schema=types.Schema(type="ARRAY", items=bundle_schema),
            ),
        )

        metadata["usage"] = (
            response.usage_metadata.model_dump()
            if hasattr(response, "usage_metadata")
            else {}
        )
        metadata["finish_reason"] = (
            response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        )
        metadata["status"] = "success"

        try:
            raw_data = (
                response.parsed
                if response.parsed is not None
                else json.loads(response.text)
            )
            bundles = []
            for b_data in raw_data:
                for item in b_data.get("items", []):
                    item["video_timestamp"] = 0.0
                    item.setdefault("timestamp_label", "")
                bundles.append(RoomBundle(**b_data))
            return bundles, metadata
        except Exception as exc:
            logger.error(f"Failed to parse frames response: {exc}")
            raise
