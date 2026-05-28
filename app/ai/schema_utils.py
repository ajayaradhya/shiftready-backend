from typing import Any


def get_clean_schema(model, *, is_pricing: bool = False) -> dict[str, Any]:
    """
    Converts a Pydantic model to a Gemini-compatible JSON schema.

    Gemini's structured-output API rejects:
      - $ref pointers  →  inlined recursively from $defs
      - anyOf with null →  collapsed to the non-null branch
      - backend-managed fields (actual_* prices, ids)  →  stripped
    """
    schema = model.model_json_schema()

    # 1. Inline all $ref definitions so the schema is self-contained
    if "$defs" in schema:
        definitions = schema.pop("$defs")

        def inline_refs(obj: Any) -> Any:
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref_name = obj["$ref"].split("/")[-1]
                    return inline_refs(definitions[ref_name])
                return {k: inline_refs(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [inline_refs(i) for i in obj]
            return obj

        schema = inline_refs(schema)

    # 2. Strip null branches and backend-owned fields
    _BACKEND_FIELDS = {
        "actual_original_price",
        "actual_year_of_purchase",
        "actual_listing_price",
        "pricing_reasoning",
    }
    _AI_FORBIDDEN = {"id", "listing_price"} if not is_pricing else set()

    forbidden = _BACKEND_FIELDS | _AI_FORBIDDEN

    def clean_node(obj: Any) -> Any:
        if isinstance(obj, dict):
            if "anyOf" in obj:
                non_null = [t for t in obj["anyOf"] if t.get("type") != "null"]
                if non_null:
                    return clean_node(non_null[0])
            return {k: clean_node(v) for k, v in obj.items() if k not in forbidden}
        if isinstance(obj, list):
            return [clean_node(i) for i in obj]
        return obj

    return clean_node(schema)
