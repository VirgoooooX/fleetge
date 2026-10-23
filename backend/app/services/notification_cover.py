"""Fleetge notification covers, with one Stack or Host icon per message."""

import asyncio
import base64
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import httpx
import resvg_py

from app.config import get_settings

logger = logging.getLogger(__name__)
_BACKGROUND = Path(__file__).resolve().parents[1] / "assets" / "notifications" / "container-update.png"
_CATEGORIES = {
    "fleetge.stack.auto_update": ("container-update", "#f4f8f9"),
    "fleetge.host.billing_due": ("billing-due", "#fcf6ed"),
    "fleetge.host.traffic_quota": ("traffic-quota", "#f2effa"),
}
_MAX_ICON_BYTES = 2 * 1024 * 1024


def _vendor_logo_root() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "frontend_dist" / "vendor-logos"
    return bundled if bundled.is_dir() else Path(__file__).resolve().parents[3] / "frontend/public/vendor-logos"


def _host_logo_url(logo: str) -> str:
    value = logo.strip()
    if value.startswith(("http://", "https://", "/")):
        return value
    # Built-in preset keys use the same-named frontend asset. Reuse the files
    # instead of keeping a second vendor registry in the notification service.
    key = value.lower()
    if re.fullmatch(r"[a-z0-9-]+", key):
        for suffix in (".svg", ".png"):
            if (_vendor_logo_root() / f"{key}{suffix}").is_file():
                return f"/vendor-logos/{key}{suffix}"
    return f"/api/static/icons/{value}"


def _read_local_icon(url: str) -> bytes:
    if url.startswith("/vendor-logos/"):
        root = _vendor_logo_root()
        relative = url.removeprefix("/vendor-logos/")
    else:
        root = Path(get_settings().HOST_CONFIG_PATH).expanduser().resolve().parent / "stack_icons"
        relative = url.removeprefix("/api/static/icons/")
    target = (root / unquote(relative)).resolve()
    if root.resolve() not in target.parents:
        raise ValueError("Icon must stay in the configured Stack icon directory")
    with target.open("rb") as handle:
        data = handle.read(_MAX_ICON_BYTES + 1)
    if len(data) > _MAX_ICON_BYTES:
        raise ValueError("Stack icon exceeds 2 MiB")
    return data


async def _load_icon(client: httpx.AsyncClient, url: str) -> bytes:
    if url.startswith(("/api/static/icons/", "/vendor-logos/")):
        return await asyncio.to_thread(_read_local_icon, url)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Stack icon must use a configured local file or HTTP(S) URL")
    # These URLs come from the administrator's Stack configuration, including LAN icons.
    # Never forward Notify Hub credentials, cookies, or redirects to an icon host.
    async with client.stream("GET", url, follow_redirects=False, timeout=httpx.Timeout(5, connect=3)) as response:
        response.raise_for_status()
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > _MAX_ICON_BYTES:
                raise ValueError("Stack icon exceeds 2 MiB")
    return bytes(chunks)


def compose_cover(background: bytes, icon: bytes | None, background_color: str = "#f4f8f9") -> bytes:
    if not icon:
        return background
    stripped = icon.lstrip()
    if stripped.startswith((b"<", b"\xef\xbb\xbf<")):
        if b"<!ENTITY" in icon.upper() or re.search(br"<!DOCTYPE[^>]*\[", icon, re.IGNORECASE):
            raise ValueError("External SVG declarations are not allowed")
        # Some bundled logos carry the standard SVG 1.1 DOCTYPE. Discard the
        # declaration without resolving its external DTD; never accept entities.
        icon = re.sub(br"<!DOCTYPE[^>\[]*>", b"", icon, flags=re.IGNORECASE)
        root = ElementTree.fromstring(icon)
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise ValueError("Stack icon is not an SVG")
        for node in root.iter():
            for name, value in node.attrib.items():
                if name.rsplit("}", 1)[-1] == "href" and not value.startswith("#"):
                    raise ValueError("External SVG resources are not allowed")
            for value in [*node.attrib.values(), node.text or ""]:
                for reference in re.findall(r"url\((.*?)\)", value, re.IGNORECASE):
                    if not reference.strip(" \t\r\n\"'").startswith("#"):
                        raise ValueError("External SVG resources are not allowed")
        # Render separately at a bounded size; never resolve resources from the filesystem.
        icon = resvg_py.svg_to_bytes(svg_string=ElementTree.tostring(root, encoding="unicode"),
                                     width=136, height=136, skip_system_fonts=True)
        mime = "image/png"
    elif icon.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif icon.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif icon.startswith(b"GIF8"):
        mime = "image/gif"
    elif icon.startswith(b"RIFF") and icon[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("Unsupported Stack icon format")
    bg = base64.b64encode(background).decode("ascii")
    image = base64.b64encode(icon).decode("ascii")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1068" height="455">'
        f'<image href="data:image/png;base64,{bg}" width="1068" height="455"/>'
        f'<rect x="814" y="159" width="136" height="136" fill="{background_color}"/>'
        f'<image href="data:{mime};base64,{image}" x="814" y="159" width="136" height="136" preserveAspectRatio="xMidYMid meet"/>'
        '</svg>'
    )
    return resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)


async def prepare_notification(client: httpx.AsyncClient, base: str, api_key: str, payload: dict) -> dict:
    """Return a wire payload; legacy queued notifications keep their existing format."""
    if "_stack_icon" not in payload and "_host_icon" not in payload:
        return payload
    payload = dict(payload)
    stack_icon = payload.pop("_stack_icon", None)
    host_icon = payload.pop("_host_icon", None)
    icon_url = stack_icon or host_icon
    category, background_color = _CATEGORIES.get(payload.get("event_type"), ("container-update", "#f4f8f9"))
    try:
        background = await asyncio.to_thread((_BACKGROUND.parent / f"{category}.png").read_bytes)
        try:
            if host_icon and not stack_icon:
                icon_url = await asyncio.to_thread(_host_logo_url, host_icon)
            icon = await _load_icon(client, icon_url) if icon_url else None
            cover = await asyncio.to_thread(compose_cover, background, icon, background_color)
        except (OSError, ValueError, httpx.HTTPError, ElementTree.ParseError) as exc:
            logger.warning("Stack notification icon unavailable (%s); using Fleetge cover", type(exc).__name__)
            cover = background
        response = await client.post(
            base + "/api/v1/media", headers={"X-API-Key": api_key}, data={"kind": "image"},
            files={"file": (f"{category}.png", cover, "image/png")},
        )
        response.raise_for_status()
        asset_id = response.json().get("id")
        if not isinstance(asset_id, str) or not asset_id:
            raise ValueError("Notify Hub returned no cover ID")
        return {**payload, "message_type": "article", "media_asset_id": asset_id}
    except (OSError, ValueError, httpx.HTTPError) as exc:
        logger.warning("Stack notification cover unavailable (%s); sending text result", type(exc).__name__)
        return payload
