import asyncio
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services import notification_cover as module


class NotificationCoverTests(unittest.TestCase):
    def test_host_presets_reuse_existing_vendor_assets_and_accept_custom_icons(self):
        background = module._BACKGROUND.read_bytes()
        for key in ["istoreos", "zspace", "oracle", "cloudcone", "zgocloud", "lightlayer"]:
            with self.subTest(key=key):
                url = module._host_logo_url(key.upper())
                self.assertTrue(url.startswith("/vendor-logos/"))
                cover = module.compose_cover(background, module._read_local_icon(url))
                self.assertEqual(cover[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(module._host_logo_url("https://icons.test/host.png"), "https://icons.test/host.png")
        self.assertEqual(module._host_logo_url("custom.png"), "/api/static/icons/custom.png")
        with self.assertRaises(ValueError):
            module._read_local_icon("/vendor-logos/%2e%2e/private.png")

    def test_svg_stack_icon_composes_and_rejects_external_resources(self):
        background = module._BACKGROUND.read_bytes()
        cover = module.compose_cover(background, b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><circle cx="16" cy="16" r="16" fill="red"/></svg>')
        self.assertEqual(cover[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", cover[16:24]), (1068, 455))
        self.assertNotEqual(cover, background)
        for icon in [
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/private.png"/></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a { fill: url(https://untrusted/image); }</style></svg>',
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/private">]><svg/>',
        ]:
            with self.assertRaises(ValueError):
                module.compose_cover(background, icon)

    def test_local_icon_path_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stack_icons").mkdir()
            (root / "stack_icons" / "test.png").write_bytes(b"test")
            with patch.object(module, "get_settings", return_value=SimpleNamespace(HOST_CONFIG_PATH=str(root / "hosts.yaml"))):
                self.assertEqual(module._read_local_icon("/api/static/icons/test.png"), b"test")
                with self.assertRaises(ValueError):
                    module._read_local_icon("/api/static/icons/%2e%2e/private.png")

    def test_article_upload_and_retry_use_one_frozen_media_reference(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "GET":
                self.assertNotIn("X-API-Key", request.headers)
                return httpx.Response(200, content=b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="blue"/></svg>')
            self.assertEqual(request.url.path, "/api/v1/media")
            self.assertEqual(request.headers["X-API-Key"], "test-key")
            return httpx.Response(201, json={"id": "media_cover"})

        async def exercise():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                source = {"event_key": "stable-key", "message_type": "text", "_stack_icon": "https://icons.test/app.svg"}
                wire = await module.prepare_notification(client, "https://notify.test", "test-key", source)
                retry = await module.prepare_notification(client, "https://notify.test", "test-key", wire)
                self.assertEqual(wire, retry)
                self.assertEqual(wire["message_type"], "article")
                self.assertEqual(wire["event_key"], "stable-key")
                self.assertNotIn("_stack_icon", wire)
                self.assertNotIn("url", wire)
        asyncio.run(exercise())
        self.assertEqual(len(requests), 2)

    def test_missing_icon_uses_generic_cover_and_media_denial_preserves_text(self):
        async def exercise():
            uploads = []

            def handler(request):
                if request.method == "GET":
                    return httpx.Response(404)
                uploads.append(request)
                return httpx.Response(403)

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                wire = await module.prepare_notification(client, "https://notify.test", "test-key", {
                    "event_key": "stable-key", "message_type": "text", "title": "result",
                    "_stack_icon": "https://icons.test/missing.png",
                })
                self.assertEqual(wire, {"event_key": "stable-key", "message_type": "text", "title": "result"})
                self.assertEqual(len(uploads), 1)
        asyncio.run(exercise())

    def test_billing_and_traffic_use_their_own_cover_without_requiring_a_click_target(self):
        async def exercise():
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(201, json={"id": "media_host_cover"})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                for event, filename in [("fleetge.host.billing_due", "billing-due.png"),
                                        ("fleetge.host.traffic_quota", "traffic-quota.png")]:
                    wire = await module.prepare_notification(client, "https://notify.test", "test-key", {
                        "event_type": event, "event_key": event, "message_type": "text", "_host_icon": None})
                    self.assertIn(filename.encode(), requests[-1].content)
                    self.assertEqual(wire["message_type"], "article")
                    self.assertNotIn("url", wire)
                    self.assertNotIn("_host_icon", wire)
        asyncio.run(exercise())
