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
        runtime.write_text(
            "JWT_SECRET=" + secrets.token_urlsafe(64) + "\n"
            + "FASTAPI_DB_PASSWORD=" + secrets.token_urlsafe(32) + "\n"
        )
    runtime_values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in runtime.read_text(encoding="utf-8").splitlines()
        if "=" in line
    }
    runtime_values.setdefault("FASTAPI_DB_PASSWORD", secrets.token_urlsafe(32))
    runtime.write_text(
        "".join(f"{key}={value}\n" for key, value in runtime_values.items()),
        encoding="utf-8",
    )
    source_env = state / "source.env"
    if source_env.is_file():
        source_values = {
            key: value
            for line in source_env.read_text(encoding="utf-8").splitlines()
            if "=" in line
            for key, value in [line.split("=", 1)]
            if key in {
                "LANGSMITH_API_KEY",
                "LANGCHAIN_API_KEY",
                "LANGSMITH_PROJECT",
                "RERANK_BATCH_SIZE",
                "RERANK_DIAGNOSTICS_ENABLED",
                "RERANK_EXECUTION_STRATEGY",
                "PERPLEXITY_API_KEY",
                "PERPLEXITY_AGENT_PRESET",
                "PERPLEXITY_AGENT_MODEL",
            }
        }
        api_key = source_values.get("LANGSMITH_API_KEY") or source_values.get("LANGCHAIN_API_KEY")
        runtime_values = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in runtime.read_text(encoding="utf-8").splitlines()
            if "=" in line
        }
        if api_key:
            runtime_values["LANGSMITH_API_KEY"] = api_key
        if source_values.get("LANGSMITH_PROJECT"):
            runtime_values["LANGSMITH_PROJECT"] = source_values["LANGSMITH_PROJECT"]
        for key in (
            "RERANK_BATCH_SIZE",
            "RERANK_DIAGNOSTICS_ENABLED",
            "RERANK_EXECUTION_STRATEGY",
        ):
            if source_values.get(key):
                runtime_values[key] = source_values[key]
        for key in ("PERPLEXITY_API_KEY", "PERPLEXITY_AGENT_PRESET", "PERPLEXITY_AGENT_MODEL"):
            # Removing a credential/selector from .env must also remove its stale forwarded value.
            if key in source_values:
                value = source_values[key].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                runtime_values[key] = value
            else:
                runtime_values.pop(key, None)
        runtime.write_text(
            "".join(f"{key}={value}\n" for key, value in runtime_values.items()),
            encoding="utf-8",
        )
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
