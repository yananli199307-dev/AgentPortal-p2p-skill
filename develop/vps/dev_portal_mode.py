"""Docker develop 多 Portal：PORTAL_URL 与联系人公网 URL 混用、跨容器 HTTP 转发、消息历史多写法匹配。"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Optional
from urllib.parse import urlparse, urlunparse


class DevPortalMode:
    def normalize_portal_url(self, url: Optional[str]) -> str:
        if not url:
            return ""
        u = url.strip().rstrip("/")
        if not u:
            return ""
        try:
            p = urlparse(u)
            scheme = (p.scheme or "http").lower()
            netloc = p.netloc.lower()
            path = (p.path or "").rstrip("/")
            if path:
                return urlunparse((scheme, netloc, path, "", "", "")).rstrip("/")
            return f"{scheme}://{netloc}"
        except Exception:
            return u

    def portal_match_variants(self, url: str) -> set[str]:
        out: set[str] = set()
        n = self.normalize_portal_url(url)
        if n:
            out.add(n)
        m = re.match(r"^https?://(portal\d+)\.ap2p\.internal:\d+$", n, re.I)
        if m:
            out.add(f"http://{m.group(1).lower()}:8080")
        m2 = re.match(r"^https?://(portal\d+)\.localhost:\d+$", n, re.I)
        if m2:
            out.add(f"http://{m2.group(1).lower()}:8080")
        m3 = re.match(r"^https?://(portal\d+):8080$", n, re.I)
        if m3:
            out.add(f"http://{m3.group(1).lower()}:8080")
        return out

    def message_thread_sql_params(
        self, my_variants: set[str], peer_variants: set[str]
    ) -> tuple[str, list]:
        if not my_variants or not peer_variants:
            return "1=0", []
        parts: list[str] = []
        params: list = []
        for mp in my_variants:
            for pp in peer_variants:
                parts.append(
                    "((from_portal = ? AND to_portal = ?) "
                    "OR (from_portal = ? AND to_portal = ?))"
                )
                params.extend([mp, pp, pp, mp])
        return "(" + " OR ".join(parts) + ")", params

    def websocket_connection_key(self) -> str:
        return os.getenv("PORTAL_URL", "").strip()

    def collect_self_portal_url_candidates(self) -> set[str]:
        out: set[str] = set()
        p = self.normalize_portal_url(os.getenv("PORTAL_URL", ""))
        if p:
            out.add(p)
        for part in os.getenv("PORTAL_URL_ALIASES", "").split(","):
            q = self.normalize_portal_url(part)
            if q:
                out.add(q)
        return out

    def portal_url_is_self(self, url: str) -> bool:
        u = self.normalize_portal_url(url)
        return bool(u and u in self.collect_self_portal_url_candidates())

    def forward_outbound_to_peer_receive(self, to_portal_base: str, body: dict) -> None:
        url = f"{to_portal_base.rstrip('/')}/api/message/receive"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                if resp.status != 200:
                    print(f"Forward to peer returned HTTP {resp.status}")
        except Exception as e:
            print(f"Forward message to peer failed: {e}")

    def ws_connection_key(self, verified_portal_url: str) -> str:
        return self.websocket_connection_key() or verified_portal_url

    def sync_storage_key(self, verified_portal_url: str) -> str:
        return self.websocket_connection_key() or verified_portal_url

    def receive_from_portal_ok(self, contact_portal: str, request_from_portal: str) -> bool:
        return self.normalize_portal_url(contact_portal) == self.normalize_portal_url(
            request_from_portal
        )

    def message_thread_sql(self, my_portal: str, contact_portal: str) -> tuple[str, list]:
        my_variants = self.collect_self_portal_url_candidates() | self.portal_match_variants(
            my_portal
        )
        peer_variants = self.portal_match_variants(contact_portal)
        n = self.normalize_portal_url(contact_portal)
        if n:
            peer_variants.add(n)
        return self.message_thread_sql_params(my_variants, peer_variants)

    def is_sent_row(self, my_portal: str, row_from_portal: str) -> bool:
        my_variants = self.collect_self_portal_url_candidates() | self.portal_match_variants(
            my_portal
        )
        return row_from_portal in my_variants

    def schedule_send_delivery(
        self,
        background_tasks,
        push_message,
        to_portal: str,
        my_portal: str,
        payload: dict,
        forward_body: dict,
    ) -> None:
        if self.portal_url_is_self(to_portal):
            wkey = self.websocket_connection_key() or my_portal
            background_tasks.add_task(push_message, wkey, payload)
        else:
            background_tasks.add_task(
                self.forward_outbound_to_peer_receive, to_portal, forward_body
            )

    def schedule_receive_push(
        self,
        background_tasks,
        push_message,
        my_portal: str,
        message_body: dict,
    ) -> None:
        wkey = self.websocket_connection_key() or my_portal
        background_tasks.add_task(push_message, wkey, message_body)
