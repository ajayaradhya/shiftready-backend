from google import genai

MODEL_ID = "gemini-3.1-flash-lite-preview"

SYSTEM_INSTRUCTION = (
    "You are the ShiftReady Relocation Agent. You specialize in the Sydney 2026 "
    "resale market (Waterloo, Zetland, Alexandria, and Surry Hills). "
    "Your goal is to ensure items are sold at maximum fair value before the "
    "user's move-out deadline. Be precise, realistic, and market-aware."
)


def create_client(project_id: str) -> genai.Client:
    return genai.Client(vertexai=True, project=project_id, location="global")
