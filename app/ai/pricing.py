import json
import logging
from datetime import datetime
from typing import Any

from google import genai
from google.genai import types

from app.ai.schemas import PricingList
from app.ai.schema_utils import get_clean_schema

logger = logging.getLogger(__name__)


class PricingService:
    def __init__(self, client: genai.Client, model_id: str, system_instruction: str):
        self._client = client
        self._model_id = model_id
        self._system_instruction = system_instruction

    async def estimate_listing_prices(
        self, items: list[dict[str, Any]], move_out_date: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        metadata: dict[str, Any] = {
            "model": self._model_id,
            "engine": "google-genai-sdk",
            "status": "processing",
        }

        try:
            deadline = datetime.strptime(move_out_date, "%Y-%m-%d")
            days_remaining = (deadline - datetime.now()).days
        except (ValueError, TypeError):
            days_remaining = 14

        if days_remaining <= 3:
            urgency_multiplier = 0.6
        elif days_remaining <= 7:
            urgency_multiplier = 0.8
        else:
            urgency_multiplier = 1.0

        prompt = (
            f"Analyze the following inventory for a move in Sydney.\n"
            f"Current Date: {datetime.now().strftime('%Y-%m-%d')}\n"
            f"Move-out Deadline: {move_out_date} ({days_remaining} days left)\n"
            f"Apply a {int((1 - urgency_multiplier) * 100)}% Urgency Discount.\n\n"
            f"INVENTORY DATA:\n{json.dumps(items, indent=2)}"
        )

        try:
            pricing_schema = get_clean_schema(PricingList, is_pricing=True)

            response = await self._client.aio.models.generate_content(
                model=self._model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    system_instruction=self._system_instruction,
                    response_mime_type="application/json",
                    response_schema=types.Schema(**pricing_schema),
                ),
            )

            metadata["usage"] = (
                response.usage_metadata.model_dump()
                if hasattr(response, "usage_metadata")
                else {}
            )

            parsed = (
                response.parsed
                if hasattr(response, "parsed")
                else json.loads(response.text)
            )

            if hasattr(parsed, "results"):
                results = [
                    r.model_dump() if hasattr(r, "model_dump") else dict(r)
                    for r in parsed.results
                ]
            else:
                results = (
                    parsed.get("results", []) if isinstance(parsed, dict) else []
                )

            metadata.update({"days_remaining": days_remaining, "status": "success"})
            return results, metadata

        except Exception as exc:
            logger.error(f"Pricing pipeline error: {exc}")
            return [], metadata
