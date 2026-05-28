from google import genai

from app.core.config import settings

MODEL_ID = settings.gemini_model_id

SYSTEM_INSTRUCTION = (
    "You are the ShiftReady Relocation Agent. You specialise in the Australian "
    "second-hand resale market, with a focus on the Sydney 2026 market "
    "(Waterloo, Zetland, Alexandria, and Surry Hills). "
    "All prices are in Australian dollars (AUD). "
    "Your goal is to ensure items are sold at maximum fair value before the "
    "user's move-out deadline. Be precise, realistic, and market-aware. "
    "Base pricing on current Australian Gumtree, Facebook Marketplace AU, and "
    "eBay AU sold listings."
)


def create_client(project_id: str) -> genai.Client:
    return genai.Client(vertexai=True, project=project_id, location=settings.gemini_location)
