"""Check the running agent through its normal authenticated health route."""

import os
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler


def main() -> int:
    host = os.environ.get("AGENT_BIND_HOST", "0.0.0.0")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = os.environ.get("PORT", "8080")
    prefix = os.environ.get("AGENT_SECRET_PATH", "").strip().strip("/")
    path = f"/{prefix}/api/agent/health" if prefix else "/api/agent/health"
    token = os.environ.get("AGENT_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = Request(f"http://{host}:{port}{path}", headers=headers)
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except (OSError, URLError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
