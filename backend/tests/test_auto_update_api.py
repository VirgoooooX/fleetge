import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.gettempdir()}/host_dashboard_test.db")

from app.auth.handler import get_current_user
from app.routers import auto_updates as router_module
from app.services import auto_update as service
from app.models import HostConfig


class AutoUpdateApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.patches = [patch.object(service, "engine", self.engine), patch.object(router_module, "engine", self.engine)]
        for item in self.patches:
            item.start()
        self.app = FastAPI()
        self.app.include_router(router_module.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        for item in self.patches:
            item.stop()
        self.engine.dispose()

    def authenticate(self):
        self.app.dependency_overrides[get_current_user] = lambda: "test-admin"

    def test_settings_require_auth_and_never_return_key(self):
        self.assertEqual(self.client.get("/api/admin/notifyhub").status_code, 401)
        self.authenticate()
        response = self.client.put("/api/admin/notifyhub", json={"url": "http://notify", "recipient": "person_1", "api_key": "nfy_private"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["key_configured"])
        self.assertNotIn("nfy_private", response.text)
        self.assertNotIn("nfy_private", self.client.get("/api/admin/notifyhub").text)
        self.assertEqual(self.client.put("/api/admin/notifyhub", json={"url": "http://notify", "recipient": "@all"}).status_code, 422)

    def test_enable_does_not_enqueue_and_disable_works_when_agent_offline(self):
        self.authenticate()
        stack = SimpleNamespace(name="app", compose_file="compose.yaml", management_status="managed")
        snap = SimpleNamespace(host_config=HostConfig(host_id="nas", agent_url="http://agent"), containers=[])
        path = "/api/hosts/nas/stacks/app/auto-update"
        with patch.object(router_module, "require_stack", return_value=(snap, stack)), patch.object(router_module, "unavailable_reason", new=AsyncMock(return_value="")), patch.object(service.auto_update_manager, "enqueue") as enqueue:
            self.assertEqual(self.client.put(path, json={"enabled": True}).status_code, 200)
            self.assertTrue(self.client.get(path).json()["enabled"])
            enqueue.assert_not_called()
        with patch.object(router_module, "require_stack", return_value=(snap, stack)), patch.object(router_module, "unavailable_reason", new=AsyncMock(return_value="offline")):
            self.assertEqual(self.client.put(path, json={"enabled": False}).status_code, 200)
            self.assertEqual(self.client.put(path, json={"enabled": True}).status_code, 409)

    def test_fleetge_stack_cannot_enable(self):
        self.authenticate()
        stack = SimpleNamespace(name="fleetge", compose_file="compose.yaml", management_status="managed")
        snap = SimpleNamespace(host_config=HostConfig(host_id="nas", agent_url="http://agent"), containers=[])
        conn = SimpleNamespace(get_self=AsyncMock(return_value={"stack_name": "fleetge"}), close=AsyncMock())
        with patch.object(router_module, "require_stack", return_value=(snap, stack)), patch.object(router_module, "AgentClient", return_value=conn):
            response = self.client.put("/api/hosts/nas/stacks/fleetge/auto-update", json={"enabled": True})
        self.assertEqual(response.status_code, 409)
