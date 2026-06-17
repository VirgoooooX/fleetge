import os
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Set env vars before importing app
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("CREDENTIALS_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "test-password-hash")

from app.main import app
from app.services.snapshot import snapshot_manager, HostSnapshot
from app.models import HostConfig
from app.schemas import ContainerSummary, DockerInfo, ContainerPort, ContainerStats

class DockerApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.host_id = "test-host"
        
        self.config = HostConfig(
            host_id=self.host_id,
            display_name="Test Host Display Name",
            enabled=True,
            agent_url="http://localhost:8080",
        )
        self.snap = HostSnapshot()
        self.snap.host_config = self.config
        
        # Populate mock docker_info
        self.snap.docker_info = DockerInfo(
            version="20.10.12",
            api_version="1.41",
            os="linux",
            architecture="amd64",
            docker_root_dir="/var/lib/docker",
            server_version="20.10.12",
            kernel_version="5.10.0",
            operating_system="Debian GNU/Linux 11",
            n_cpus=4,
            memory_total=8589934592,
            name="test-node"
        )
        
        # Populate mock container list
        self.snap.containers = [
            ContainerSummary(
                id="a1b2c3d4e5f6",
                name="running-nginx",
                image="nginx:alpine",
                image_id="sha256:nginx123",
                repo_digests=["nginx:alpine@sha256:nginx123"],
                state="running",
                status="Up 3 hours",
                created=1672531199,
                ports=[ContainerPort(private_port=80, public_port=8080, ip="0.0.0.0", type="tcp")],
                labels={"com.docker.compose.project": "nginx-stack"},
                network_mode="bridge",
                networks={"bridge": {"IPAddress": "172.17.0.2"}}
            ),
            ContainerSummary(
                id="f6e5d4c3b2a1",
                name="stopped-db",
                image="postgres:15",
                image_id="sha256:postgres123",
                repo_digests=["postgres:15@sha256:postgres123"],
                state="exited",
                status="Exited (0) 5 hours ago",
                created=1672521199,
                ports=[],
                labels={"com.docker.compose.project": "db-stack"},
                network_mode="bridge",
                networks={}
            )
        ]
        
        # Populate mock container stats
        self.snap.container_stats = {
            "a1b2c3d4e5f6": ContainerStats(
                cpu_percent=12.5,
                memory_usage=45000000,
                memory_limit=200000000,
                memory_percent=22.5,
                network_rx_bytes=102400,
                network_tx_bytes=204800,
                block_read_bytes=1048576,
                block_write_bytes=2097152
            )
        }
        
        # Set containers_updated to current time so it's not stale by default
        self.snap.containers_updated = time.monotonic()
        
        # Register in snapshot manager
        snapshot_manager._snapshots = {self.host_id: self.snap}
        
    def test_ping_with_header(self):
        response = self.client.get("/_ping", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
        self.assertEqual(response.headers.get("cache-control"), "no-cache, no-store, must-revalidate")

    def test_ping_with_query_param(self):
        response = self.client.get(f"/_ping?host={self.host_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
        
    def test_ping_missing_host_returns_400(self):
        response = self.client.get("/_ping")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing host identifier", response.json()["detail"])
        
    def test_version(self):
        response = self.client.get("/version", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["Version"], "20.10.12")
        self.assertEqual(data["ApiVersion"], "1.41")
        self.assertEqual(data["Os"], "linux")
        self.assertEqual(data["Arch"], "amd64")
        self.assertEqual(data["KernelVersion"], "5.10.0")
        
    def test_info(self):
        response = self.client.get("/info", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["Name"], "test-node")
        self.assertEqual(data["ServerVersion"], "20.10.12")
        self.assertEqual(data["NCPU"], 4)
        self.assertEqual(data["MemTotal"], 8589934592)
        self.assertEqual(data["Containers"], 2)
        self.assertEqual(data["ContainersRunning"], 1)
        self.assertEqual(data["ContainersStopped"], 1)
        
    def test_containers_json_default_running_only(self):
        response = self.client.get("/containers/json", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["Id"], "a1b2c3d4e5f6")
        self.assertEqual(data[0]["Names"], ["/running-nginx"])
        self.assertEqual(data[0]["Image"], "nginx:alpine")
        self.assertEqual(data[0]["State"], "running")
        self.assertEqual(data[0]["Ports"][0]["PublicPort"], 8080)
        self.assertEqual(data[0]["HostConfig"]["NetworkMode"], "bridge")
        self.assertEqual(data[0]["NetworkSettings"]["Networks"]["bridge"]["IPAddress"], "172.17.0.2")
        
    def test_containers_json_all(self):
        response = self.client.get("/containers/json?all=true", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        states = {c["Id"]: c["State"] for c in data}
        self.assertEqual(states["a1b2c3d4e5f6"], "running")
        self.assertEqual(states["f6e5d4c3b2a1"], "exited")
        
    def test_container_inspect(self):
        response = self.client.get("/containers/a1b2c3d4e5f6/json", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["Id"], "a1b2c3d4e5f6")
        self.assertEqual(data["Name"], "/running-nginx")
        self.assertTrue(data["State"]["Running"])
        self.assertEqual(data["Config"]["Labels"]["com.docker.compose.project"], "nginx-stack")
        self.assertEqual(data["HostConfig"]["NetworkMode"], "bridge")
        
    def test_container_inspect_by_name(self):
        response = self.client.get("/containers/running-nginx/json", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["Id"], "a1b2c3d4e5f6")
        self.assertEqual(data["Name"], "/running-nginx")
        
    def test_container_inspect_not_found(self):
        response = self.client.get("/containers/nonexistent/json", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 404)
        
    def test_container_stats(self):
        response = self.client.get("/containers/a1b2c3d4e5f6/stats", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify cpu percentage calculation inputs
        cpu_stats = data["cpu_stats"]
        precpu_stats = data["precpu_stats"]
        cpu_delta = cpu_stats["cpu_usage"]["total_usage"] - precpu_stats["cpu_usage"]["total_usage"]
        system_delta = cpu_stats["system_cpu_usage"] - precpu_stats["system_cpu_usage"]
        online_cpus = cpu_stats["online_cpus"]
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
        self.assertAlmostEqual(cpu_percent, 12.5)
        
        # Verify memory limits and usage
        self.assertEqual(data["memory_stats"]["usage"], 45000000)
        self.assertEqual(data["memory_stats"]["limit"], 200000000)
        
        # Verify networks
        self.assertEqual(data["networks"]["eth0"]["rx_bytes"], 102400)
        self.assertEqual(data["networks"]["eth0"]["tx_bytes"], 204800)

    def test_container_stats_by_name(self):
        response = self.client.get("/containers/running-nginx/stats", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["memory_stats"]["usage"], 45000000)
        self.assertEqual(data["memory_stats"]["limit"], 200000000)
        
    def test_images_json(self):
        response = self.client.get("/images/json", headers={"X-Host-Id": self.host_id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        tags = [img["RepoTags"][0] for img in data]
        self.assertIn("nginx:alpine", tags)
        self.assertIn("postgres:15", tags)
        
    def test_unauthorized_public_ip_returns_403(self):
        with patch("app.routers.docker_api.is_private_ip", return_value=False):
            response = self.client.get("/_ping", headers={"X-Host-Id": self.host_id})
            self.assertEqual(response.status_code, 403)
            
    def test_stale_refresh_triggered(self):
        # Set timestamp to 40 seconds ago (stale)
        self.snap.containers_updated = time.monotonic() - 40.0
        
        # Mock refresh_host_docker_with_retry
        mock_refresh = AsyncMock()
        with patch.object(snapshot_manager, "refresh_host_docker_with_retry", mock_refresh):
            response = self.client.get("/_ping", headers={"X-Host-Id": self.host_id})
            self.assertEqual(response.status_code, 200)
            
            # Wait briefly for background task to spawn/execute mock
            time.sleep(0.05)
            mock_refresh.assert_called_once_with(self.host_id)
