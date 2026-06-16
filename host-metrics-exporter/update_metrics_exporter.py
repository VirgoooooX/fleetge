#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-shot script: update the host-metrics-exporter stack on all configured hosts.

Connects to each host's Dockge instance via Socket.IO, finds the stack whose
name contains "metrics", and triggers updateStack (docker compose pull + up -d).

Usage:
  python update_metrics_exporter.py
"""

import asyncio
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid UnicodeEncodeError
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import yaml
import socketio


def load_hosts() -> list[dict]:
    """Parse data/hosts.yaml, returning enabled hosts with plaintext credentials."""
    hosts_path = Path(__file__).resolve().parent.parent / "data" / "hosts.yaml"
    if not hosts_path.exists():
        print(f"ERROR: hosts.yaml not found at {hosts_path}")
        sys.exit(1)

    with open(hosts_path, "r") as f:
        data = yaml.safe_load(f)

    result = []
    for entry in data.get("hosts", []):
        if not entry.get("enabled", True):
            continue
        dockge = entry.get("dockge", {})
        if not dockge.get("url"):
            continue
        result.append({
            "host_id": entry["host_id"],
            "display_name": entry.get("display_name", entry["host_id"]),
            "dockge_url": dockge["url"].rstrip("/"),
            "dockge_username": dockge.get("username", ""),
            "dockge_password": dockge.get("password", ""),
        })
    return result


async def update_one_host(host: dict) -> bool:
    """Connect to one host's Dockge, find the metrics stack, and update it."""
    host_id = host["host_id"]
    sio = socketio.AsyncClient()

    try:
        # ── Connect ──────────────────────────────────────────────
        await asyncio.wait_for(
            sio.connect(
                host["dockge_url"],
                socketio_path="/socket.io",
                transports=["websocket", "polling"],
            ),
            timeout=15.0,
        )

        # ── Login ────────────────────────────────────────────────
        auth = await sio.call(
            "login",
            {"username": host["dockge_username"], "password": host["dockge_password"]},
            timeout=15,
        )
        if not auth or not auth.get("ok"):
            print(f"  [{host_id}] ❌ Dockge login failed: {auth}")
            return False

        # ── List stacks ──────────────────────────────────────────
        future: asyncio.Future = asyncio.get_running_loop().create_future()

        def on_agent(event_name, *args):
            if event_name == "stackList" and not future.done():
                data = args[0] if args else {}
                stacks = []
                if isinstance(data, dict):
                    raw = data.get("stackList") or data.get("stacks") or data.get("data") or {}
                    if isinstance(raw, dict):
                        for name, sdata in raw.items():
                            entry = sdata if isinstance(sdata, dict) else {}
                            entry.setdefault("name", name)
                            stacks.append(entry)
                    elif isinstance(raw, list):
                        stacks = raw
                future.set_result(stacks)

        sio.on("agent", on_agent)
        await sio.call("agent", ("", "requestStackList"), timeout=10)
        stacks = await asyncio.wait_for(future, timeout=10.0)

        # ── Find the metrics exporter stack ─────────────────────
        metrics_stack = None
        for s in stacks:
            name = (s.get("name") or "").lower()
            if "metric" in name or "exporter" in name:
                metrics_stack = s.get("name")
                break

        if not metrics_stack:
            print(f"  [{host_id}] ⚠ No metrics/exporter stack found in {[s.get('name') for s in stacks]}")
            return False

        # ── Update the stack ────────────────────────────────────
        print(f"  [{host_id}] Updating stack '{metrics_stack}' ...")
        result = await sio.call("agent", ("", "updateStack", metrics_stack), timeout=120)
        print(f"  [{host_id}] ✅ Updated '{metrics_stack}': {result}")
        return True

    except asyncio.TimeoutError:
        print(f"  [{host_id}] ❌ Connection timed out")
        return False
    except Exception as exc:
        print(f"  [{host_id}] ❌ Error: {exc}")
        return False
    finally:
        try:
            await sio.disconnect()
        except Exception:
            pass


async def main():
    hosts = load_hosts()
    print(f"Found {len(hosts)} enabled host(s) with Dockge configured.\n")

    results = {}
    for host in hosts:
        print(f"▶ {host['display_name']} ({host['host_id']}) — {host['dockge_url']}")
        ok = await update_one_host(host)
        results[host["host_id"]] = ok
        print()

    # ── Summary ──────────────────────────────────────────────────
    ok = sum(1 for v in results.values() if v)
    fail = len(results) - ok
    print(f"Done: {ok} succeeded, {fail} failed")


if __name__ == "__main__":
    asyncio.run(main())
