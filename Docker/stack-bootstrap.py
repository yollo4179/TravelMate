"""Create local stack configuration inside Docker; host Python is unnecessary."""
import json
import os
import secrets
import shutil
import socket
from pathlib import Path
from urllib.parse import urlsplit


def prepare(state: Path) -> None:
    runtime = state / "runtime.env"
    if not runtime.exists():
        runtime.write_text("JWT_SECRET=" + secrets.token_urlsafe(64) + "\n")
    runtime.chmod(0o600)

    # Use this Linux image's standard CA store unless a custom host bundle was
    # explicitly supplied. Never disable verification or point Python at an empty file.
    if os.environ.get("STACK_CUSTOM_CA") != "1":
        shutil.copyfile("/etc/ssl/certs/ca-certificates.crt", state / "ca-bundle.pem")
    (state / "ca-bundle.pem").chmod(0o644)

    proxy = urlsplit(os.environ.get("HTTPS_PROXY", ""))
    lines = []
    if proxy.hostname:
        for scheme in ("http", "https"):
            lines += [f"systemProp.{scheme}.proxyHost={proxy.hostname}",
                      f"systemProp.{scheme}.proxyPort={proxy.port or 80}"]
    lines.append("systemProp.http.nonProxyHosts=localhost|127.*")
    (state / "gradle.properties").write_text("\n".join(lines) + "\n")

    hosts = {}
    for name in ("HTTPS_PROXY", "HTTP_PROXY"):
        host = urlsplit(os.environ.get(name, "")).hostname
        if host:
            hosts[host] = socket.gethostbyname(host)
    services = {}
    if hosts:
        build = {"extra_hosts": hosts}
        if os.environ.get("STACK_BUILD_NETWORK"):
            build["network"] = os.environ["STACK_BUILD_NETWORK"]
        services["server"] = {"build": build}
        services["embedding"] = {"build": build, "extra_hosts": hosts}
    # JSON is valid YAML; proxy settings stay in ignored local state.
    (state / "proxy.compose.yml").write_text(json.dumps({"services": services}))


if __name__ == "__main__":
    prepare(Path("/stack"))
