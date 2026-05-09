from typing import Any

from app.ai.client import MODEL_ID, SYSTEM_INSTRUCTION, create_client
from app.ai.extraction import ExtractionService
from app.ai.pricing import PricingService
from app.models.inventory import RoomBundle


class GeminiProcessor:
    """
    Thin facade that wires ExtractionService and PricingService together and
    exposes the original public API used by pipelines.py.
    """

    def __init__(self, project_id: str):
        client = create_client(project_id)
        self._extraction = ExtractionService(client, MODEL_ID, SYSTEM_INSTRUCTION)
        self._pricing = PricingService(client, MODEL_ID, SYSTEM_INSTRUCTION)

    async def process_walkthrough(
        self, gcs_uri: str
    ) -> tuple[list[RoomBundle], dict[str, Any]]:
        return await self._extraction.process_walkthrough(gcs_uri)

    async def estimate_listing_prices(
        self, items: list[dict[str, Any]], move_out_date: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return await self._pricing.estimate_listing_prices(items, move_out_date)
