"""Claude-vision based label field extraction.

Uses forced tool-use so the model returns structured JSON directly instead
of free text we'd have to parse ourselves.
"""

import base64
import os
import time

from anthropic import Anthropic, AnthropicVertex

from models import ExtractedLabel

EXTRACTION_TOOL = {
    "name": "record_label_fields",
    "description": "Record the fields read directly off the alcohol beverage label image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand_name": {
                "type": "string",
                "description": "Brand name exactly as printed on the label.",
            },
            "class_type": {
                "type": "string",
                "description": "Class/type designation exactly as printed, e.g. 'Kentucky Straight Bourbon Whiskey'.",
            },
            "alcohol_content": {
                "type": "string",
                "description": (
                    "Alcohol content exactly as printed, including units/proof, "
                    "e.g. '45% Alc./Vol. (90 Proof)'. Empty string if absent."
                ),
            },
            "net_contents": {
                "type": "string",
                "description": "Net contents exactly as printed, e.g. '750 mL'.",
            },
            "warning_statement_text": {
                "type": "string",
                "description": (
                    "The full government warning statement, verbatim including "
                    "punctuation. MUST start with the 'GOVERNMENT WARNING:' (or "
                    "similar) heading itself, not just the body text that "
                    "follows it -- include the heading as the first words of "
                    "this string. Empty string if no warning statement appears "
                    "on the label."
                ),
            },
            "warning_heading_is_caps_bold": {
                "type": "boolean",
                "description": (
                    "True only if 'GOVERNMENT WARNING:' appears in all capital "
                    "letters AND in a bold/heavier weight than the surrounding "
                    "text. False otherwise, including when no warning statement "
                    "is present."
                ),
            },
            "notes": {
                "type": "string",
                "description": (
                    "Observations such as blur, glare, odd angle, or any field "
                    "that could not be read with confidence. Empty string if none."
                ),
            },
        },
        "required": [
            "brand_name",
            "class_type",
            "alcohol_content",
            "net_contents",
            "warning_statement_text",
            "warning_heading_is_caps_bold",
            "notes",
        ],
    },
}

_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return _MEDIA_TYPES.get(ext, "image/jpeg")


def get_client():
    """Direct Anthropic API by default; Vertex AI only if explicitly configured.

    Vertex was the original plan (see README), but Claude on Vertex requires
    Anthropic business-account approval that doesn't fit an individual
    prototype, so direct API is the primary path. GOOGLE_CLOUD_PROJECT is
    still supported here in case that access is granted later -- confirmed
    working values are region "global" and model "claude-sonnet-5" (no date
    suffix), found by testing against the live API rather than guessing.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        region = os.environ.get("GOOGLE_CLOUD_REGION", "global")
        model = os.environ.get("CLAUDE_MODEL_VERTEX", "claude-sonnet-5")
        return AnthropicVertex(project_id=project, region=region), model

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No credentials found. Set ANTHROPIC_API_KEY (direct Anthropic API) "
            "or GOOGLE_CLOUD_PROJECT (Vertex AI, if you have Anthropic business "
            "access approved) in the environment."
        )
    model = os.environ.get("CLAUDE_MODEL_API", "claude-sonnet-5")
    return Anthropic(api_key=api_key), model


def extract_label_fields(
    image_bytes: bytes, filename: str, client=None, model=None
) -> tuple[ExtractedLabel, float]:
    """Send a label image to Claude and return extracted fields plus call latency."""
    if client is None or model is None:
        client, model = get_client()

    encoded = base64.standard_b64encode(image_bytes).decode("utf-8")

    start = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_label_fields"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _media_type(filename),
                            "data": encoded,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a photo of an alcohol beverage label. Read the "
                            "fields directly off the label as printed -- do not "
                            "correct spelling, capitalization, or punctuation. "
                            "Record them with the record_label_fields tool."
                        ),
                    },
                ],
            }
        ],
    )
    latency = time.monotonic() - start

    tool_use = next(block for block in response.content if block.type == "tool_use")
    data = tool_use.input

    extracted = ExtractedLabel(
        brand_name=data["brand_name"],
        class_type=data["class_type"],
        alcohol_content=data["alcohol_content"],
        net_contents=data["net_contents"],
        warning_statement_text=data["warning_statement_text"],
        warning_heading_is_caps_bold=data["warning_heading_is_caps_bold"],
        notes=data.get("notes", ""),
    )
    return extracted, latency
