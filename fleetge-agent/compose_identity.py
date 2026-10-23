"""Resolve Compose services to the image identities currently available after pull."""

import json
import re
import subprocess
from typing import Sequence


def capture_pulled_images(
    stack_path: str, compose_config_args: Sequence[str], selected_services: Sequence[str] | None = None,
) -> list[dict]:
    """Return per-service image IDs, RepoDigests and platforms without logging env data."""
    try:
        config_result = subprocess.run(
            ["docker", *compose_config_args],
            cwd=stack_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Could not resolve the effective Compose service configuration: command timed out after 60 seconds.") from exc
    except Exception as exc:
        raise RuntimeError("Could not run docker compose config to resolve the service configuration.") from exc
    if config_result.returncode != 0:
        # Only expose bounded, redacted stderr. Resolved configuration stdout
        # contains environment values and must never appear in an error.
        detail = re.sub(
            r'''(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|SECRET|KEY|AUTH|CREDENTIAL)[A-Z0-9_]*\s*[=:]\s*)(?:"[^"]*"|'[^']*'|\S+)''',
            r"\1[REDACTED]", config_result.stderr or "",
        )
        detail = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", detail)
        detail = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", detail).strip()[:1500]
        raise RuntimeError(
            "Could not resolve the effective Compose service configuration "
            f"(docker compose config exit {config_result.returncode}): {detail or 'no error details returned'}"
        )
    try:
        config = json.loads(config_result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Docker Compose returned invalid JSON while resolving the service configuration.") from exc

    services = config.get("services") if isinstance(config, dict) else None
    if not isinstance(services, dict) or not services:
        raise RuntimeError("Compose configuration contains no services to verify.")

    if selected_services and any(name not in services for name in selected_services):
        raise RuntimeError("Requested service is missing from the effective Compose configuration.")
    pulled_images: list[dict] = []
    for service_name, service in services.items():
        if selected_services is not None and service_name not in selected_services:
            continue
        image = service.get("image") if isinstance(service, dict) else None
        if not isinstance(image, str) or not image.strip():
            raise RuntimeError(f"Compose service '{service_name}' has no effective image reference.")
        try:
            inspected = subprocess.run(
                ["docker", "image", "inspect", image],
                cwd=stack_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if inspected.returncode != 0:
                raise ValueError
            payload = json.loads(inspected.stdout)
            info = payload[0] if isinstance(payload, list) and payload else payload
            if not isinstance(info, dict) or not info.get("Id"):
                raise ValueError
        except Exception as exc:
            raise RuntimeError(f"Could not inspect the pulled image for Compose service '{service_name}'.") from exc

        platform_parts = (
            info.get("Os") or "",
            info.get("Architecture") or "",
            info.get("Variant") or "",
        )
        pulled_images.append({
            "service": str(service_name),
            "image": image,
            "image_id": str(info["Id"]),
            "repo_digests": [value for value in (info.get("RepoDigests") or []) if isinstance(value, str)],
            "platform": service.get("platform") or "/".join(part for part in platform_parts if part),
        })

    return pulled_images
