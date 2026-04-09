# OpenClaw official image is Node-based and has no pip. Extend it with Python 3 + venv for skill scripts.
ARG LOBSTER_BASE=ghcr.io/openclaw/openclaw:latest
FROM ${LOBSTER_BASE}

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# 必须用带小版本的解释器建 venv：若用 python3 -m venv，bin/python3 常链到 /usr/bin/python3，
# 后面再让 /usr/bin/python3 指向 venv 会形成「Too many levels of symbolic links」。
COPY develop/docker/requirements-lobster.txt /tmp/requirements-lobster.txt
RUN set -eux; \
    if [ -x /usr/bin/python3.12 ]; then V=/usr/bin/python3.12; \
    elif [ -x /usr/bin/python3.11 ]; then V=/usr/bin/python3.11; \
    else V=/usr/bin/python3; fi; \
    "$V" -m venv /opt/ap2p-skill-python; \
    /opt/ap2p-skill-python/bin/pip install --no-cache-dir --upgrade pip; \
    /opt/ap2p-skill-python/bin/pip install --no-cache-dir -r /tmp/requirements-lobster.txt; \
    rm /tmp/requirements-lobster.txt; \
    chmod -R a+rX /opt/ap2p-skill-python

# 子进程写死 /usr/bin/python3：用包装脚本 exec venv，避免与 venv 内指向 /usr/bin/python3 的 symlink 形成环
RUN set -eux; \
    mv /usr/bin/python3 /usr/bin/python3.distrib; \
    printf '%s\n' '#!/bin/sh' 'exec /opt/ap2p-skill-python/bin/python3 "$@"' > /usr/bin/python3; \
    chmod +x /usr/bin/python3; \
    if [ -e /opt/ap2p-skill-python/bin/python ]; then \
      mv /usr/bin/python /usr/bin/python.distrib 2>/dev/null || true; \
      printf '%s\n' '#!/bin/sh' 'exec /opt/ap2p-skill-python/bin/python "$@"' > /usr/bin/python; \
      chmod +x /usr/bin/python; \
    fi

RUN /usr/bin/python3 -c "import requests, urllib3; print('lobster python deps ok')"

ENV PATH="/opt/ap2p-skill-python/bin:${PATH}"

# Match official Node / OpenClaw images (non-root).
USER node
