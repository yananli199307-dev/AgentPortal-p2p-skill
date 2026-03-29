#!/usr/bin/env python3
"""
Agent P2P Client 启动脚本
"""
import asyncio
import sys
import os

# 添加 client 到路径
sys.path.insert(0, os.path.dirname(__file__))

from client import get_client
from config import is_configured, set_portal_url, set_api_key

async def main():
    """主函数"""
    if not is_configured():
        print("[Agent P2P] 未配置，请先配置门户地址和 API Key")
        print("配置方法：")
        print("  python3 client/configure.py")
        return
    
    print("[Agent P2P] 启动客户端...")
    client = get_client()
    
    # 启动连接（自动重连）
    try:
        await client.run()
    except KeyboardInterrupt:
        print("\n[Agent P2P] 客户端已停止")

if __name__ == "__main__":
    asyncio.run(main())
