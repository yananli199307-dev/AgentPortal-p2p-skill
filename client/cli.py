#!/usr/bin/env python3
"""
Agent P2P Client 命令行工具
"""
import sys
import os

# 添加 client 到路径
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from client import get_client
from config import is_configured, set_portal_url, set_api_key, get_portal_url, get_api_key

async def send_message(to_portal, content):
    """发送消息"""
    if not is_configured():
        print("[Agent P2P] 未配置，请先运行: python3 scripts/configure.py")
        return
    
    client = get_client()
    client.portal_url = get_portal_url()
    client.api_key = get_api_key()
    
    result = await client.send_message(to_portal, content)
    if result:
        print(f"[Agent P2P] 消息已发送: {result}")
    else:
        print("[Agent P2P] 发送失败")

async def list_messages():
    """查看留言"""
    if not is_configured():
        print("[Agent P2P] 未配置")
        return
    
    client = get_client()
    client.portal_url = get_portal_url()
    client.api_key = get_api_key()
    
    result = await client.get_guest_messages()
    if result:
        messages = result.get('messages', [])
        print(f"\n📨 共有 {len(messages)} 条留言:\n")
        for msg in messages:
            print(f"  [{msg['id']}] {msg['created_at']}")
            print(f"      {msg['content'][:100]}...")
            print()
    else:
        print("[Agent P2P] 获取留言失败")

async def show_help():
    """显示帮助"""
    print("""
Agent P2P Client 命令行工具

用法:
  python3 scripts/cli.py send <portal_url> <message>  发送消息
  python3 scripts/cli.py messages                      查看留言
  python3 scripts/cli.py help                          显示帮助

示例:
  python3 scripts/cli.py send https://example.com "你好！"
""")

async def main():
    if len(sys.argv) < 2:
        await show_help()
        return
    
    command = sys.argv[1]
    
    if command == "send" and len(sys.argv) >= 4:
        to_portal = sys.argv[2]
        content = " ".join(sys.argv[3:])
        await send_message(to_portal, content)
    elif command == "messages":
        await list_messages()
    elif command == "help":
        await show_help()
    else:
        await show_help()

if __name__ == "__main__":
    asyncio.run(main())
