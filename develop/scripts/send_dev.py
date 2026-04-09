#!/usr/bin/env python3
"""
Development-only sender using develop/runtime/envN/gateway.env.
"""

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests


def resolve_env_file(env_name: str = None, env_index: int = None) -> Path:
    root = Path(__file__).resolve().parents[2]
    if env_name:
        return root / "develop" / "runtime" / env_name / "gateway.env"
    if env_index:
        return root / "develop" / "runtime" / f"env{env_index}" / "gateway.env"
    raise ValueError("must provide --env or --env-index")


def _parse_gateway_env(path: Path) -> dict[str, str]:
    acc: dict[str, str] = {}
    if not path.exists():
        return acc
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        acc[k.strip()] = v.strip()
    return acc


def _hub_url_for_runner(vals: dict[str, str]) -> str:
    """
    Bridge containers use AGENTP2P_HUB_URL (http://portalN:8080).
    Host-run send_dev cannot resolve portalN — use AGENTP2P_HUB_URL_HOST instead.
    """
    docker_hub = vals.get("AGENTP2P_HUB_URL", "")
    host_hub = vals.get("AGENTP2P_HUB_URL_HOST", "")
    if not docker_hub:
        return host_hub
    host = urlparse(docker_hub).hostname or ""
    try:
        socket.getaddrinfo(host, None)
        return docker_hub
    except OSError:
        return host_hub or docker_hub


def get_config(env_name: str = None, env_index: int = None):
    api_key = os.environ.get("AGENTP2P_API_KEY")

    gateway_env = resolve_env_file(env_name=env_name, env_index=env_index)
    if not gateway_env.exists():
        print(f"env file not found: {gateway_env}")
        sys.exit(1)

    vals = _parse_gateway_env(gateway_env)
    if vals.get("AGENTP2P_API_KEY"):
        api_key = vals["AGENTP2P_API_KEY"]
    hub_url = _hub_url_for_runner(vals)

    # P2P 协议里的 from_portal 须与 DB/contacts 里存的规范 URL 一致（portalN:8080）
    p2p_self_url = vals.get("AGENTP2P_HUB_URL", hub_url)

    return api_key, hub_url, p2p_self_url


def get_contact(contact_id: int, api_key: str, hub_url: str) -> Optional[Dict[str, Any]]:
    url = f"{hub_url}/api/contacts"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 200:
        contacts = resp.json().get("contacts", [])
        for contact in contacts:
            if contact.get("id") == contact_id:
                return contact
    return None


def send_message(content: str, to_contact_id: int = None, to_user_id: int = None, env_name: str = None, env_index: int = None):
    api_key, my_hub_url, p2p_self_url = get_config(env_name=env_name, env_index=env_index)
    if not api_key or not my_hub_url:
        print("missing AGENTP2P_API_KEY or hub URL")
        sys.exit(1)

    contact_id = to_contact_id or to_user_id
    if not contact_id:
        print("must provide --to-contact or --to-user")
        sys.exit(1)

    contact = get_contact(contact_id, api_key, my_hub_url)
    if not contact:
        print(f"contact not found: {contact_id}")
        sys.exit(1)

    to_portal = contact.get("portal_url")
    shared_key = contact.get("SHARED_KEY")
    if not to_portal or not shared_key:
        print("contact info incomplete")
        sys.exit(1)

    print(f"send to {contact.get('display_name', to_portal)}")
    requests.post(
        f"{to_portal}/api/message/receive",
        json={
            "api_key": shared_key,
            "from_portal": p2p_self_url,
            "content": content,
            "message_type": "text",
        },
        timeout=30,
    )
    requests.post(
        f"{my_hub_url}/api/message/sent",
        json={
            "api_key": api_key,
            "to_portal": to_portal,
            "content": content,
            "message_type": "text",
        },
        timeout=30,
    )
    print("done")


def list_contacts(env_name: str = None, env_index: int = None):
    api_key, hub_url, _ = get_config(env_name=env_name, env_index=env_index)
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{hub_url}/api/contacts", headers=headers, timeout=10)
    if resp.status_code != 200:
        print(f"failed: {resp.status_code}")
        sys.exit(1)
    contacts = resp.json().get("contacts", [])
    for contact in contacts:
        print(f"{contact.get('id')}: {contact.get('display_name', 'Unknown')} -> {contact.get('portal_url')}")


def main():
    parser = argparse.ArgumentParser(description="Development sender for envN.")
    parser.add_argument("content", nargs="?", help="message content")
    parser.add_argument("--to-contact", type=int, help="contact id")
    parser.add_argument("--to-user", type=int, help="user id")
    parser.add_argument("--list", action="store_true", help="list contacts")
    parser.add_argument("--env", help="environment name, e.g. env1")
    parser.add_argument("--env-index", type=int, help="environment index, e.g. 1")
    args = parser.parse_args()

    if not args.env and not args.env_index:
        parser.error("must provide --env or --env-index")

    if args.list:
        list_contacts(env_name=args.env, env_index=args.env_index)
        return

    if not args.content:
        parser.error("content is required unless --list is used")

    send_message(
        args.content,
        to_contact_id=args.to_contact,
        to_user_id=args.to_user,
        env_name=args.env,
        env_index=args.env_index,
    )


if __name__ == "__main__":
    main()
