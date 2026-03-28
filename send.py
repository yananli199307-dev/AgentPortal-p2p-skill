#!/usr/bin/env python3
"""
Agent P2P 消息发送工具

用法：
    # 发送给指定 Agent
    venv/bin/python3 send.py "Hello" --to-agent <agent_id>
    
    # 发送给指定用户
    venv/bin/python3 send.py "Hello" --to-user <user_id>
    
    # 发送到群聊
    venv/bin/python3 send.py "Hello" --group <group_id>
    
    # 回复某条消息
    venv/bin/python3 send.py "Reply" --reply-to <message_id>
"""

import os
import sys
import json
import argparse
from pathlib import Path

import requests


def get_config():
    """获取配置"""
    token = os.environ.get("AGENTP2P_TOKEN")
    hub_url = os.environ.get("AGENTP2P_HUB_URL", "https://your-domain.com")
    
    if not token:
        # 尝试从 gateway.env 读取
        gateway_env = Path.home() / ".openclaw" / "gateway.env"
        if gateway_env.exists():
            for line in gateway_env.read_text().splitlines():
                if line.startswith("AGENTP2P_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("AGENTP2P_HUB_URL="):
                    hub_url = line.split("=", 1)[1].strip()
    
    return token, hub_url


def send_message(content: str, to_agent: str = None, to_user: str = None, 
                 group_id: str = None, reply_to: str = None):
    """发送消息"""
    token, hub_url = get_config()
    
    if not token:
        print("❌ AGENTP2P_TOKEN 未设置")
        print("请设置环境变量或在 ~/.openclaw/gateway.env 中配置")
        sys.exit(1)
    
    # 构建请求
    url = f"{hub_url}/api/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    data = {"content": content}
    
    if to_agent:
        data["to_agent_id"] = to_agent
    elif to_user:
        data["to_user_id"] = to_user
    elif group_id:
        data["group_id"] = group_id
    else:
        print("❌ 必须指定接收者: --to-agent, --to-user, 或 --group")
        sys.exit(1)
    
    if reply_to:
        data["reply_to_id"] = reply_to
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ 消息已发送: {result.get('id', 'unknown')}")
            return result
        else:
            print(f"❌ 发送失败: {resp.status_code}")
            print(resp.text)
            sys.exit(1)
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        sys.exit(1)


def list_contacts():
    """列出联系人"""
    token, hub_url = get_config()
    
    if not token:
        print("❌ AGENTP2P_TOKEN 未设置")
        sys.exit(1)
    
    url = f"{hub_url}/api/contacts"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            contacts = resp.json()
            print(f"📇 联系人 ({len(contacts)}个):")
            for c in contacts:
                print(f"  - {c.get('name', 'Unknown')} ({c.get('id', 'unknown')[:8]}...)")
            return contacts
        else:
            print(f"❌ 获取失败: {resp.status_code}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        sys.exit(1)


def list_groups():
    """列出群聊"""
    token, hub_url = get_config()
    
    if not token:
        print("❌ AGENTP2P_TOKEN 未设置")
        sys.exit(1)
    
    url = f"{hub_url}/api/groups"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            groups = resp.json()
            print(f"👥 群聊 ({len(groups)}个):")
            for g in groups:
                print(f"  - {g.get('name', 'Unknown')} ({g.get('id', 'unknown')[:8]}...)")
            return groups
        else:
            print(f"❌ 获取失败: {resp.status_code}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Agent P2P 消息发送工具")
    parser.add_argument("content", nargs="?", help="消息内容")
    parser.add_argument("--to-agent", help="发送给指定 Agent")
    parser.add_argument("--to-user", help="发送给指定用户")
    parser.add_argument("--group", help="发送到群聊")
    parser.add_argument("--reply-to", help="回复某条消息")
    parser.add_argument("--contacts", action="store_true", help="列出联系人")
    parser.add_argument("--groups", action="store_true", help="列出群聊")
    
    args = parser.parse_args()
    
    if args.contacts:
        list_contacts()
    elif args.groups:
        list_groups()
    elif args.content:
        send_message(
            args.content,
            to_agent=args.to_agent,
            to_user=args.to_user,
            group_id=args.group,
            reply_to=args.reply_to
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
