#!/usr/bin/env python3
"""
Generate N local development environments for Docker debugging.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / "develop" / "runtime"
DOCKER_DIR = ROOT / "develop" / "docker"
GENERATED_COMPOSE = DOCKER_DIR / "docker-compose.generated.yml"
DEVELOP_DOTENV = ROOT / "develop" / ".env"

BASE_HOST_PORT = 18080
BASE_LOBSTER_HOST_PORT = 18790

# Plain HTTP reverse proxy (Caddy): http://lobsterN.localhost:OPENCLAW_UI_PROXY_HOST_PORT → lobsterN:18789
# Browsers treat http://*.localhost as a secure context (Web Crypto / device identity), unlike http://*.sslip.io.
OPENCLAW_UI_PROXY_HOST_PORT = 18443
OPENCLAW_UI_PROXY_CONTAINER_PORT = 8443
GENERATED_CADDY_UI = DOCKER_DIR / "Caddyfile.openclaw-ui.generated"

# Portal URLs shared with agents: must NOT be *.localhost — Node (OpenClaw/fetch) resolves *.localhost to
# 127.0.0.1 inside the process (RFC 6761), ignoring /etc/hosts, so Docker extra_hosts never applies.
DEV_PORTAL_PUBLIC_SUFFIX = "ap2p.internal"


def env_index_from_runtime_dir(env_dir: Path) -> int:
    name = env_dir.name
    if name.startswith("env") and name[3:].isdigit():
        return max(1, int(name[3:]))
    return 1


def portal_public_host(env_index: int) -> str:
    """Use in URLs you give to the lobster (HTTP API). Resolvable via compose extra_hosts → host-gateway."""
    return f"portal{env_index}.{DEV_PORTAL_PUBLIC_SUFFIX}"


def lobster_localhost_proxy_origin(env_index: int) -> str:
    """Distinct hostname per lobster + secure context; see OPENCLAW_UI_PROXY_* + openclaw-ui-proxy in compose."""
    return f"http://lobster{env_index}.localhost:{OPENCLAW_UI_PROXY_HOST_PORT}"


def scrub_sslip_allowed_origins(origins: list[str]) -> list[str]:
    """http://*.sslip.io is not a secure context — Control UI rejects it; drop from allowlist."""
    return [o for o in origins if ".sslip.io" not in o]


def apply_develop_openclaw_control_ui_bypass(cu: dict) -> bool:
    """
    OpenClaw Control UI may require device pairing / device identity over WS; Docker + proxy + HTTP
    triggers \"pairing required\" or authorization failures despite a valid gateway token.
    These flags are develop-stack only (runtime is gitignored).
    """
    dirty = False
    if cu.get("dangerouslyDisableDeviceAuth") is not True:
        cu["dangerouslyDisableDeviceAuth"] = True
        dirty = True
    if cu.get("allowInsecureAuth") is not True:
        cu["allowInsecureAuth"] = True
        dirty = True
    return dirty


# OpenClaw expects provider API keys + agents.defaults.model.primary; gateway.env alone is not enough.
_MOONSHOT_MODEL_ALIASES: dict[str, str] = {
    "kimi": "moonshot/kimi-k2.5",
    "kimi-k2.5": "moonshot/kimi-k2.5",
    "kimi-k2-thinking": "moonshot/kimi-k2-thinking",
    "kimi-k2-thinking-turbo": "moonshot/kimi-k2-thinking-turbo",
    "kimi-k2-turbo": "moonshot/kimi-k2-turbo",
    "kimi-code": "kimi/kimi-code",
    "kimi-coding": "kimi/kimi-code",
}

# OpenClaw rejects providers.moonshot without a non-empty models[] (gateway exits at startup).
_MOONSHOT_PROVIDER_MODELS: list[dict] = [
    {
        "id": "kimi-k2.5",
        "name": "Kimi K2.5",
        "reasoning": False,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 262144,
        "maxTokens": 262144,
        "compat": {"supportsUsageInStreaming": True},
    },
    {
        "id": "kimi-k2-thinking",
        "name": "Kimi K2 Thinking",
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 262144,
        "maxTokens": 262144,
        "compat": {"supportsUsageInStreaming": True},
    },
    {
        "id": "kimi-k2-thinking-turbo",
        "name": "Kimi K2 Thinking Turbo",
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 262144,
        "maxTokens": 262144,
        "compat": {"supportsUsageInStreaming": True},
    },
    {
        "id": "kimi-k2-turbo",
        "name": "Kimi K2 Turbo",
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 256000,
        "maxTokens": 16384,
        "compat": {"supportsUsageInStreaming": True},
    },
]


def resolve_lobster_model_primary(lobster_model: str) -> str:
    """
    Map develop LOBSTER_MODEL shorthand to OpenClaw model.primary refs.
    Moonshot (Kimi K2): moonshot/kimi-*. Kimi Coding: kimi/kimi-code.
    """
    raw = (lobster_model or "kimi").strip()
    if not raw:
        return _MOONSHOT_MODEL_ALIASES["kimi"]
    key = raw.lower()
    if key in _MOONSHOT_MODEL_ALIASES:
        return _MOONSHOT_MODEL_ALIASES[key]
    if "/" in raw:
        return raw.strip()
    return f"moonshot/{raw.strip()}"


def resolve_moonshot_base_url(existing: dict[str, str], develop_dotenv: dict[str, str]) -> str:
    """
    Moonshot 国内开放平台密钥只接受 api.moonshot.cn；用 api.moonshot.ai 会稳定 401。
    默认走国内线；国际密钥请在 develop/.env 设 LOBSTER_MOONSHOT_REGION=intl。
    """
    b = env_or_existing("LOBSTER_MOONSHOT_BASE_URL", existing, "", develop_file=develop_dotenv)
    r = env_or_existing("LOBSTER_MOONSHOT_REGION", existing, "cn", develop_file=develop_dotenv).lower()
    intl = r in ("intl", "global", "ai", "moonshot-ai", "international")
    if b:
        if b.rstrip("/") == "https://api.moonshot.ai/v1" and not intl:
            return "https://api.moonshot.cn/v1"
        return b
    if intl:
        return "https://api.moonshot.ai/v1"
    return "https://api.moonshot.cn/v1"


def env_or_existing(
    key: str,
    existing: dict[str, str],
    default: str,
    *,
    develop_file: dict[str, str],
) -> str:
    """Prefer process env, then develop/.env, then existing gateway.env, then default."""
    raw = os.environ.get(key)
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip()
    file_val = develop_file.get(key)
    if file_val is not None and str(file_val).strip() != "":
        return str(file_val).strip()
    return existing.get(key, default)


def merge_lobster_openclaw_config(
    env_dir: Path,
    lobster_host_port: int,
    gateway_operator_token: str,
    *,
    lobster_model: str,
    env_index: int,
) -> None:
    """
    OpenClaw Control UI checks the browser Origin on WebSocket connect. Docker maps
    host ports (e.g. 18790) to gateway port 18789 inside the container; the default
    allowlist only matches :18789, so the UI must allow the URL shown in the address bar.

    The dashboard WebSocket uses gateway.auth.token (operator), not hooks.token /
    OPENCLAW_HOOKS_TOKEN; those must match what we put in gateway.env as
    OPENCLAW_GATEWAY_TOKEN so printed URLs work.

    For multiple lobsters use http://lobsterN.localhost on the openclaw-ui-proxy port (18443 by default):
    *.localhost stays a secure context in browsers, and distinct hostnames avoid cookie collisions.
    """
    home = env_dir / "lobster-home"
    home.mkdir(parents=True, exist_ok=True)
    path = home / "openclaw.json"
    needed = {
        f"http://127.0.0.1:{lobster_host_port}",
        f"http://localhost:{lobster_host_port}",
        lobster_localhost_proxy_origin(env_index),
    }
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            data: dict = raw if isinstance(raw, dict) else {}
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    gw = data.setdefault("gateway", {})
    if not isinstance(gw, dict):
        gw = {}
        data["gateway"] = gw
    cu = gw.setdefault("controlUi", {})
    if not isinstance(cu, dict):
        cu = {}
        gw["controlUi"] = cu

    existing = cu.get("allowedOrigins")
    if existing is None:
        existing_list: list[str] = []
    elif isinstance(existing, list):
        existing_list = [str(x) for x in existing]
    else:
        existing_list = []

    existing_list = scrub_sslip_allowed_origins(existing_list)
    cu["allowedOrigins"] = sorted(set(existing_list) | needed)
    apply_develop_openclaw_control_ui_bypass(cu)

    if gateway_operator_token.strip():
        gw["bind"] = "lan"
        auth = gw.get("auth")
        if not isinstance(auth, dict):
            auth = {}
        auth["mode"] = "token"
        auth["token"] = gateway_operator_token.strip()
        gw["auth"] = auth

    primary = resolve_lobster_model_primary(lobster_model)
    agents = data.get("agents")
    if not isinstance(agents, dict):
        agents = {}
    data["agents"] = agents
    defaults = agents.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}
    agents["defaults"] = defaults
    model_block = defaults.get("model")
    if not isinstance(model_block, dict):
        model_block = {}
    defaults["model"] = model_block
    model_block["primary"] = primary

    if primary.startswith("moonshot/"):
        gvals = parse_env_file(env_dir / "gateway.env")
        develop_dd = parse_env_file(DEVELOP_DOTENV)
        base = resolve_moonshot_base_url(gvals, develop_dd)
        moon_key = (gvals.get("MOONSHOT_API_KEY") or "").strip()
        models_cfg = data.get("models")
        if not isinstance(models_cfg, dict):
            models_cfg = {}
        data["models"] = models_cfg
        if models_cfg.get("mode") is None:
            models_cfg["mode"] = "merge"
        providers = models_cfg.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        models_cfg["providers"] = providers
        moon = providers.get("moonshot")
        if not isinstance(moon, dict):
            moon = {}
        providers["moonshot"] = moon
        moon["baseUrl"] = base
        moon["api"] = moon.get("api") or "openai-completions"
        # ${MOONSHOT_API_KEY} 在部分网关启动顺序下无法从进程环境替换，导致请求无密钥、聊天一直无输出。
        # develop 栈从 gateway.env 写入明文（runtime 已 gitignore）。
        if moon_key and moon_key != "CHANGE_ME":
            moon["apiKey"] = moon_key
            env_top = data.get("env")
            if not isinstance(env_top, dict):
                env_top = {}
            data["env"] = env_top
            env_top["MOONSHOT_API_KEY"] = moon_key
        elif moon.get("apiKey") is None:
            moon["apiKey"] = "${MOONSHOT_API_KEY}"
        if not moon.get("models"):
            moon["models"] = [dict(m) for m in _MOONSHOT_PROVIDER_MODELS]

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if primary.startswith("moonshot/"):
        patch_moonshot_runtime(env_dir)


def parse_env_file(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_file.exists():
        return values
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_lobster_dotenv_moonshot(home: Path, moon_key: str) -> None:
    """OpenClaw also loads ~/.openclaw/.env — helps subprocess / agent paths that miss compose env_file."""
    if not moon_key or moon_key == "CHANGE_ME":
        return
    dot = home / ".env"
    lines: list[str] = []
    if dot.exists():
        for line in dot.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("MOONSHOT_API_KEY="):
                lines.append(line.rstrip())
    lines.append(f"MOONSHOT_API_KEY={moon_key}")
    dot.write_text("\n".join(lines) + "\n", encoding="utf-8")


def patch_agent_models_moonshot_key(home: Path, moon_key: str, moon_base: str) -> None:
    """
    Gateway re-materializes agents/*/agent/models.json with apiKey \"MOONSHOT_API_KEY\" (literal),
    which Moonshot rejects with 401. Rewrite from gateway.env after each start / gen.
    Also sync baseUrl (cn vs ai) when OpenClaw regenerates the file.
    """
    if not moon_key or moon_key == "CHANGE_ME":
        return
    agents_root = home / "agents"
    if not agents_root.is_dir():
        return
    bad = frozenset({"MOONSHOT_API_KEY", "${MOONSHOT_API_KEY}", ""})
    for path in agents_root.rglob("models.json"):
        if path.parent.name != "agent":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        prov = raw.get("providers")
        if not isinstance(prov, dict):
            continue
        moon = prov.get("moonshot")
        if not isinstance(moon, dict):
            continue
        dirty = False
        cur = moon.get("apiKey")
        if cur in bad or cur is None or cur != moon_key:
            moon["apiKey"] = moon_key
            dirty = True
        if moon_base and moon.get("baseUrl") != moon_base:
            moon["baseUrl"] = moon_base
            dirty = True
        if dirty:
            path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def patch_openclaw_json_moonshot(home: Path, moon_key: str, moon_base: str) -> None:
    """Keep models.providers.moonshot in openclaw.json aligned with gateway.env (gateway often reads this, not per-agent models.json)."""
    path = home / "openclaw.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    models_cfg = data.get("models")
    if not isinstance(models_cfg, dict):
        return
    providers = models_cfg.get("providers")
    if not isinstance(providers, dict):
        return
    moon = providers.get("moonshot")
    if not isinstance(moon, dict):
        return
    bad = frozenset({"MOONSHOT_API_KEY", "${MOONSHOT_API_KEY}", ""})
    dirty = False
    if moon_base and moon.get("baseUrl") != moon_base:
        moon["baseUrl"] = moon_base
        dirty = True
    if moon_key and moon_key != "CHANGE_ME":
        cur = moon.get("apiKey")
        if cur in bad or cur is None or cur != moon_key:
            moon["apiKey"] = moon_key
            dirty = True
    if dirty:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def patch_openclaw_control_ui_origins(home: Path, env_index: int, lobster_host_port: int) -> None:
    """Ensure allowlist includes direct ports + lobsterN.localhost proxy origin; strip legacy sslip.io."""
    path = home / "openclaw.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    gw = data.setdefault("gateway", {})
    if not isinstance(gw, dict):
        gw = {}
        data["gateway"] = gw
    cu = gw.setdefault("controlUi", {})
    if not isinstance(cu, dict):
        cu = {}
        gw["controlUi"] = cu
    existing = cu.get("allowedOrigins")
    if existing is None:
        existing_list: list[str] = []
    elif isinstance(existing, list):
        existing_list = [str(x) for x in existing]
    else:
        existing_list = []
    scrubbed = scrub_sslip_allowed_origins(existing_list)
    needed = {
        f"http://127.0.0.1:{lobster_host_port}",
        f"http://localhost:{lobster_host_port}",
        lobster_localhost_proxy_origin(env_index),
    }
    merged = sorted(set(scrubbed) | needed)
    bypass_dirty = apply_develop_openclaw_control_ui_bypass(cu)
    origins_dirty = merged != sorted(existing_list)
    if not bypass_dirty and not origins_dirty:
        return
    cu["allowedOrigins"] = merged
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def patch_moonshot_runtime(env_dir: Path) -> None:
    vals = parse_env_file(env_dir / "gateway.env")
    home = env_dir / "lobster-home"
    idx = env_index_from_runtime_dir(env_dir)
    port_raw = (vals.get("LOBSTER_HOST_PORT") or "").strip()
    try:
        lobster_host_port = int(port_raw) if port_raw else BASE_LOBSTER_HOST_PORT + idx - 1
    except ValueError:
        lobster_host_port = BASE_LOBSTER_HOST_PORT + idx - 1
    patch_openclaw_control_ui_origins(home, idx, lobster_host_port)

    develop_dd = parse_env_file(DEVELOP_DOTENV)
    primary = resolve_lobster_model_primary(vals.get("LOBSTER_MODEL", "kimi"))
    if not primary.startswith("moonshot/"):
        return
    moon_key = (vals.get("MOONSHOT_API_KEY") or "").strip()
    moon_base = resolve_moonshot_base_url(vals, develop_dd)
    write_lobster_dotenv_moonshot(home, moon_key)
    patch_agent_models_moonshot_key(home, moon_key, moon_base)
    patch_openclaw_json_moonshot(home, moon_key, moon_base)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate develop runtime env files and compose.",
        epilog="LOBSTER_* via shell → develop/.env → existing gateway.env. "
        "Default Moonshot base is https://api.moonshot.cn/v1; use LOBSTER_MOONSHOT_REGION=intl for api.moonshot.ai.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--count", type=int, default=2, help="Number of environments to generate.")
    parser.add_argument("--with-lobster", action="store_true", help="Generate one lobster service per env.")
    parser.add_argument(
        "--lobster-image",
        default="ghcr.io/openclaw/openclaw:latest",
        help="Container image used for lobster services.",
    )
    parser.add_argument(
        "--patch-moonshot-only",
        action="store_true",
        help="Sync Moonshot + Control UI allowedOrigins (incl. lobsterN.localhost proxy) from gateway.env …",
    )
    return parser.parse_args()


def env_gateway_content(
    index: int,
    host_port: int,
    with_lobster: bool,
    lobster_host_port: int,
    existing: dict[str, str],
    develop_dotenv: dict[str, str],
) -> str:
    gateway_url = f"http://lobster{index}:18789" if with_lobster else "http://host.docker.internal:18789"
    hooks_token = existing.get("OPENCLAW_HOOKS_TOKEN", "")
    if (not hooks_token) or hooks_token == "CHANGE_ME" or hooks_token.startswith("dev-hooks-token-"):
        hooks_token = secrets.token_urlsafe(24)

    gateway_token = existing.get("OPENCLAW_GATEWAY_TOKEN", "")
    if (not gateway_token) or gateway_token == "CHANGE_ME":
        gateway_token = secrets.token_urlsafe(24)
    while gateway_token == hooks_token:
        gateway_token = secrets.token_urlsafe(24)

    lobster_api_key = env_or_existing(
        "LOBSTER_API_KEY", existing, "CHANGE_ME", develop_file=develop_dotenv
    )
    lobster_model = env_or_existing(
        "LOBSTER_MODEL", existing, "kimi", develop_file=develop_dotenv
    )
    primary = resolve_lobster_model_primary(lobster_model)
    if primary.startswith("kimi/"):
        provider_key_line = f"KIMI_API_KEY={lobster_api_key}"
    else:
        provider_key_line = f"MOONSHOT_API_KEY={lobster_api_key}"
    moonshot_base = resolve_moonshot_base_url(existing, develop_dotenv)
    agentp2p_api_key = existing.get("AGENTP2P_API_KEY", "CHANGE_ME")
    agent_identity = existing.get("AGENT_IDENTITY", f"lobster-agent-{index}")
    agent_name = existing.get("AGENT_NAME", f"lobster-agent-{index}")
    return "\n".join(
        [
            f"AGENT_IDENTITY={agent_identity}",
            f"AGENT_NAME={agent_name}",
            f"LOBSTER_API_KEY={lobster_api_key}",
            f"LOBSTER_MODEL={lobster_model}",
            f"LOBSTER_MOONSHOT_BASE_URL={moonshot_base}",
            provider_key_line,
            f"AGENTP2P_API_KEY={agentp2p_api_key}",
            f"AGENTP2P_HUB_URL=http://portal{index}:8080",
            f"AGENTP2P_PORTAL_PUBLIC_URL=http://portal{index}.{DEV_PORTAL_PUBLIC_SUFFIX}:{host_port}",
            f"AGENTP2P_HUB_URL_HOST=http://127.0.0.1:{host_port}",
            f"OPENCLAW_GATEWAY_URL={gateway_url}",
            f"OPENCLAW_HOOKS_TOKEN={hooks_token}",
            f"OPENCLAW_GATEWAY_TOKEN={gateway_token}",
            f"AGENTP2P_HOST_PORT={host_port}",
            f"LOBSTER_HOST_PORT={lobster_host_port}",
            "",
        ]
    )


def generate_openclaw_ui_caddyfile(count: int) -> str:
    """Caddy vhosts on one HTTP port; Host header selects lobsterN (Docker DNS)."""
    lines = [
        "# Generated by develop/scripts/gen_envs.py — plain HTTP; browsers treat http://*.localhost as secure.",
        "{",
        "    auto_https off",
        "}",
        "",
        f"http://:{OPENCLAW_UI_PROXY_CONTAINER_PORT} {{",
    ]
    for i in range(1, count + 1):
        lines.append(f"    @lobster{i} host lobster{i}.localhost")
        lines.append(f"    handle @lobster{i} {{")
        lines.append(f"        reverse_proxy lobster{i}:18789")
        lines.append("    }")
    lines.append("    handle {")
    lines.append(
        f'        respond "unknown host — use http://lobster{{N}}.localhost:{OPENCLAW_UI_PROXY_HOST_PORT}" 404'
    )
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def compose_dev_public_hostname_extra_hosts(total_count: int) -> str:
    """
    Map portalN.<suffix> to the Docker host so containers reach published portal ports.
    Do not use *.localhost for this: Node hard-wires it to 127.0.0.1 and ignores /etc/hosts.
    """
    entries = ["host.docker.internal:host-gateway"]
    for i in range(1, total_count + 1):
        entries.append(f"portal{i}.{DEV_PORTAL_PUBLIC_SUFFIX}:host-gateway")
    return "\n".join(f'      - "{e}"' for e in entries)


def compose_openclaw_ui_proxy_block(count: int) -> str:
    dep_lines = "\n".join(f"      - lobster{i}" for i in range(1, count + 1))
    return (
        "  openclaw-ui-proxy:\n"
        "    image: caddy:2-alpine\n"
        "    container_name: ap2p-openclaw-ui-proxy\n"
        "    ports:\n"
        f'      - "{OPENCLAW_UI_PROXY_HOST_PORT}:{OPENCLAW_UI_PROXY_CONTAINER_PORT}"\n'
        "    volumes:\n"
        "      - ./Caddyfile.openclaw-ui.generated:/etc/caddy/Caddyfile:ro\n"
        "    depends_on:\n"
        f"{dep_lines}\n"
        "\n"
    )


def compose_service_block(
    index: int, host_port: int, with_lobster: bool, lobster_image: str, total_count: int
) -> str:
    lobster_block = ""
    bridge_depends = f"      - portal{index}"
    extra_hosts_yaml = compose_dev_public_hostname_extra_hosts(total_count)
    if with_lobster:
        lobster_host_port = BASE_LOBSTER_HOST_PORT + (index - 1)
        lobster_block = f"""  lobster{index}:
    image: {lobster_image}
    container_name: ap2p-lobster-{index}
    env_file:
      - ../runtime/env{index}/gateway.env
    volumes:
      - ../runtime/env{index}/lobster-home:/home/node/.openclaw
      - ../../:/home/node/.openclaw/workspace/skills/agent-p2p
    ports:
      - "{lobster_host_port}:18789"
    extra_hosts:
{extra_hosts_yaml}

"""
        bridge_depends = f"""      - portal{index}
      - lobster{index}"""
    return f"""{lobster_block}  portal{index}:
    build:
      context: ../..
      dockerfile: develop/docker/Dockerfile.portal
    container_name: ap2p-portal-{index}
    environment:
      PORT: "8080"
      PORTAL_URL: "http://portal{index}:8080"
      DATABASE_PATH: "/app/develop/runtime/env{index}/portal.db"
    ports:
      - "{host_port}:8080"
    volumes:
      - ../runtime:/app/develop/runtime

  bridge{index}:
    build:
      context: ../..
      dockerfile: develop/docker/Dockerfile.bridge
    container_name: ap2p-bridge-{index}
    env_file:
      - ../runtime/env{index}/gateway.env
    extra_hosts:
{extra_hosts_yaml}
    depends_on:
{bridge_depends}
    volumes:
      - ../runtime:/app/develop/runtime
"""


def generate_compose(count: int, with_lobster: bool, lobster_image: str) -> str:
    header = [
        "name: agentp2p-dev",
        "",
        "services:",
    ]
    blocks = []
    for i in range(1, count + 1):
        host_port = BASE_HOST_PORT + (i - 1)
        blocks.append(compose_service_block(i, host_port, with_lobster, lobster_image, count))
    body = "\n".join(header + blocks) + "\n"
    if with_lobster:
        body = body.rstrip("\n") + "\n" + compose_openclaw_ui_proxy_block(count)
    return body


def main() -> None:
    args = parse_args()
    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    if args.patch_moonshot_only:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        for i in range(1, args.count + 1):
            patch_moonshot_runtime(RUNTIME_DIR / f"env{i}")
        print(
            f"Patched lobster runtime for env1..env{args.count} "
            "(openclaw Control UI origins; Moonshot .env/models/openclaw provider when model is moonshot)"
        )
        return

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    DOCKER_DIR.mkdir(parents=True, exist_ok=True)
    develop_dotenv = parse_env_file(DEVELOP_DOTENV)

    for i in range(1, args.count + 1):
        host_port = BASE_HOST_PORT + (i - 1)
        lobster_host_port = BASE_LOBSTER_HOST_PORT + (i - 1)
        env_dir = RUNTIME_DIR / f"env{i}"
        env_dir.mkdir(parents=True, exist_ok=True)
        env_file = env_dir / "gateway.env"
        existing = parse_env_file(env_file)
        env_file.write_text(
            env_gateway_content(
                i, host_port, args.with_lobster, lobster_host_port, existing, develop_dotenv
            ),
            encoding="utf-8",
        )
        if args.with_lobster:
            (env_dir / "lobster-home").mkdir(parents=True, exist_ok=True)
            written_env = parse_env_file(env_file)
            merge_lobster_openclaw_config(
                env_dir,
                lobster_host_port,
                written_env.get("OPENCLAW_GATEWAY_TOKEN", ""),
                lobster_model=written_env.get("LOBSTER_MODEL", "kimi"),
                env_index=i,
            )

    GENERATED_COMPOSE.write_text(
        generate_compose(args.count, args.with_lobster, args.lobster_image),
        encoding="utf-8",
    )
    if args.with_lobster:
        GENERATED_CADDY_UI.write_text(generate_openclaw_ui_caddyfile(args.count), encoding="utf-8")
    elif GENERATED_CADDY_UI.exists():
        GENERATED_CADDY_UI.unlink()
    print(
        f"Generated {args.count} env(s), with_lobster={args.with_lobster}, and {GENERATED_COMPOSE}"
    )


if __name__ == "__main__":
    main()
