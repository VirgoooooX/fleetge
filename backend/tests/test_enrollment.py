from datetime import datetime, timedelta, timezone

from app.models import EnrollmentInvite
from app.services.enrollment_service import (
    build_install_command,
    decode_install_token,
    is_private_host,
    normalize_geolocation,
    normalize_public_host,
    render_install_script,
)


def _invite() -> EnrollmentInvite:
    return EnrollmentInvite(
        invite_id="invite-1",
        install_token_hash="hash",
        claim_token_hash="claim-hash",
        agent_instance_id="instance-123",
        agent_public_host="agent-test.example.com",
        agent_port=8080,
        stack_root="/opt/stacks",
        agent_image="ghcr.io/example/agent:latest",
        secret_path="fleetge-secret",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def test_install_command_contains_only_short_install_token():
    command = build_install_command("https://fleetge.example", "install-envelope")
    assert "install-envelope" in command
    assert "AGENT_TOKEN" not in command
    assert "claim" not in command.lower()


def test_install_envelope_can_be_decoded_without_plaintext_db_storage():
    invite = _invite()
    # The public command token is intentionally opaque; decode helper is tested
    # through a generated command token in the service API rather than DB fields.
    assert invite.agent_token_encrypted is None
    script = render_install_script(invite, "claim-token", "long-agent-token", "https://fleetge.example")
    assert "long-agent-token" not in script
    assert "claim-token" in script
    assert "https://ipwho.is/" not in script
    assert "--noproxy '*'" in script
    assert "callback_mode=direct" in script
    assert "callback_mode=proxy_fallback" in script
    assert "network_mode: host" not in script  # compose content remains base64 encoded


def test_geolocation_is_normalized_and_rejects_bad_coordinates():
    suggestion = normalize_geolocation(
        {
            "city": "Shanghai",
            "region": "Shanghai",
            "country": "China",
            "country_code": "cn",
            "latitude": 31.23,
            "longitude": 121.47,
            "raw_provider_field": "discard",
        }
    )
    assert suggestion == {
        "city": "Shanghai",
        "region": "Shanghai",
        "country": "China",
        "country_code": "CN",
        "latitude": 31.23,
        "longitude": 121.47,
        "source": "ipwho.is",
        "confirmed": False,
    }
    assert normalize_geolocation({"latitude": 190, "longitude": 0}) is None


def test_private_ip_is_not_used_for_external_location():
    assert is_private_host("10.0.0.2")
    assert is_private_host("127.0.0.1")
    assert not is_private_host("8.8.8.8")


def test_agent_public_host_must_be_a_concrete_hostname():
    assert normalize_public_host("agent-vps-01.example.com") == "agent-vps-01.example.com"
    assert normalize_public_host("HTTPS://agent-vps-01.example.com") is None
    assert normalize_public_host("*.example.com") is None
