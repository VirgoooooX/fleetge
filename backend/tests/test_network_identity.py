from types import SimpleNamespace

from app.models import HostConfig
from app.services.enrollment_service import resolve_request_source_ip
from app.services.network_identity_service import _dns_evidence, _select_effective_ip


def _request(peer: str, headers: dict[str, str]):
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_untrusted_peer_cannot_spoof_forwarded_source(monkeypatch):
    from app.services import enrollment_service

    monkeypatch.setattr(
        enrollment_service,
        "get_settings",
        lambda: SimpleNamespace(TRUSTED_PROXY_CIDRS="10.0.0.0/8"),
    )
    request = _request("198.51.100.20", {"x-forwarded-for": "203.0.113.99"})
    assert resolve_request_source_ip(request) == "198.51.100.20"


def test_trusted_proxy_uses_forwarded_source(monkeypatch):
    from app.services import enrollment_service

    monkeypatch.setattr(
        enrollment_service,
        "get_settings",
        lambda: SimpleNamespace(TRUSTED_PROXY_CIDRS="10.0.0.0/8"),
    )
    request = _request("10.1.2.3", {"x-forwarded-for": "203.0.113.99, 10.1.2.3"})
    assert resolve_request_source_ip(request) == "203.0.113.99"


def test_effective_ip_needs_two_categories_and_prefers_ipv4():
    host = HostConfig(host_id="h", display_name="h")
    categories = {
        "agent": {"eligible": True, "addresses": ["8.8.8.8", "2001:4860:4860::8888"]},
        "callback": {"eligible": True, "addresses": ["8.8.8.8"]},
        "dns": {"eligible": True, "eligibleAddresses": ["2001:4860:4860::8888"]},
    }
    address, source, confidence = _select_effective_ip(host, categories)
    assert address == "8.8.8.8"
    assert source == "agent+callback"
    assert confidence == "high"


def test_cdn_dns_is_excluded_from_consensus():
    evidence = _dns_evidence({
        "hostname": "agent.example.com",
        "addresses": ["1.1.1.1"],
        "cnameChain": ["edge.cloudflare.net"],
        "metadata": [{"address": "1.1.1.1", "isProxyOrCdn": True}],
    })
    assert evidence["eligible"] is False
    assert "cdn_cname" in evidence["excludedReasons"]
