#!/usr/bin/env python3
"""
Agent P2P Client 配置脚本
"""
import sys
import os

# 添加 client 到路径
sys.path.insert(0, os.path.dirname(__file__))

from config import set_portal_url, set_api_key, get_portal_url, get_api_key, is_configured

def main():
    print("="*50)
    print("Agent P2P Client 配置")
    print("="*50)
    
    # 显示当前配置
    if is_configured():
        print(f"\n当前配置:")
        print(f"  门户地址: {get_portal_url()}")
        print(f"  API Key: {get_api_key()[:20]}...")
    else:
        print("\n当前未配置")
    
    print("\n请输入配置信息:")
    
    # 输入门户地址
    portal_url = input("门户地址 (如 https://your-portal.com): ").strip()
    if not portal_url:
        print("错误: 门户地址不能为空")
        return
    
    # 输入 API Key
    api_key = input("API Key: ").strip()
    if not api_key:
        print("错误: API Key 不能为空")
        return
    
    # 保存配置
    set_portal_url(portal_url)
    set_api_key(api_key)
    
    print("\n✅ 配置已保存!")
    print(f"  门户地址: {portal_url}")
    print(f"  API Key: {api_key[:20]}...")

if __name__ == "__main__":
    main()
