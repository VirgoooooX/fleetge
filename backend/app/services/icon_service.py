"""Stack icon directory resolution, URL helpers, wildcard matching, and SVG sanitization."""

from __future__ import annotations

import os
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote
from xml.etree import ElementTree

from app.config import get_settings

ALLOWED_ICON_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")
MAX_ICON_BYTES = 2 * 1024 * 1024

_FORBIDDEN_SVG_TAGS = frozenset({
    "script",
    "foreignobject",
    "iframe",
    "object",
    "embed",
    "animate",
    "animatemotion",
    "animatetransform",
    "set",
    "handler",
    "listener",
})


def get_stack_icons_dir(*, create: bool = True) -> Path:
    """Resolve stack_icons directory dynamically from current settings."""
    host_config_path = Path(get_settings().HOST_CONFIG_PATH).expanduser()
    if not host_config_path.is_absolute():
        host_config_path = Path.cwd() / host_config_path
    icons_dir = host_config_path.parent / "stack_icons"
    if create:
        icons_dir.mkdir(parents=True, exist_ok=True)
    return icons_dir


def list_available_icon_files() -> list[str]:
    """Return sorted list of valid icon filenames in stack_icons."""
    icons_dir = get_stack_icons_dir(create=False)
    files: list[str] = []
    if icons_dir.exists() and icons_dir.is_dir():
        for entry in os.scandir(icons_dir):
            if entry.is_file() and entry.name.lower().endswith(ALLOWED_ICON_EXTENSIONS):
                files.append(entry.name)
    files.sort()
    return files


def resolve_icon_url(icon_value: Any) -> Optional[str]:
    """Normalize an icon value (http/https URL, path, or local filename) into a URL."""
    if not isinstance(icon_value, str):
        return None
    val = icon_value.strip()
    if not val:
        return None
    if val.startswith(("http://", "https://", "/")):
        return val
    return f"/api/static/icons/{val.lstrip('/')}"


def match_wildcard_rule(name: str, rules: dict[str, Any]) -> Any:
    """Match a stack/service name against exact or glob patterns (most specific first)."""
    if not name or not rules:
        return None
    if name in rules:
        return rules[name]
    lower = name.lower()
    for pattern, value in rules.items():
        if pattern.lower() == lower:
            return value
    wildcard_patterns = [p for p in rules.keys() if "*" in p or "?" in p]
    wildcard_patterns.sort(key=lambda s: len(s.replace("*", "").replace("?", "")), reverse=True)
    for pattern in wildcard_patterns:
        if fnmatch(lower, pattern.lower()):
            return rules[pattern]
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _is_unsafe_svg_ref(value: str) -> bool:
    cleaned = unquote(value or "").strip().lower()
    if not cleaned:
        return False
    if cleaned.startswith("#"):
        return False
    if cleaned.startswith(("javascript:", "vbscript:", "data:text/html", "data:application/")):
        return True
    if cleaned.startswith(("http://", "https://", "//", "file:")):
        return True
    return False


def sanitize_svg_bytes(raw: bytes) -> bytes:
    """Parse and sanitize SVG bytes, stripping scripts, event handlers, and external refs."""
    if not raw or not raw.strip():
        raise ValueError("Empty SVG file")

    upper_head = raw.upper()
    if b"<!ENTITY" in upper_head or re.search(br"<!DOCTYPE[^>]*\[", raw, re.IGNORECASE):
        raise ValueError("External SVG DTD entities are not allowed")

    cleaned_raw = re.sub(br"<!DOCTYPE[^>\[]*>", b"", raw, flags=re.IGNORECASE)
    try:
        root = ElementTree.fromstring(cleaned_raw)
    except ElementTree.ParseError as exc:
        raise ValueError("Malformed SVG XML") from exc

    if _local_name(root.tag) != "svg":
        raise ValueError("Uploaded SVG root element must be <svg>")

    def _clean_element(el: ElementTree.Element) -> None:
        # Remove forbidden child elements
        for child in list(el):
            tag = _local_name(child.tag)
            if tag in _FORBIDDEN_SVG_TAGS:
                el.remove(child)
                continue
            _clean_element(child)

        # Clean attributes on current element
        for attr_name in list(el.attrib.keys()):
            local_attr = _local_name(attr_name)
            attr_val = el.attrib[attr_name]
            if local_attr.startswith("on"):
                del el.attrib[attr_name]
                continue
            if local_attr in {"href", "src", "action", "formaction"} and _is_unsafe_svg_ref(attr_val):
                del el.attrib[attr_name]
                continue
            if local_attr == "style" and (
                "javascript:" in attr_val.lower()
                or "expression(" in attr_val.lower()
                or re.search(r"url\(\s*['\"]?(?:https?:|//|javascript:)", attr_val, re.IGNORECASE)
            ):
                del el.attrib[attr_name]
                continue
            if any(
                re.search(r"url\(\s*['\"]?(?:https?:|//|javascript:)", attr_val, re.IGNORECASE)
                for _ in (0,)
            ):
                del el.attrib[attr_name]

    _clean_element(root)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=False)
