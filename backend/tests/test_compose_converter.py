import pytest
import yaml
from fastapi import HTTPException

from app.routers.stacks import _convert_docker_run_to_compose


def test_convert_docker_run_common_flags():
    compose_yaml = _convert_docker_run_to_compose(
        "docker run -d --name web --restart unless-stopped "
        "-p 8080:80 -v /data:/usr/share/nginx/html "
        "-e TZ=Asia/Shanghai --network host nginx:latest nginx -g 'daemon off;'"
    )

    data = yaml.safe_load(compose_yaml)
    service = data["services"]["web"]
    assert service["container_name"] == "web"
    assert service["restart"] == "unless-stopped"
    assert service["network_mode"] == "host"
    assert service["image"] == "nginx:latest"
    assert service["ports"] == ["8080:80"]
    assert service["volumes"] == ["/data:/usr/share/nginx/html"]
    assert service["environment"] == ["TZ=Asia/Shanghai"]
    assert service["command"] == ["nginx", "-g", "daemon off;"]


def test_convert_docker_run_rejects_unsupported_flags():
    with pytest.raises(HTTPException) as exc_info:
        _convert_docker_run_to_compose("docker run --pull always nginx")

    assert exc_info.value.status_code == 400
    assert "Unsupported docker run flag" in exc_info.value.detail
