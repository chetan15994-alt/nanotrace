"""Testing Round 3: Multi-Modal Media Parsing, Sanitization & Gallery Scanning."""

import pytest
from nanotrace.media.multimodal import (
    detect_media,
    sanitize_payload_for_display,
    scan_trace_multimodal_artifacts,
)


def test_detect_media_base64_images():
    """Verify detection of data:image/png and data:image/jpeg base64 URIs."""
    # Small dummy 1x1 png base64
    fake_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    text = f"User asks: Can you inspect this receipt screenshot? [Image: {fake_png}]"

    items = detect_media(text)
    assert len(items) == 1
    assert items[0]["type"] == "image"
    assert items[0]["mime_type"] == "image/png"
    assert items[0]["source"] == "data_uri"
    assert items[0]["is_base64"] is True
    assert items[0]["size_bytes"] > 0
    assert "PNG" in items[0]["preview_label"]


def test_detect_media_image_and_audio_urls():
    """Verify detection of remote image and audio links in payloads."""
    text = (
        "Look at https://assets.example.com/charts/quarterly_arr.png and "
        "listen to https://audio.example.com/voicemail/memo_2026.mp3 for context."
    )
    items = detect_media(text)
    assert len(items) == 2

    types = {m["type"] for m in items}
    assert types == {"image", "audio"}

    img = next(m for m in items if m["type"] == "image")
    assert "quarterly_arr.png" in img["url"]
    assert img["is_base64"] is False

    aud = next(m for m in items if m["type"] == "audio")
    assert "memo_2026.mp3" in aud["url"]
    assert aud["is_base64"] is False


def test_sanitize_payload_for_display():
    """Verify that giant base64 image strings are replaced with concise badges for text views."""
    # Simulate an agent prompt with an embedded 10,000-char base64 payload
    long_b64 = "A" * 12_000
    huge_data_uri = f"data:image/webp;base64,{long_b64}"
    raw_payload = f"Prompt: Summarize the contents of this slide: {huge_data_uri}. Explain ROI."

    sanitized, media = sanitize_payload_for_display(raw_payload)
    assert len(media) == 1
    assert media[0]["mime_type"] == "image/webp"

    # Sanitized string must not contain the 12,000-character blob
    assert long_b64 not in sanitized
    assert "[🖼️ Embedded Media: image/webp" in sanitized
    assert "Explain ROI." in sanitized


def test_scan_trace_multimodal_artifacts():
    """Verify scanning all spans in a trace collects a consolidated media gallery."""
    spans = [
        {
            "span_id": "span_root",
            "name": "vision_agent",
            "prompt_payload": "Inspect input: data:image/jpeg;base64,/9j/4AAQSkZJRg==",
            "completion_payload": "I identified the invoice header.",
        },
        {
            "span_id": "span_tool",
            "name": "ocr_tool",
            "prompt_payload": "Running OCR on https://cdn.example.com/docs/invoice_99.png",
            "completion_payload": "Extracted text: Total due $450.00",
        },
    ]

    gallery = scan_trace_multimodal_artifacts(spans)
    assert len(gallery) == 2

    # First is from span_root prompt
    assert gallery[0]["span_id"] == "span_root"
    assert gallery[0]["role"] == "prompt"
    assert gallery[0]["mime_type"] == "image/jpeg"

    # Second is from span_tool prompt
    assert gallery[1]["span_id"] == "span_tool"
    assert gallery[1]["source"] == "url"
    assert "invoice_99.png" in gallery[1]["url"]


def test_detect_media_empty_or_non_string():
    """Verify safety when receiving None, empty strings, or non-string objects."""
    assert detect_media("") == []
    assert detect_media(None) == []
    assert detect_media(12345) == []
    sanitized, media = sanitize_payload_for_display(None)
    assert sanitized == ""
    assert media == []
