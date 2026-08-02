import asyncio
from types import SimpleNamespace

from app.models import HostConfig
from app.services.enrollment_service import resolve_request_source_ip
from app.services import network_identity_service
from app.services.network_identity_service import (
    _dns_evidence,
    _select_effective_ip,
    geolocate_consensus,
)


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


def test_effective_ip_uses_best_agent_address_and_prefers_ipv4():
    host = HostConfig(host_id="h", display_name="h")
    categories = {
        "agent": {"eligible": True, "addresses": ["8.8.8.8", "2001:4860:4860::8888"]},
        "callback": {"eligible": False, "addresses": []},
        "dns": {"eligible": False, "eligibleAddresses": []},
    }
    address, source, confidence = _select_effective_ip(host, categories)
    assert address == "8.8.8.8"
    assert source == "agent"
    assert confidence == "high"


def test_effective_ip_prefers_agent_when_other_categories_disagree():
    host = HostConfig(host_id="h", display_name="h")
    categories = {
        "agent": {"eligible": True, "addresses": ["8.8.8.8"]},
        "callback": {"eligible": True, "addresses": ["1.1.1.1"]},
        "dns": {"eligible": True, "eligibleAddresses": ["1.1.1.1"]},
    }
    address, source, confidence = _select_effective_ip(host, categories)
    assert address == "8.8.8.8"
    assert source == "agent"
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


def test_geolocation_uses_single_available_provider(monkeypatch):
    async def fake_provider(provider: str, _address: str):
        if provider == "ipapi.co":
            return None
        return {
            "provider": provider,
            "city": "Los Angeles",
            "region": "California",
            "country": "United States",
            "country_code": "US",
            "latitude": 34.0522,
            "longitude": -118.2437,
        }

    monkeypatch.setattr(network_identity_service, "_geo_provider", fake_provider)
    result = asyncio.run(geolocate_consensus("8.8.8.8"))
    assert result is not None
    assert result["city"] == "Los Angeles"
    assert result["source"] == "ipwho.is"
    assert result["confidence"] == "provider"
    assert result["providers"] == ["ipwho.is"]


def test_geolocation_uses_primary_provider_when_results_conflict(monkeypatch):
    async def fake_provider(provider: str, _address: str):
        if provider == "ipwho.is":
            return {
                "provider": provider,
                "city": "Los Angeles",
                "region": "California",
                "country": "United States",
                "country_code": "US",
                "latitude": 34.0522,
                "longitude": -118.2437,
            }
        return {
            "provider": provider,
            "city": "Toronto",
            "region": "Ontario",
            "country": "Canada",
            "country_code": "CA",
            "latitude": 43.6532,
            "longitude": -79.3832,
        }

    monkeypatch.setattr(network_identity_service, "_geo_provider", fake_provider)
    result = asyncio.run(geolocate_consensus("8.8.8.8"))
    assert result is not None
    assert result["city"] == "Los Angeles"
    assert result["country_code"] == "US"
    assert result["latitude"] == 34.0522
    assert result["source"] == "ipwho.is"
