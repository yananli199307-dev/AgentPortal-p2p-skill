#!/usr/bin/env python3
"""
Development-only bridge process manager.
Uses develop/runtime/envN for pid/log/env files.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def get_runtime_paths(env_name=None, env_index=None):
    root = Path(__file__).resolve().parents[2]
    if env_name or env_index:
        name = env_name or f"env{env_index}"
        env_dir = root / "develop" / "runtime" / name
        env_dir.mkdir(parents=True, exist_ok=True)
        return env_dir / "bridge.pid", env_dir / "bridge.log", env_dir / "gateway.env"
    raise ValueError("must provide --env or --env-index")


def get_pid(pid_file):
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return pid
        except Exception:
            pid_file.unlink(missing_ok=True)
    return None


def is_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def start(env_name=None, env_index=None):
    pid_file, log_file, env_file = get_runtime_paths(env_name=env_name, env_index=env_index)
    pid = get_pid(pid_file)
    if pid and is_running(pid):
        print(f"Bridge already running (PID: {pid})")
        return

    env = os.environ.copy()
    if env_file.exists():
        host_hub = ""
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()
                env[key] = value
                if key == "AGENTP2P_HUB_URL_HOST":
                    host_hub = value
        # 容器外跑 bridge 时无法解析 portalN，改用宿主机映射端口连 Portal
        if host_hub:
            env["AGENTP2P_HUB_URL"] = host_hub

    bridge_py = Path(__file__).resolve().parents[2] / "local" / "bridge.py"
    with open(log_file, "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(bridge_py)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )

    pid_file.write_text(str(process.pid), encoding="utf-8")
    print(f"Bridge started (PID: {process.pid})")
    print(f"log: {log_file}")


def stop(env_name=None, env_index=None):
    pid_file, _, _ = get_runtime_paths(env_name=env_name, env_index=env_index)
    pid = get_pid(pid_file)
    if not pid:
        print("Bridge not running")
        return

    os.kill(pid, signal.SIGTERM)
    for _ in range(10):
        if not is_running(pid):
            break
        time.sleep(0.5)
    if is_running(pid):
        os.kill(pid, signal.SIGKILL)
    pid_file.unlink(missing_ok=True)
    print("Bridge stopped")


def status(env_name=None, env_index=None):
    pid_file, log_file, _ = get_runtime_paths(env_name=env_name, env_index=env_index)
    pid = get_pid(pid_file)
    if pid and is_running(pid):
        print(f"Bridge running (PID: {pid})")
    else:
        print("Bridge not running")

    status_file = Path(__file__).resolve().parents[2] / "skill_status.json"
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            print(f"status: {data.get('status')}")
            print(f"message: {data.get('message')}")
        except Exception:
            pass

    if log_file.exists():
        lines = log_file.read_text(encoding="utf-8").splitlines()[-5:]
        print("recent logs:")
        for line in lines:
            if line.strip():
                print(f"  {line}")


def restart(env_name=None, env_index=None):
    stop(env_name=env_name, env_index=env_index)
    time.sleep(1)
    start(env_name=env_name, env_index=env_index)


def main():
    parser = argparse.ArgumentParser(description="Development bridge manager.")
    parser.add_argument("command", choices=["start", "stop", "restart", "status"])
    parser.add_argument("--env", help="environment name, e.g. env1")
    parser.add_argument("--env-index", type=int, help="environment index, e.g. 1")
    args = parser.parse_args()

    if not args.env and not args.env_index:
        parser.error("must provide --env or --env-index")

    kwargs = {"env_name": args.env, "env_index": args.env_index}
    if args.command == "start":
        start(**kwargs)
    elif args.command == "stop":
        stop(**kwargs)
    elif args.command == "restart":
        restart(**kwargs)
    else:
        status(**kwargs)


if __name__ == "__main__":
    main()
