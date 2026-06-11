from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
from pathlib import PurePosixPath
from typing import Any, TypeGuard
from urllib.parse import unquote, unquote_to_bytes, urlparse

from curl_cffi import requests
from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from services.proxy_service import proxy_settings

ImageInput = tuple[bytes, str, str]
ImageSource = str | UploadFile | ImageInput

MAX_IMAGE_REFERENCE_BYTES = 50 * 1024 * 1024
IMAGE_REFERENCE_FIELDS = {"image", "image[]", "images", "images[]", "image_url", "image_url[]"}


def _clean(value: object, default: str = "") -> str:
    """Clean a string: convert to str and strip leading/trailing whitespace."""
    text = str(value if value is not None else default).strip()
    return text or default


def _is_upload(value: object) -> TypeGuard[UploadFile]:
    """Detect an uploaded file: compatible with the UploadFile returned by Starlette forms."""
    return isinstance(value, UploadFile)


def _parse_bool(value: object) -> bool | None:
    """Parse a boolean field: compatible with JSON booleans and form strings."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = _clean(value).lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    raise HTTPException(status_code=400, detail={"error": "stream must be a boolean"})


def _parse_count(value: object) -> int:
    """Parse the generation count: keep the image API's 1 to 4 limit."""
    try:
        count = int(value or 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"error": "n must be an integer"}) from exc
    if count < 1 or count > 4:
        raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})
    return count


def _payload_from_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Build the image-edit payload: extract common params from form or JSON fields."""
    prompt = _clean(fields.get("prompt"))
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt is required"})
    payload = {
        "prompt": prompt,
        "model": _clean(fields.get("model"), "gpt-image-2"),
        "n": _parse_count(fields.get("n")),
        "size": _clean(fields.get("size")) or None,
        "quality": _clean(fields.get("quality"), "auto"),
        "response_format": _clean(fields.get("response_format"), "b64_json"),
        "stream": _parse_bool(fields.get("stream")),
    }
    if "client_task_id" in fields:
        payload["client_task_id"] = _clean(fields.get("client_task_id"))
    return payload


def _json_reference_value(value: object) -> object:
    """Parse form image references: supports passing the images field as a JSON string."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _decode_base64_image(value: object, filename: str, mime_type: str) -> ImageInput:
    try:
        data = base64.b64decode(str(value).strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid base64 image data"}) from exc
    if not data:
        raise HTTPException(status_code=400, detail={"error": "image file is empty"})
    if len(data) > MAX_IMAGE_REFERENCE_BYTES:
        raise HTTPException(status_code=400, detail={"error": "image URL exceeds 50MB limit"})
    return data, filename, mime_type


def _source_from_object(value: dict[str, Any]) -> list[ImageSource]:
    """Extract an image reference object: supports image_url or url, explicitly rejects file_id."""
    has_url = "image_url" in value or "url" in value
    if value.get("file_id"):
        raise HTTPException(
            status_code=400,
            detail={"error": "file_id image references are not supported; use image_url instead"},
        )
    inline = value.get("b64_json") or value.get("base64")
    if inline:
        filename = _clean(value.get("filename") or value.get("file_name"), "image.png")
        mime_type = _clean(value.get("mime_type") or value.get("mimeType"), "image/png")
        return [_decode_base64_image(inline, filename, mime_type)]
    if not has_url:
        raise HTTPException(status_code=400, detail={"error": "image reference must include image_url"})
    image_url = value.get("image_url", value.get("url"))
    if isinstance(image_url, dict):
        image_url = image_url.get("url")
    return _sources_from_value(image_url)


def _sources_from_value(value: object) -> list[ImageSource]:
    """Expand image references: normalize strings, arrays and objects into a list of image sources."""
    value = _json_reference_value(value)
    if _is_upload(value):
        return [value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.lower().startswith(("data:", "http://", "https://")):
            return [text]
        return [_decode_base64_image(text, "image.png", "image/png")]
    if isinstance(value, list):
        sources: list[ImageSource] = []
        for item in value:
            sources.extend(_sources_from_value(item))
        return sources
    if isinstance(value, dict):
        return _source_from_object(value)
    if value is None:
        return []
    raise HTTPException(status_code=400, detail={"error": "invalid image reference"})


def _json_image_sources(body: dict[str, Any]) -> list[ImageSource]:
    """Read JSON image references: prefers the official images array field."""
    sources: list[ImageSource] = []
    for key in ("images", "image", "image_url"):
        if key in body:
            sources.extend(_sources_from_value(body.get(key)))
    return sources


async def parse_image_edit_request(request: Request) -> tuple[dict[str, Any], list[ImageSource]]:
    """Parse an image-edit request: supports both multipart uploads and official JSON image URLs."""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail={"error": "invalid JSON body"}) from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail={"error": "JSON body must be an object"})
        return _payload_from_fields(body), _json_image_sources(body)

    form = await request.form()
    fields: dict[str, Any] = {}
    for key in ("client_task_id", "prompt", "model", "n", "size", "quality", "response_format", "stream"):
        value = form.get(key)
        if isinstance(value, str):
            fields[key] = value
    sources: list[ImageSource] = []
    for key, value in form.multi_items():
        if key in IMAGE_REFERENCE_FIELDS:
            sources.extend(_sources_from_value(value))
    return _payload_from_fields(fields), sources


def _extension_from_mime(mime_type: str) -> str:
    """Derive an image extension: convert the MIME type into a common file suffix."""
    subtype = mime_type.split("/", 1)[1].split("+", 1)[0] if "/" in mime_type else "png"
    if subtype == "jpeg":
        return "jpg"
    return re.sub(r"[^a-z0-9]+", "", subtype.lower()) or "png"


def _safe_filename(name: str, mime_type: str, fallback: str) -> str:
    """Build a safe filename: sanitize the URL filename and append an extension."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not cleaned:
        cleaned = fallback
    if "." not in cleaned:
        cleaned = f"{cleaned}.{_extension_from_mime(mime_type)}"
    return cleaned


def _decode_data_url(url: str) -> ImageInput:
    """Decode a data URL: convert an inline image into a standard image-input tuple."""
    header, separator, payload = url.partition(",")
    if not separator:
        raise HTTPException(status_code=400, detail={"error": "invalid data image URL"})
    mime_type = header.split(";", 1)[0].removeprefix("data:") or "image/png"
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail={"error": "image_url must point to an image"})
    try:
        data = base64.b64decode(payload, validate=True) if ";base64" in header else unquote_to_bytes(payload)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid data image URL"}) from exc
    if not data:
        raise HTTPException(status_code=400, detail={"error": "image URL is empty"})
    if len(data) > MAX_IMAGE_REFERENCE_BYTES:
        raise HTTPException(status_code=400, detail={"error": "image URL exceeds 50MB limit"})
    return data, f"image_url.{_extension_from_mime(mime_type)}", mime_type


def _response_mime_type(response: requests.Response, parsed_path: str) -> str:
    """Detect a downloaded image's type: prefer the response headers, fall back to the URL suffix."""
    header_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    guessed_type = mimetypes.guess_type(parsed_path)[0] or ""
    if header_type.startswith("image/"):
        return header_type
    if header_type and header_type not in {"application/octet-stream", "binary/octet-stream"}:
        raise HTTPException(status_code=400, detail={"error": "image_url must point to an image"})
    if guessed_type.startswith("image/"):
        return guessed_type
    if not header_type or header_type in {"application/octet-stream", "binary/octet-stream"}:
        return "image/png"
    raise HTTPException(status_code=400, detail={"error": "image_url must point to an image"})


def _filename_from_url(parsed_path: str, mime_type: str) -> str:
    """Build a filename for a URL image: extract the name from the link path and sanitize it."""
    raw_name = PurePosixPath(unquote(parsed_path)).name
    return _safe_filename(raw_name, mime_type, "image_url")


def _download_image_url(url: str) -> ImageInput:
    """Download a remote image: convert an http/https image link into a standard image-input tuple."""
    source = _clean(url)
    if source.startswith("data:"):
        return _decode_data_url(source)
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail={"error": "image_url must be an http or https URL"})
    try:
        response = requests.get(
            source,
            headers={"Accept": "image/*,*/*;q=0.8", "User-Agent": "chatgpt2api image fetcher"},
            timeout=60,
            allow_redirects=True,
            **proxy_settings.build_session_kwargs(),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": f"image_url fetch failed: {exc}"}) from exc
    if not 200 <= response.status_code < 300:
        raise HTTPException(status_code=400, detail={"error": f"image_url fetch failed: HTTP {response.status_code}"})
    content_length = _clean(response.headers.get("content-length"))
    if content_length and content_length.isdigit() and int(content_length) > MAX_IMAGE_REFERENCE_BYTES:
        raise HTTPException(status_code=400, detail={"error": "image_url exceeds 50MB limit"})
    data = response.content
    if not data:
        raise HTTPException(status_code=400, detail={"error": "image_url returned empty content"})
    if len(data) > MAX_IMAGE_REFERENCE_BYTES:
        raise HTTPException(status_code=400, detail={"error": "image_url exceeds 50MB limit"})
    mime_type = _response_mime_type(response, parsed.path)
    return data, _filename_from_url(parsed.path, mime_type), mime_type


async def read_image_sources(sources: list[ImageSource]) -> list[ImageInput]:
    """Read image sources: read uploaded files directly, download URLs, and return image tuples uniformly."""
    images: list[ImageInput] = []
    for source in sources:
        if isinstance(source, tuple):
            images.append(source)
            continue
        if _is_upload(source):
            try:
                image_data = await source.read()
            finally:
                await source.close()
            if not image_data:
                raise HTTPException(status_code=400, detail={"error": "image file is empty"})
            images.append((image_data, source.filename or "image.png", source.content_type or "image/png"))
            continue
        images.append(await run_in_threadpool(_download_image_url, source))
    if not images:
        raise HTTPException(status_code=400, detail={"error": "image file or image_url is required"})
    return images
