from __future__ import annotations

import base64
from io import BytesIO

from app.config import (
    VISION_MAX_BYTES,
    VISION_MIN_PIXELS,
    VISION_MIN_SIDE,
    anthropic_api_key,
)
from app.http_client import PoliteClient
from app.llm import BillingError, complete, is_billing_error


class VisionUnavailable(RuntimeError):
    """Stop further vision calls this run (billing, auth, etc.)."""


VISION_PROMPT = (
    "Describe this support-article screenshot so it can be searched later. "
    "Name visible UI labels, buttons, menus, fields, and the action shown. "
    "If the image is decorative, a logo, unreadable, or you are not sure, "
    "start the reply with UNSURE and say why. Plain text only."
)


def _media_type(content_type: str, url: str) -> str | None:
    raw = (content_type or "").split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": "image/jpeg",
        "image/jpg": "image/jpeg",
        "image/png": "image/png",
        "image/gif": "image/gif",
        "image/webp": "image/webp",
    }
    if raw in mapping:
        return mapping[raw]
    lower = url.lower()
    if ".png" in lower:
        return "image/png"
    if ".jpg" in lower or ".jpeg" in lower:
        return "image/jpeg"
    if ".gif" in lower:
        return "image/gif"
    if ".webp" in lower:
        return "image/webp"
    return None


def image_is_tiny(data: bytes) -> bool:
    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as img:
            width, height = img.size
        if min(width, height) < VISION_MIN_SIDE:
            return True
        if width * height < VISION_MIN_PIXELS:
            return True
        return False
    except Exception:
        return False


def describe_image(
    client: PoliteClient,
    db_conn,
    image_url: str,
    *,
    model: str = "claude-haiku-5-5",
) -> tuple[str, str]:
    """Return (description, status) where status is ok|unsure|failed|skipped_tiny."""
    key = anthropic_api_key()
    if not key:
        return (
            f"Image at {image_url}. Vision skipped because ANTHROPIC_API_KEY is not set.",
            "failed",
        )

    try:
        response = client.get_bytes(image_url)
        media_type = _media_type(response.headers.get("content-type", ""), image_url)
        data = response.content
        if not media_type:
            raise ValueError("unsupported image type")
        if len(data) > VISION_MAX_BYTES:
            raise ValueError("image exceeds size cap")
        if image_is_tiny(data):
            return (
                f"Screenshot skipped: tiny icon or decorative asset. Source image: {image_url}",
                "skipped_tiny",
            )

        result = complete(
            db_conn,
            "vision",
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(data).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": VISION_PROMPT},
                    ],
                }
            ],
            max_tokens=400,
            model=model,
        )
        text = result.text or "UNSURE: empty vision response."
        unsure = text.upper().startswith("UNSURE")
        note = "" if not unsure else " Note: description marked unsure."
        description = f"Screenshot from article. {text}{note}\nSource image: {image_url}"
        return description, "unsure" if unsure else "ok"
    except BillingError as exc:
        raise VisionUnavailable(str(exc)) from exc
    except Exception as exc:
        error = str(exc)
        description = (
            f"Screenshot from article. UNSURE: vision failed ({error}). "
            f"Source image: {image_url}"
        )
        if is_billing_error(error):
            raise VisionUnavailable(error) from exc
        return description, "failed"
