"""
Develop Docker 栈使用的 Portal ASGI 入口。

启动前设置 AGENTPORTAL_DEV=1，使 vps/main.py 加载 develop.vps.dev_portal_mode.DevPortalMode。
生产部署请使用 vps.main:app，且镜像/环境中勿设置该变量。
"""
import os

os.environ.setdefault("AGENTPORTAL_DEV", "1")

from vps.main import app  # noqa: E402

__all__ = ["app"]
