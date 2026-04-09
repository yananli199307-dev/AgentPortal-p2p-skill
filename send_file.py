#!/usr/bin/env python3
"""
Agent P2P 文件传输客户端
支持分片上传、断点续传、进度显示
"""

import os
import sys
import json
import base64
import hashlib
import requests
from pathlib import Path
from typing import Optional, Callable
import math

# 配置
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB 分片大小
MAX_RETRIES = 3  # 单分片最大重试次数


def get_config():
    """获取配置"""
    api_key = os.environ.get("AGENTP2P_API_KEY")
    hub_url = os.environ.get("AGENTP2P_HUB_URL")
    
    if not api_key or not hub_url:
        # 尝试从 gateway.env 读取
        gateway_env = Path.home() / ".openclaw" / "gateway.env"
        if gateway_env.exists():
            for line in gateway_env.read_text().splitlines():
                if line.startswith("AGENTP2P_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                elif line.startswith("AGENTP2P_HUB_URL="):
                    hub_url = line.split("=", 1)[1].strip()
    
    return api_key, hub_url


def get_contact(contact_id: int, api_key: str, hub_url: str):
    """获取联系人信息"""
    try:
        resp = requests.get(
            f"{hub_url}/api/contacts",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if resp.status_code == 200:
            contacts = resp.json().get("contacts", [])
            for c in contacts:
                if c.get("id") == contact_id:
                    return c
        return None
    except Exception as e:
        print(f"获取联系人失败: {e}")
        return None


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


def initiate_transfer(api_key: str, hub_url: str, filename: str, 
                     file_size: int, file_md5: str, chunks_total: int) -> Optional[str]:
    """初始化文件传输，返回 file_id"""
    try:
        resp = requests.post(
            f"{hub_url}/api/file/initiate",
            json={
                "api_key": api_key,
                "filename": filename,
                "size": file_size,
                "md5": file_md5,
                "chunk_size": CHUNK_SIZE,
                "chunks_total": chunks_total
            },
            timeout=30
        )
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ 文件传输已初始化: {result.get('file_id')}")
            print(f"   状态: {result.get('message')}")
            return result.get("file_id")
        else:
            print(f"❌ 初始化失败: {resp.status_code} - {resp.text}")
            return None
            
    except Exception as e:
        print(f"❌ 初始化传输失败: {e}")
        return None


def upload_chunk(api_key: str, hub_url: str, file_id: str, chunk_index: int, 
                chunk_data: bytes, max_retries: int = MAX_RETRIES) -> bool:
    """上传单个分片，支持重试"""
    chunk_md5 = calculate_chunk_md5(chunk_data)
    chunk_base64 = base64.b64encode(chunk_data).decode('utf-8')
    
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{hub_url}/api/file/chunk/{file_id}/{chunk_index}",
                json={
                    "api_key": api_key,
                    "file_id": file_id,
                    "chunk_index": chunk_index,
                    "chunk_md5": chunk_md5,
                    "data": chunk_base64
                },
                timeout=60
            )
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get("status") in ["received", "exists"]:
                    return True
            
            print(f"   分片 {chunk_index} 上传失败 (尝试 {attempt + 1}/{max_retries}): {resp.status_code}")
            
        except Exception as e:
            print(f"   分片 {chunk_index} 上传异常 (尝试 {attempt + 1}/{max_retries}): {e}")
    
    return False


def send_file(file_path: str, to_contact: int, progress_callback: Optional[Callable] = None):
    """发送文件到指定联系人"""
    # 获取配置
    api_key, hub_url = get_config()
    if not api_key or not hub_url:
        print("❌ 配置不完整，请检查环境变量或 gateway.env")
        return False
    
    # 检查文件
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    if not file_path.is_file():
        print(f"❌ 不是文件: {file_path}")
        return False
    
    # 获取联系人信息
    contact = get_contact(to_contact, api_key, hub_url)
    if not contact:
        print(f"❌ 找不到联系人: {to_contact}")
        return False
    
    to_portal = contact.get("portal_url")
    contact_name = contact.get("agent_name", to_portal)
    
    print(f"📤 准备发送文件到: {contact_name}")
    print(f"   文件: {file_path.name}")
    
    # 计算文件信息
    file_size = file_path.stat().st_size
    file_md5 = calculate_md5(str(file_path))
    chunks_total = math.ceil(file_size / CHUNK_SIZE)
    
    print(f"   大小: {file_size / 1024 / 1024:.2f} MB")
    print(f"   MD5: {file_md5}")
    print(f"   分片: {chunks_total} 个 ({CHUNK_SIZE / 1024 / 1024:.0f}MB/片)")
    
    # 初始化传输
    file_id = initiate_transfer(api_key, hub_url, file_path.name, 
                               file_size, file_md5, chunks_total)
    if not file_id:
        return False
    
    print(f"\n⏳ 等待接收方确认...")
    print(f"   文件ID: {file_id}")
    print(f"   对方需要运行: python3 send_file.py --confirm {file_id} --accept")
    
    return True


def confirm_transfer(file_id: str, accept: bool):
    """确认或拒绝文件传输"""
    api_key, hub_url = get_config()
    if not api_key or not hub_url:
        print("❌ 配置不完整")
        return False
    
    try:
        resp = requests.post(
            f"{hub_url}/api/file/confirm",
            json={
                "api_key": api_key,
                "file_id": file_id,
                "accept": accept
            },
            timeout=10
        )
        
        if resp.status_code == 200:
            result = resp.json()
            if accept:
                print(f"✅ 已接受文件传输: {file_id}")
                print(f"   等待对方上传文件...")
            else:
                print(f"❌ 已拒绝文件传输: {file_id}")
            return True
        else:
            print(f"❌ 确认失败: {resp.status_code} - {resp.text}")
            return False
            
    except Exception as e:
        print(f"❌ 确认传输失败: {e}")
        return False


def upload_file_chunks(file_id: str, file_path: str):
    """上传文件分片（在接收方确认后调用）"""
    api_key, hub_url = get_config()
    if not api_key or not hub_url:
        print("❌ 配置不完整")
        return False
    
    # 检查文件
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    # 查询传输状态
    try:
        resp = requests.get(
            f"{hub_url}/api/file/status/{file_id}",
            params={"api_key": api_key},
            timeout=10
        )
        
        if resp.status_code != 200:
            print(f"❌ 查询传输状态失败: {resp.status_code}")
            return False
        
        status = resp.json()
        if status.get("status") != "transferring":
            print(f"❌ 传输状态不是 transferring: {status.get('status')}")
            return False
        
        filename = status.get("filename")
        chunks_total = status.get("chunks_total")
        received_chunks = set(status.get("received_chunks", []))
        
        print(f"📤 开始上传文件分片: {filename}")
        print(f"   总分片: {chunks_total}, 已接收: {len(received_chunks)}, 待上传: {chunks_total - len(received_chunks)}")
        
        # 上传缺失的分片
        success_count = 0
        fail_count = 0
        
        with open(file_path, "rb") as f:
            for chunk_index in range(chunks_total):
                if chunk_index in received_chunks:
                    continue  # 跳过已上传的分片
                
                # 读取分片数据
                f.seek(chunk_index * CHUNK_SIZE)
                chunk_data = f.read(CHUNK_SIZE)
                
                # 上传分片
                print(f"   上传分片 {chunk_index + 1}/{chunks_total}...", end=" ")
                if upload_chunk(api_key, hub_url, file_id, chunk_index, chunk_data):
                    print("✅")
                    success_count += 1
                else:
                    print("❌")
                    fail_count += 1
                    if fail_count > 3:  # 允许最多3个分片失败
                        print(f"\n❌ 上传失败分片过多，中断传输")
                        return False
        
        print(f"\n✅ 分片上传完成: 成功 {success_count}, 失败 {fail_count}")
        print(f"   等待服务器合并文件...")
        return True
        
    except Exception as e:
        print(f"❌ 上传分片失败: {e}")
        return False


def check_transfer_status(file_id: str):
    """查询文件传输状态"""
    api_key, hub_url = get_config()
    if not api_key or not hub_url:
        print("❌ 配置不完整")
        return

    try:
        resp = requests.get(
            f"{hub_url}/api/file/status/{file_id}",
            params={"api_key": api_key},
            timeout=10
        )

        if resp.status_code == 200:
            status = resp.json()
            print(f"📋 文件传输状态:")
            print(f"   文件ID: {status.get('file_id')}")
            print(f"   文件名: {status.get('filename')}")
            print(f"   大小: {status.get('size', 0) / 1024 / 1024:.2f} MB")
            print(f"   状态: {status.get('status')}")
            print(f"   分片: {status.get('chunks_received')}/{status.get('chunks_total')}")
            print(f"   发送方: {status.get('from_portal')}")
            print(f"   接收方: {status.get('to_portal')}")
        else:
            print(f"❌ 查询失败: {resp.status_code} - {resp.text}")

    except Exception as e:
        print(f"❌ 查询状态失败: {e}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Agent P2P 文件传输工具")
    parser.add_argument("--file", "-f", help="要发送的文件路径")
    parser.add_argument("--to-contact", "-t", type=int, help="接收方联系人ID")
    parser.add_argument("--confirm", help="确认文件传输（file_id）")
    parser.add_argument("--accept", action="store_true", help="接受传输")
    parser.add_argument("--reject", action="store_true", help="拒绝传输")
    parser.add_argument("--upload", help="上传分片（file_id）")
    parser.add_argument("--resume", action="store_true", help="断点续传模式")
    parser.add_argument("--status", help="查询传输状态（file_id）")
    parser.add_argument("--download", help="下载文件（file_id）")
    parser.add_argument("--output", "-o", help="下载保存路径")

    args = parser.parse_args()

    if args.download:
        # 下载文件
        output = args.output or "."
        download_file(args.download, output)
    elif args.status:
        # 查询状态
        check_transfer_status(args.status)
    elif args.confirm:
        # 确认/拒绝传输
        if args.accept:
            confirm_transfer(args.confirm, True)
        elif args.reject:
            confirm_transfer(args.confirm, False)
        else:
            print("请指定 --accept 或 --reject")
    elif args.upload and args.file:
        # 上传分片
        upload_file_chunks(args.upload, args.file)
    elif args.file and args.to_contact:
        # 发送文件
        send_file(args.file, args.to_contact)
    else:
        parser.print_help()
        print("\n示例:")
        print("  # 1. 发送文件（初始化传输）")
        print("  python3 send_file.py -f document.pdf -t 1")
        print("")
        print("  # 2. 接收方确认")
        print("  python3 send_file.py --confirm <file_id> --accept")
        print("")
        print("  # 3. 发送方上传分片")
        print("  python3 send_file.py --upload <file_id> -f document.pdf")
        print("")
        print("  # 4. 接收方下载文件")
        print("  python3 send_file.py --download <file_id> -o ./downloads/")
        print("")
        print("  # 5. 查询传输状态")
        print("  python3 send_file.py --status <file_id>")


if __name__ == "__main__":
    main()

def download_file(file_id: str, output_path: str):
    """下载完整文件"""
    api_key, hub_url = get_config()
    if not api_key or not hub_url:
        print("❌ 配置不完整")
        return False
    
    try:
        # 查询传输状态
        resp = requests.get(
            f"{hub_url}/api/file/status/{file_id}",
            params={"api_key": api_key},
            timeout=10
        )
        
        if resp.status_code != 200:
            print(f"❌ 查询传输状态失败: {resp.status_code}")
            return False
        
        status = resp.json()
        if status.get("status") != "completed":
            print(f"❌ 文件未准备好，状态: {status.get('status')}")
            return False
        
        filename = status.get("filename")
        file_size = status.get("size")
        
        print(f"📥 开始下载文件: {filename}")
        print(f"   大小: {format_size(file_size)}")
        
        # 下载文件
        resp = requests.get(
            f"{hub_url}/api/file/download/{file_id}",
            params={"api_key": api_key},
            stream=True,
            timeout=300
        )
        
        if resp.status_code != 200:
            print(f"❌ 下载失败: {resp.status_code}")
            return False
        
        # 保存文件
        output_path = Path(output_path)
        if output_path.is_dir():
            output_path = output_path / filename
        
        with open(output_path, "wb") as f:
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if file_size > 0:
                        print_progress(downloaded, file_size, "下载进度")
        
        print(f"\n✅ 文件已保存: {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ 下载文件失败: {e}")
        return False
