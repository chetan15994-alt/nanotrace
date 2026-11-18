"""Multi-Modal Payload Inspector and Media Parser for NanoTrace.

Detects, sanitizes, and extracts image, audio, and document payloads from LLM traces.
Prevents massive base64 text dumps from breaking UI scrolling while providing
rich inline thumbnails, lightbox viewing, and offline capsule embedding.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# Regex to match data URIs: data:<mime_type>;base64,<payload>
DATA_URI_PATTERN = re.compile(
    r'(data:(image/[a-zA-Z0-9\+\-\.]+|audio/[a-zA-Z0-9\+\-\.]+|application/pdf);base64,([A-Za-z0-9+/=]+))',
    re.IGNORECASE
)

# Regex to match image and media URLs
IMAGE_URL_PATTERN = re.compile(
    r'(https?://[^\s"\'<>]+\.(?:png|jpg|jpeg|webp|gif|svg)(?:\?[^\s"\'<>]*)?)',
    re.IGNORECASE
)

AUDIO_URL_PATTERN = re.compile(
    r'(https?://[^\s"\'<>]+\.(?:mp3|wav|ogg|m4a)(?:\?[^\s"\'<>]*)?)',
    re.IGNORECASE
)


def detect_media(text: str) -> List[Dict[str, Any]]:
    """Scan text payload for data URIs, image URLs, and audio references."""
    if not text or not isinstance(text, str):
        return []

    media_items: List[Dict[str, Any]] = []

    # 1. Match Data URIs
    for match in DATA_URI_PATTERN.finditer(text):
        full_uri = match.group(1)
        mime_type = match.group(2).lower()
        base64_data = match.group(3)
        size_bytes = int(len(base64_data) * 0.75)  # approximate byte length
        media_type = "image" if mime_type.startswith("image/") else ("audio" if mime_type.startswith("audio/") else "document")
        size_label = f"{size_bytes / 1024:.1f} KB" if size_bytes > 1024 else f"{size_bytes} B"

        media_items.append({
            "type": media_type,
            "mime_type": mime_type,
            "source": "data_uri",
            "url": full_uri,
            "size_bytes": size_bytes,
            "preview_label": f"{mime_type.split('/')[-1].upper()} {media_type.capitalize()} ({size_label})",
            "is_base64": True,
        })

    # 2. Match Image URLs
    for match in IMAGE_URL_PATTERN.finditer(text):
        url = match.group(1)
        # Avoid matching if already part of a data URI
        if "data:" in url:
            continue
        ext = url.split("?")[0].split(".")[-1].lower()
        media_items.append({
            "type": "image",
            "mime_type": f"image/{ext}",
            "source": "url",
            "url": url,
            "size_bytes": 0,
            "preview_label": f"Remote {ext.upper()} Image",
            "is_base64": False,
        })

    # 3. Match Audio URLs
    for match in AUDIO_URL_PATTERN.finditer(text):
        url = match.group(1)
        if "data:" in url:
            continue
        ext = url.split("?")[0].split(".")[-1].lower()
        media_items.append({
            "type": "audio",
            "mime_type": f"audio/{ext}",
            "source": "url",
            "url": url,
            "size_bytes": 0,
            "preview_label": f"Remote {ext.upper()} Audio",
            "is_base64": False,
        })

    return media_items


def sanitize_payload_for_display(payload: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Replace giant base64 image strings with sleek semantic badges for text views.
    
    Returns:
        (sanitized_text, list_of_media_items)
    """
    if not payload or not isinstance(payload, str):
        return "", []

    media_items = detect_media(payload)
    if not media_items:
        return payload, []

    # Replace each base64 data URI with a concise tag
    def repl(match: re.Match) -> str:
        mime = match.group(2)
        base64_data = match.group(3)
        size_kb = (len(base64_data) * 0.75) / 1024.0
        icon = "🖼️" if "image" in mime else ("🎵" if "audio" in mime else "📄")
        return f"[{icon} Embedded Media: {mime} ({size_kb:.1f} KB)]"

    sanitized = DATA_URI_PATTERN.sub(repl, payload)
    return sanitized, media_items


def scan_trace_multimodal_artifacts(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Scan all spans in a trace and aggregate a unified multi-modal media gallery."""
    gallery: List[Dict[str, Any]] = []

    for sp in spans:
        span_id = sp.get("span_id", "")
        span_name = sp.get("name", "span")

        # Scan prompt
        prompt = sp.get("prompt_payload") or ""
        p_media = detect_media(prompt)
        for m in p_media:
            gallery.append({
                **m,
                "span_id": span_id,
                "span_name": span_name,
                "role": "prompt",
            })

        # Scan completion
        completion = sp.get("completion_payload") or ""
        c_media = detect_media(completion)
        for m in c_media:
            gallery.append({
                **m,
                "span_id": span_id,
                "span_name": span_name,
                "role": "completion",
            })

    return gallery
