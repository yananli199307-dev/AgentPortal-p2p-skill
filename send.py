#!/usr/bin/env python3
"""
Agent P2P 发送工具 - 统一版
支持发送消息和文件

用法：
    # 发送消息
    python3 send.py -m "消息内容" -t 4
    
    # 发送文件
    python3 send.py -f /path/to/file -t 4
    
    # 查看联系人
    python3 send.py --contacts
"""

import os
import sys
import argparse
import requests
from pathlib import Path


def get_config():
    """获取配置"""
    api_key = os.environ.get("AGENTP2P_API_KEY")
    hub_url = os.environ.get("AGENTP2P_HUB_URL", "https://your-domain.com")
    
    # 尝试从 gateway.env 读取
    if not api_key or not hub_url:
        gateway_env = Path.home() / ".openclaw" / "gateway.env"
        if gateway_env.exists():
            for line in gateway_env.read_text().splitlines():
                if line.startswith("AGENTP2P_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                elif line.startswith("AGENTP2P_HUB_URL="):
                    hub_url = line.split("=", 1)[1].strip()
    
    return api_key, hub_url


def get_contact(api_key, hub_url, contact_id):
    """获取联系人信息"""
    resp = requests.get(
        f"{hub_url}/api/contacts",
        headers={"Authorization": f"Bearer {api_key}"},
        verify=False
    )
    contacts = resp.json().get("contacts", [])
    for c in contacts:
        if c.get("id") == contact_id:
            return c
    return None


def send_message(api_key, hub_url, contact_id, content):
    """发送消息
    
    1. POST 到对方 Portal (/api/message/receive)
    2. POST 到自己的 Portal (/api/message/sent) [记录备份]
    """
    contact = get_contact(api_key, hub_url, contact_id)
    if not contact:
        print(f"❌ 联系人 {contact_id} 不存在")
        return False
    
    to_portal = contact.get("portal_url")
    shared_key = contact.get("SHARED_KEY")
    
    if not to_portal or not shared_key:
        print("❌ 联系人信息不完整")
        return False
    
    # 1. 发送到对方 Portal
    resp = requests.post(
        f"{to_portal}/api/message/receive",
        json={
            "api_key": shared_key,
            "from_portal": hub_url,
            "content": content,
            "message_type": "text"
        },
        verify=False
    )
    
    if resp.status_code != 200:
        print(f"❌ 发送到对方 Portal 失败: {resp.status_code}")
        return False
    
    message_id = resp.json().get('message_id')
    print(f"✅ 已发送到对方 Portal (message_id: {message_id})")
    
    # 2. 记录到自己的 Portal (备份)
    try:
        resp_backup = requests.post(
            f"{hub_url}/api/message/sent",
            json={
                "api_key": api_key,
                "to_portal": to_portal,
                "content": content,
                "message_type": "text"
            },
            verify=False
        )
        if resp_backup.status_code == 200:
            print(f"✅ 已记录到自己的 Portal")
        else:
            print(f"⚠️ 记录到自己的 Portal 失败: {resp_backup.status_code} - {resp_backup.text}")
    except Exception as e:
        print(f"⚠️ 备份消息失败: {e}")
    
    return True


import hashlib
import base64
import math

CHUNK_SIZE = 10 * 1024 * 1024  # 10MB 分片大小


def calculate_md5(file_path: str) -> str:
    """计算文件MD5"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def calculate_chunk_md5(data: bytes) -> str:
    """计算分片MD5"""
    return hashlib.md5(data).hexdigest()


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"


def send_file(api_key, hub_url, contact_id, file_path):
    """发送文件（简化版：直接上传到接收方 Portal）"""
    import requests
    from pathlib import Path
    
    # 获取联系人信息
    contact = get_contact(api_key, hub_url, contact_id)
    if not contact:
        print(f"❌ 联系人 {contact_id} 不存在")
        return False
    
    to_portal = contact.get("portal_url")
    shared_key = contact.get("SHARED_KEY")
    
    if not to_portal or not shared_key:
        print("❌ 联系人信息不完整")
        return False
    
    file_path = Path(file_path)
    filename = file_path.name
    file_size = file_path.stat().st_size
    file_md5 = calculate_md5(str(file_path))
    chunks_total = math.ceil(file_size / CHUNK_SIZE)
    
    print(f"📤 准备发送文件: {filename}")
    print(f"   大小: {format_size(file_size)}")
    print(f"   分片: {chunks_total} 个")
    
    # 1. 初始化文件传输（直接上传到接收方 Portal）
    try:
        resp = requests.post(
            f"{to_portal}/api/file/initiate",
            json={
                "api_key": shared_key,
                "filename": filename,
                "size": file_size,
                "md5": file_md5,
                "chunk_size": CHUNK_SIZE,
                "chunks_total": chunks_total,
                "to_portal": to_portal
            },
            verify=False,
            timeout=30
        )
        
        if resp.status_code != 200:
            print(f"❌ 初始化传输失败: {resp.status_code}")
            return False
        
        result = resp.json()
        file_id = result.get("file_id")
        print(f"✅ 传输已初始化 (file_id: {file_id[:20]}...)")
        
    except Exception as e:
        print(f"❌ 初始化传输失败: {e}")
        return False
    
    # 2. 上传文件分片
    try:
        with open(file_path, "rb") as f:
            for chunk_index in range(chunks_total):
                chunk_data = f.read(CHUNK_SIZE)
                chunk_md5 = calculate_chunk_md5(chunk_data)
                
                # 上传分片（上传到接收方 Portal）
                resp = requests.post(
                    f"{to_portal}/api/file/chunk/{file_id}/{chunk_index}",
                    json={
                        "api_key": shared_key,
                        "file_id": file_id,
                        "chunk_index": chunk_index,
                        "chunk_md5": chunk_md5,
                        "data": base64.b64encode(chunk_data).decode()
                    },
                    verify=False,
                    timeout=60
                )
                
                if resp.status_code != 200:
                    print(f"❌ 上传分片 {chunk_index} 失败: {resp.status_code}")
                    return False
                
                progress = (chunk_index + 1) / chunks_total * 100
                print(f"\r   上传进度: {progress:.1f}%", end="", flush=True)
        
        print(f"\n✅ 文件上传完成")
        print(f"   文件ID: {file_id}")
        
        # 3. 记录到自己的 Portal (备份)
        try:
            resp_backup = requests.post(
                f"{hub_url}/api/file/sent",
                json={
                    "api_key": api_key,
                    "to_portal": to_portal,
                    "filename": filename,
                    "file_id": file_id,
                    "file_size": file_size
                },
                verify=False
            )
            if resp_backup.status_code == 200:
                print(f"✅ 已记录到自己的 Portal")
            else:
                print(f"⚠️ 记录到自己的 Portal 失败: {resp_backup.status_code}")
        except Exception as e:
            print(f"⚠️ 备份文件记录失败: {e}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 上传文件失败: {e}")
        return False


def list_contacts(api_key, hub_url):
    """列出联系人"""
    resp = requests.get(
        f"{hub_url}/api/contacts",
        headers={"Authorization": f"Bearer {api_key}"},
        verify=False
    )
    contacts = resp.json().get("contacts", [])
    print(f"📇 联系人 ({len(contacts)}个):")
    for c in contacts:
        print(f"  ID {c.get('id')}: {c.get('name', 'Unknown')} ({c.get('portal_url', 'N/A')})")
    return contacts


def main():
    parser = argparse.ArgumentParser(description="Agent P2P 发送工具")
    parser.add_argument("-m", "--message", help="发送消息内容")
    parser.add_argument("-f", "--file", help="发送文件路径")
    parser.add_argument("-t", "--to", type=int, help="联系人ID")
    parser.add_argument("--contacts", action="store_true", help="列出联系人")
    
    args = parser.parse_args()
    
    # 获取配置
    api_key, hub_url = get_config()
    if not api_key:
        print("❌ AGENTP2P_API_KEY 未设置")
        sys.exit(1)
    
    # 列出联系人
    if args.contacts:
        list_contacts(api_key, hub_url)
        return
    
    # 检查必要参数
    if not args.to:
        print("❌ 必须指定联系人ID: -t <id>")
        parser.print_help()
        sys.exit(1)
    
    # 发送消息
    if args.message:
        send_message(api_key, hub_url, args.to, args.message)
    
    # 发送文件
    elif args.file:
        if not Path(args.file).exists():
            print(f"❌ 文件不存在: {args.file}")
            sys.exit(1)
        send_file(api_key, hub_url, args.to, args.file)
    
    else:
        print("❌ 必须指定 -m (消息) 或 -f (文件)")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
