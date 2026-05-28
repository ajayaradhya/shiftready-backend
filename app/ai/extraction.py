import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.ai.schema_utils import get_clean_schema
from app.ai.schemas import SingleFrameResult, RefinementResult
from app.models.inventory import RoomBundle

logger = logging.getLogger(__name__)

_REFINEMENT_PROMPT = """You are organizing household items into bundles for a home relocation sale.

You receive a JSON array of items, each with: idx (index), name, brand, price, and name_source ("user" or "ai").

Your job:
1. GROUPING: Assign each item to exactly one bundle by functional category similarity.
   Examples: "Study & Office" (desk, monitor, books, lamp), "Artifacts & Decor" (vases, frames, sculptures),
   "Kitchen Gear" (appliances, cookware), "Bedding & Linens" (sheets, pillows, blankets),
   "Tech & Electronics" (TVs, speakers, cables), "Furniture — Seating" (sofas, chairs),
   "Furniture — Storage" (wardrobes, shelves). Use whichever bundle names best fit the items.
   Aim for 2–6 items per bundle. Single-item bundles are acceptable.
2. NAMES: When name_source is "user", treat that item's name as authoritative — do not rename or merge it.
3. COVERAGE: Every item index must appear in exactly one bundle. Do not drop any items.

Return bundle groupings only. Do not modify item names or prices.
"""

_SINGLE_FRAME_PROMPT = """You are analyzing a photo of a single household item for a home relocation sale.

Identify the main item and extract exactly four fields:
- name: descriptive common name (e.g. "Armchair", "Samsung 65\" TV", "Coffee Table")
- brand: visible brand or manufacturer; return "Unknown" if not determinable from the image
- predicted_original_price: estimated original retail price in AUD when purchased new
- confidence: your identification confidence level
  - "low": image is blurry, partially occluded, too dark, or multiple competing items make main item unclear
  - "medium": main category is clear but specific model, brand, or price is uncertain
  - "high": item is clearly visible, well-lit, and you can identify it with high certainty

Focus only on the primary item in the frame. Be concise and realistic with pricing.

Examples:
- Clear well-lit sofa with visible brand tag → confidence: "high"
- Blurry photo of what looks like a lamp → confidence: "low"
- Obviously a monitor but brand/size unclear → confidence: "medium"
"""

_SUGGEST_TITLE_PROMPT = """Generate a concise moving sale title for the ShiftReady marketplace.
Items: {item_names}

Rules:
- Max 60 characters
- No quotes around the result
- Format like: "12-item Newtown moving sale: study, kitchen & decor"
- Be specific about item categories
- Return ONLY the title string, nothing else"""


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

CATEGORY: Assign one of: furniture, appliance, electronics, decor, clothing, books_media,
sports_fitness, garden_outdoor, kitchen_dining, baby_kids, tools_hardware, toys_games,
lighting, storage, other.

Set 'timestamp_label' to "" (no video involved).
Do not generate 'id' fields.
"""

_PROMPT = """
Analyze this video and identify sellable items.
Organize items into Room Bundles (e.g., 'Living Room', 'Kitchen').

CATEGORY: Assign one of: furniture, appliance, electronics, decor, clothing, books_media,
sports_fitness, garden_outdoor, kitchen_dining, baby_kids, tools_hardware, toys_games,
lighting, storage, other.

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

    async def refine_captured_items(
        self, items: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        metadata: dict[str, Any] = {
            "model": self._model_id,
            "engine": "google-genai-sdk",
            "status": "processing",
            "item_count": len(items),
        }

        refinement_schema = get_clean_schema(RefinementResult)
        prompt = (
            f"{_REFINEMENT_PROMPT}\n\nItems:\n{json.dumps(items, ensure_ascii=False)}"
        )

        response = await self._client.aio.models.generate_content(
            model=self._model_id,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.1,
                system_instruction=self._system_instruction,
                response_mime_type="application/json",
                response_schema=types.Schema(**refinement_schema),
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
            parsed = (
                response.parsed
                if response.parsed is not None
                else json.loads(response.text)
            )
            if hasattr(parsed, "bundles"):
                bundles = [b.model_dump() for b in parsed.bundles]
            elif isinstance(parsed, dict):
                bundles = parsed.get("bundles", [])
            else:
                bundles = []
            logger.info(
                f"Refinement complete | {len(bundles)} bundles | items={len(items)}"
            )
            return bundles, metadata
        except Exception as exc:
            logger.error(f"Failed to parse refinement response: {exc}")
            raise

    async def identify_single_frame(self, gcs_uri: str) -> dict[str, Any]:
        schema = get_clean_schema(SingleFrameResult)

        response = await self._client.aio.models.generate_content(
            model=self._model_id,
            contents=[
                types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg"),
                _SINGLE_FRAME_PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                system_instruction=self._system_instruction,
                response_mime_type="application/json",
                response_schema=types.Schema(**schema),
            ),
        )

        usage = (
            response.usage_metadata.total_token_count
            if hasattr(response, "usage_metadata")
            else "n/a"
        )
        parsed = (
            response.parsed
            if response.parsed is not None
            else json.loads(response.text)
        )

        if hasattr(parsed, "model_dump"):
            result = parsed.model_dump()
        elif isinstance(parsed, dict):
            result = parsed
        else:
            result = {
                "name": str(parsed),
                "brand": "Unknown",
                "predicted_original_price": 0.0,
            }

        result.setdefault("confidence", "medium")
        logger.info(
            f"Single frame identified | name={result.get('name')} | confidence={result.get('confidence')} | tokens={usage}"
        )
        return result

    async def suggest_sale_title(self, item_names: list[str]) -> str:
        prompt = _SUGGEST_TITLE_PROMPT.format(item_names=", ".join(item_names[:20]))
        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self._model,
            contents=prompt,
        )
        title = (response.text or "").strip().strip('"').strip("'")
        usage = (
            response.usage_metadata.total_token_count
            if hasattr(response, "usage_metadata")
            else "n/a"
        )
        logger.info(f"Sale title suggested | title={title!r} | tokens={usage}")
        return title
