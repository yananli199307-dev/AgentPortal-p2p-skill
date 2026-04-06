from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, File, UploadFile, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
import sqlite3
import json
import secrets
import hashlib
from datetime import datetime, timedelta
import pytz
import os

app = FastAPI(title="Agent P2P Portal")

# 配置
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/portal.db")

# 时区设置
TZ = pytz.timezone('Asia/Shanghai')

def get_now():
    """获取当前北京时间"""
    return datetime.now(TZ)

def format_datetime(dt):
    """格式化日期时间为北京时间字符串"""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    # 转换为北京时间
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')

# 确保数据目录存在
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

# 数据库初始化

def get_table_columns(cursor, table_name):
    """获取表的列名"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]

def run_migrations():
    """数据库迁移脚本（只新增/重命名，不删除）"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        # 迁移 contacts 表
        columns = get_table_columns(cursor, 'contacts')
        
        # 1. 新增 SHARED_KEY 列（如果不存在）
        if 'SHARED_KEY' not in columns:
            cursor.execute('ALTER TABLE contacts ADD COLUMN SHARED_KEY TEXT')
            print("Added column: SHARED_KEY")
        
        # 2. 重命名 display_name（如果需要）
        if 'display_name' in columns and 'DISPLAY_NAME' not in columns:
            cursor.execute('ALTER TABLE contacts RENAME COLUMN display_name TO DISPLAY_NAME')
            print("Renamed column: display_name -> DISPLAY_NAME")
        
        # 迁移 api_keys 表
        api_keys_columns = get_table_columns(cursor, 'api_keys')
        
        if 'description' not in api_keys_columns:
            cursor.execute('ALTER TABLE api_keys ADD COLUMN description TEXT')
            print("Added column: description")
        
        conn.commit()
        print("数据库迁移完成")
    except Exception as e:
        print(f"迁移跳过: {e}")
        conn.rollback()
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 匿名留言表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guest_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT FALSE,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    # 联系人表（已验证）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portal_url TEXT UNIQUE NOT NULL,
            display_name TEXT,
            agent_name TEXT,
            user_name TEXT,
            SHARED_KEY TEXT NOT NULL,  -- 共享的 Key，双方都用此发消息
            is_verified BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    
    # 消息表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_portal TEXT NOT NULL,
            to_portal TEXT NOT NULL,
            content TEXT NOT NULL,
            message_type TEXT DEFAULT 'text',
            sender_api_key TEXT,        -- 发送方使用的API Key，用于验证身份
            file_url TEXT,
            is_delivered BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    # API Keys 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            key_id TEXT PRIMARY KEY,
            portal_url TEXT NOT NULL,
            agent_name TEXT,
            user_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# 运行数据库迁移
run_migrations()

# 数据模型
class GuestMessageRequest(BaseModel):
    content: str

class MessageHistoryRequest(BaseModel):
    contact_portal: str
    limit: int = 50
    offset: int = 0

class SendMessageRequest(BaseModel):
    contact_id: int                 # 联系人ID，系统会自动使用我给对方的API Key
    content: str
    message_type: str = "text"

class ApiKeyCreateRequest(BaseModel):
    portal_url: str
    agent_name: Optional[str] = None
    user_name: Optional[str] = None

class ApiKeyExchangeRequest(BaseModel):
    portal_url: str
    SHARED_KEY: str  # 共享的 Key

class ReceiveMessageRequest(BaseModel):
    """接收来自其他 Agent 的消息"""
    api_key: str           # 共享的 Key
    from_portal: str       # 发送方 Portal URL
    content: str
    message_type: str = "text"

# 工具函数
def generate_api_key() -> str:
    """生成随机 API Key"""
    return "ap2p_" + secrets.token_urlsafe(32)

def verify_api_key(api_key: str) -> Optional[str]:
    """验证 API Key，返回对应的 portal_url
    
    检查两个地方：
    1. api_keys 表 - 我自己生成的 Key（用于 WebSocket 连接）
    2. contacts.SHARED_KEY - 共享 Key（双方都用此发消息）
    """
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # 1. 检查是否是我自己的 Key
        cursor.execute('''
            SELECT portal_url FROM api_keys 
            WHERE key_id = ? AND is_active = TRUE
        ''', (api_key,))
        
        result = cursor.fetchone()
        if result:
            return result[0]
        
        # 2. 检查是否是共享 Key
        cursor.execute('''
            SELECT portal_url FROM contacts 
            WHERE SHARED_KEY = ?
        ''', (api_key,))
        
        result = cursor.fetchone()
        if result:
            return result[0]
        
        return None
    finally:
        if conn:
            conn.close()

def get_my_portal_url() -> str:
    """获取当前 Portal 的 URL（从环境变量或配置）"""
    return os.getenv("PORTAL_URL", "")

# API 路由

async def notify_openclaw(content: str, message_type: str = "guest_message"):
    """发送通知到 OpenClaw
    
    当前实现：记录到待通知队列，由 Agent 通过心跳检查拉取
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # 保存到待通知表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                portal TEXT NOT NULL,
                is_notified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            INSERT INTO pending_notifications (type, content, portal)
            VALUES (?, ?, ?)
        ''', (message_type, content, get_my_portal_url()))
        
        conn.commit()
        conn.close()
        print(f"[OpenClaw Notify] Queued: {content[:50]}...")
    except Exception as e:
        print(f"[OpenClaw Notify] Failed: {e}")

@app.post("/api/guest/leave-message")
async def leave_message(request: GuestMessageRequest, request_obj: Request):
    """匿名留言"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO guest_messages (content, ip_address, user_agent, created_at)
        VALUES (?, ?, ?, ?)
    ''', (request.content, request_obj.client.host, request_obj.headers.get("user-agent"), get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # 广播新留言给所有连接的 Agent（通知主人，不自动处理）
    await manager.broadcast({
        "type": "new_guest_message",
        "message_id": message_id,
        "content": request.content[:100],
        "created_at": get_now().isoformat(),
        "requires_approval": True  # 标记需要主人审批
    })
    
    # 发送 OpenClaw 通知（提示主人需要审批）
    await notify_openclaw(
        f"📨 收到新留言（等待审批）:\n{request.content[:200]}\n\n"
        f"回复以下指令处理:\n"
        f"- 同意添加: 同意 {message_id}\n"
        f"- 拒绝添加: 拒绝 {message_id}\n"
        f"- 仅标记已读: 已读 {message_id}",
        "guest_message"
    )
    
    return {"status": "ok", "message_id": message_id}

@app.get("/api/guest/messages")
async def get_guest_messages():
    """获取匿名留言列表"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, content, created_at, is_read, status 
        FROM guest_messages 
        ORDER BY created_at DESC
    ''')
    
    messages = cursor.fetchall()
    conn.close()
    
    return {
        "messages": [
            {"id": m[0], "content": m[1], "created_at": m[2], "is_read": m[3], "status": m[4] or 'pending'}
            for m in messages
        ]
    }

@app.post("/api/guest/messages/{message_id}/status")
async def update_message_status(message_id: int, request: Request):
    """更新留言状态（approved/rejected/read）"""
    data = await request.json()
    status = data.get('status')
    
    if status not in ['approved', 'rejected', 'read']:
        raise HTTPException(status_code=400, detail="Invalid status. Must be 'approved', 'rejected', or 'read'")
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # read 状态只标记已读，不改变 status 字段
    if status == 'read':
        cursor.execute('''
            UPDATE guest_messages 
            SET is_read = TRUE 
            WHERE id = ?
        ''', (message_id,))
    else:
        # approved/rejected 更新状态并标记已读
        cursor.execute('''
            UPDATE guest_messages 
            SET status = ?, is_read = TRUE 
            WHERE id = ?
        ''', (status, message_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "updated", "message_id": message_id, "new_status": status}

@app.post("/api/guest/messages/{message_id}/approve")
async def approve_guest_message(message_id: int, request: Request):
    """
    主人审批留言：同意添加联系人并生成 API Key
    需要传入对方的 Portal URL 和联系信息
    """
    data = await request.json()
    portal_url = data.get('portal_url')
    agent_name = data.get('agent_name', 'Unknown')
    user_name = data.get('user_name', 'Unknown')
    
    if not portal_url:
        raise HTTPException(status_code=400, detail="portal_url is required")
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 检查留言是否存在
    cursor.execute('SELECT id FROM guest_messages WHERE id = ?', (message_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Message not found")
    
    # 生成 API Key
    SHARED_KEY = generate_api_key()
    
    # 保存联系人（只有一个共享 Key）
    cursor.execute('''
        INSERT OR REPLACE INTO contacts 
        (portal_url, display_name, agent_name, user_name, SHARED_KEY, is_verified, created_at)
        VALUES (?, ?, ?, ?, ?, TRUE, ?)
    ''', (
        portal_url,
        f"{agent_name} ({user_name})",
        agent_name,
        user_name,
        SHARED_KEY,
        get_now().strftime('%Y-%m-%d %H:%M:%S')
    ))
    
    # 更新留言状态为 approved
    cursor.execute('''
        UPDATE guest_messages 
        SET status = 'approved', is_read = TRUE 
        WHERE id = ?
    ''', (message_id,))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "approved",
        "message_id": message_id,
        "api_key": SHARED_KEY,
        "message": f"已添加联系人，请将此 API Key 发送给对方: {SHARED_KEY}"
    }

# ========== API Key 管理接口 ==========

@app.post("/api/key/create")
async def create_api_key(request: ApiKeyCreateRequest):
    """创建新的 API Key"""
    api_key = generate_api_key()
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO api_keys (key_id, portal_url, agent_name, user_name, created_at, is_active)
        VALUES (?, ?, ?, ?, ?, TRUE)
    ''', (api_key, request.portal_url, request.agent_name, request.user_name, get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "created",
        "api_key": api_key,
        "portal_url": request.portal_url,
        "message": "请妥善保存此 API Key，它不会再次显示"
    }

@app.get("/api/key/list")
async def list_api_keys():
    """列出所有 API Keys"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT key_id, portal_url, agent_name, user_name, created_at, is_active
        FROM api_keys
        ORDER BY created_at DESC
    ''')
    
    keys = cursor.fetchall()
    conn.close()
    
    return {
        "api_keys": [
            {
                "key_id": k[0][:20] + "...",  # 只显示前20个字符
                "portal_url": k[1],
                "agent_name": k[2],
                "user_name": k[3],
                "created_at": k[4],
                "is_active": k[5]
            }
            for k in keys
        ],
        "total": len(keys)
    }

@app.post("/api/key/revoke")
async def revoke_api_key(api_key: str):
    """撤销 API Key"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE api_keys SET is_active = FALSE WHERE key_id = ?
    ''', (api_key,))
    
    conn.commit()
    conn.close()
    
    return {"status": "revoked"}

@app.post("/api/key/exchange")
async def exchange_api_key(request: ApiKeyExchangeRequest):
    """交换 API Key（建立好友关系）"""
    my_portal = get_my_portal_url()
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 生成我的 API Key 给对方
    SHARED_KEY = generate_api_key()
    
    # 保存 API Key 到数据库
    cursor.execute('''
        INSERT INTO api_keys (key_id, portal_url, agent_name, created_at, is_active)
        VALUES (?, ?, ?, ?, TRUE)
    ''', (SHARED_KEY, request.portal_url, "friend", get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    # 保存联系人关系
    cursor.execute('''
        INSERT OR REPLACE INTO contacts 
        (portal_url, api_key, SHARED_KEY, is_verified, created_at)
        VALUES (?, ?, ?, TRUE, ?)
    ''', (request.portal_url, SHARED_KEY, request.SHARED_KEY, get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "exchanged",
        "api_key": SHARED_KEY,
        "message": "API Key 交换成功"
    }

# ========== 历史消息 API ==========

@app.get("/api/messages/history")
async def get_message_history(
    contact_portal: str,
    limit: int = 50,
    offset: int = 0,
    my_portal: str = ""
):
    """
    获取与指定联系人的消息历史
    按时间倒序排列，支持分页
    """
    if not my_portal:
        my_portal = get_my_portal_url()
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 获取总消息数
    cursor.execute('''
        SELECT COUNT(*) FROM messages 
        WHERE (from_portal = ? AND to_portal = ?) 
           OR (from_portal = ? AND to_portal = ?)
    ''', (my_portal, contact_portal, contact_portal, my_portal))
    
    total = cursor.fetchone()[0]
    
    # 获取消息列表（按时间倒序）
    cursor.execute('''
        SELECT id, from_portal, to_portal, content, message_type, created_at
        FROM messages 
        WHERE (from_portal = ? AND to_portal = ?) 
           OR (from_portal = ? AND to_portal = ?)
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', (my_portal, contact_portal, contact_portal, my_portal, limit, offset))
    
    messages = []
    for row in cursor.fetchall():
        msg_type = "sent" if row[1] == my_portal else "received"
        messages.append({
            "id": row[0],
            "type": msg_type,
            "from": row[1],
            "to": row[2],
            "content": row[3],
            "message_type": row[4],
            "created_at": row[5]
        })
    
    conn.close()
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "messages": messages
    }

async def push_message(to_portal: str, message: dict):
    """异步推送消息到 WebSocket，成功则标记为已送达"""
    try:
        await manager.send_message(to_portal, message)
        # 推送成功，标记为已送达
        message_id = message.get("id")
        if message_id:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute('UPDATE messages SET is_delivered = TRUE WHERE id = ?', (message_id,))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"WebSocket 推送失败: {e}")
        # 推送失败，保持 is_delivered = FALSE，等 Agent 上线后 sync

@app.post("/api/message/send")
async def send_message(request: SendMessageRequest, background_tasks: BackgroundTasks):
    """发送消息给指定联系人"""
    my_portal = get_my_portal_url()
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 获取联系人信息
    cursor.execute('''
        SELECT portal_url, SHARED_KEY FROM contacts WHERE id = ?
    ''', (request.contact_id,))
    contact = cursor.fetchone()
    
    if not contact:
        conn.close()
        raise HTTPException(status_code=404, detail="Contact not found")
    
    to_portal, SHARED_KEY = contact
    
    # 保存消息（使用我给对方的API Key作为发送方标识）
    cursor.execute('''
        INSERT INTO messages (from_portal, to_portal, content, message_type, sender_api_key, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (my_portal, to_portal, request.content, request.message_type, SHARED_KEY, get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # 后台推送消息
    background_tasks.add_task(push_message, to_portal, {
        "type": "message",
        "id": message_id,
        "from": my_portal,
        "api_key": SHARED_KEY,  # 让对方可以用此验证我的身份
        "content": request.content,
        "message_type": request.message_type,
        "created_at": get_now().isoformat()
    })
    
    return {"status": "delivered", "message_id": message_id}

@app.post("/api/message/receive")
async def receive_message(request: ReceiveMessageRequest, background_tasks: BackgroundTasks):
    """
    接收来自其他 Agent 的消息
    
    流程：
    1. 验证 api_key（必须是我给对方的 Key）
    2. 保存消息到数据库
    3. 通过 WebSocket 推送给我的 Agent
    """
    my_portal = get_my_portal_url()
    conn = None
    
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # 检查共享 Key
        cursor.execute('''
            SELECT portal_url, user_name, agent_name FROM contacts 
            WHERE SHARED_KEY = ?
        ''', (request.api_key,))
        
        contact = cursor.fetchone()
        
        if not contact:
            raise HTTPException(status_code=401, detail="Invalid API Key")
        
        contact_portal, user_name, agent_name = contact
        
        # 拼接显示名：主人名的Agent名，如 "李亚楠的小扣子"
        from_name = f"{user_name}的{agent_name}" if user_name and agent_name else agent_name or contact_portal
        
        # 验证 from_portal 是否匹配
        if contact_portal != request.from_portal:
            raise HTTPException(status_code=403, detail="Portal URL mismatch")
        
        # 保存消息（我是接收方）
        cursor.execute('''
            INSERT INTO messages (from_portal, to_portal, content, message_type, sender_api_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (request.from_portal, my_portal, request.content, request.message_type, request.api_key, get_now().strftime('%Y-%m-%d %H:%M:%S')))
        
        message_id = cursor.lastrowid
        conn.commit()
        
        # 通过 WebSocket 推送给我的 Agent
        background_tasks.add_task(push_message, my_portal, {
            "type": "new_message",
            "id": message_id,
            "from": request.from_portal,
            "from_name": from_name,
            "content": request.content,
            "message_type": request.message_type,
            "created_at": get_now().isoformat()
        })
        
        return {"status": "received", "message_id": message_id}
    finally:
        if conn:
            conn.close()

@app.get("/api/messages")
async def get_messages(contact_portal: str, since: Optional[str] = None):
    """获取与某个联系人的消息"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    if since:
        cursor.execute('''
            SELECT from_portal, to_portal, content, message_type, created_at
            FROM messages 
            WHERE (from_portal = ? OR to_portal = ?) AND created_at > ?
            ORDER BY created_at ASC
        ''', (contact_portal, contact_portal, since))
    else:
        cursor.execute('''
            SELECT from_portal, to_portal, content, message_type, created_at
            FROM messages 
            WHERE from_portal = ? OR to_portal = ?
            ORDER BY created_at ASC
        ''', (contact_portal, contact_portal))
    
    messages = cursor.fetchall()
    conn.close()
    
    return {
        "messages": [
            {
                "from": m[0],
                "to": m[1],
                "content": m[2],
                "type": m[3],
                "created_at": m[4]
            }
            for m in messages
        ]
    }

@app.get("/api/contacts")
async def get_contacts():
    """获取联系人列表"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, portal_url, display_name, agent_name, user_name, SHARED_KEY, SHARED_KEY, is_verified, created_at
        FROM contacts
        ORDER BY created_at DESC
    ''')
    
    contacts = cursor.fetchall()
    
    # 获取每个联系人的未读消息数
    result = []
    for c in contacts:
        contact_id, portal_url, display_name, agent_name, user_name, SHARED_KEY, SHARED_KEY, is_verified, created_at = c
        
        cursor.execute('''
            SELECT COUNT(*) FROM messages 
            WHERE from_portal = ? AND to_portal = ? AND is_delivered = FALSE
        ''', (portal_url, get_my_portal_url()))
        
        unread_count = cursor.fetchone()[0]
        
        result.append({
            "id": contact_id,
            "portal_url": portal_url,
            "display_name": display_name,
            "agent_name": agent_name,
            "user_name": user_name,
            "SHARED_KEY": SHARED_KEY,  # 我给对方的API Key
            "SHARED_KEY": SHARED_KEY,  # 对方给我的API Key
            "is_verified": is_verified,
            "created_at": created_at,
            "unread_count": unread_count
        })
    
    conn.close()
    
    return {"contacts": result}

class CreateContactRequest(BaseModel):
    portal_url: str
    display_name: Optional[str] = None
    agent_name: Optional[str] = None
    user_name: Optional[str] = None
    SHARED_KEY: Optional[str] = None  # 共享的 Key

@app.post("/api/contacts")
async def create_contact(request: CreateContactRequest):
    """创建联系人"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO contacts 
        (portal_url, display_name, agent_name, user_name, SHARED_KEY, is_verified, created_at)
        VALUES (?, ?, ?, ?, ?, TRUE, ?)
    ''', (
        request.portal_url,
        request.display_name,
        request.agent_name,
        request.user_name,
        request.SHARED_KEY or generate_api_key(),  # 自动生成共享Key
        get_now().strftime('%Y-%m-%d %H:%M:%S')
    ))
    
    conn.commit()
    conn.close()
    
    return {"status": "created"}

@app.delete("/api/contacts/{contact_id}")
async def delete_contact(contact_id: int):
    """删除联系人"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM contacts WHERE id = ?', (contact_id,))
    
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Contact not found")
    
    conn.commit()
    conn.close()
    
    return {"status": "deleted"}

@app.put("/api/contacts/{contact_id}")
async def update_contact(contact_id: int, request: CreateContactRequest):
    """更新联系人信息"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 检查联系人是否存在
    cursor.execute('SELECT id FROM contacts WHERE id = ?', (contact_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # 更新字段
    cursor.execute('''
        UPDATE contacts 
        SET display_name = ?, agent_name = ?, user_name = ?, SHARED_KEY = ?
        WHERE id = ?
    ''', (
        request.display_name,
        request.agent_name,
        request.user_name,
        request.SHARED_KEY,
        contact_id
    ))
    
    conn.commit()
    conn.close()
    
    return {"status": "updated"}

@app.get("/api/notifications/pending")
async def get_pending_notifications():
    """获取待通知的消息（供 OpenClaw 拉取）"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 获取未通知的消息
    cursor.execute('''
        SELECT id, type, content, portal, created_at 
        FROM pending_notifications 
        WHERE is_notified = FALSE
        ORDER BY created_at ASC
    ''')
    
    notifications = cursor.fetchall()
    
    # 标记为已通知
    if notifications:
        ids = [n[0] for n in notifications]
        placeholders = ','.join('?' * len(ids))
        sql = f"UPDATE pending_notifications SET is_notified = TRUE WHERE id IN ({placeholders})"
        cursor.execute(sql, ids)
        conn.commit()
    
    conn.close()
    
    return {
        "notifications": [
            {
                "id": n[0],
                "type": n[1],
                "content": n[2],
                "portal": n[3],
                "created_at": n[4]
            }
            for n in notifications
        ]
    }

@app.get("/api/portal/info")
async def get_portal_info():
    """获取当前 Portal 信息"""
    # 获取第一个可用的 API Key
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT key_id FROM api_keys 
        WHERE is_active = TRUE 
        ORDER BY created_at DESC 
        LIMIT 1
    ''')
    
    result = cursor.fetchone()
    
    # 获取 OpenClaw 配置
    cursor.execute('SELECT value FROM config WHERE key = ?', ('openclaw_url',))
    openclaw_url = cursor.fetchone()
    cursor.execute('SELECT value FROM config WHERE key = ?', ('openclaw_token',))
    openclaw_token = cursor.fetchone()
    
    conn.close()
    
    return {
        "url": get_my_portal_url(),
        "api_key": result[0] if result else None,
        "openclaw_url": openclaw_url[0] if openclaw_url else None,
        "openclaw_token": openclaw_token[0] if openclaw_token else None
    }

class OpenClawConfig(BaseModel):
    url: str
    token: str

@app.post("/api/config/openclaw")
async def save_openclaw_config(request: OpenClawConfig):
    """保存 OpenClaw 配置"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)
    ''', ('openclaw_url', request.url))
    
    cursor.execute('''
        INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)
    ''', ('openclaw_token', request.token))
    
    conn.commit()
    conn.close()
    
    return {"status": "saved"}

# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}
    
    async def connect(self, websocket: WebSocket, api_key: str):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[WS] Connection attempt with api_key: {api_key[:30]}...")
        await websocket.accept()
        portal_url = verify_api_key(api_key)
        logger.info(f"[WS] API Key verified, portal_url: {portal_url}")
        if portal_url:
            self.active_connections[portal_url] = websocket
            logger.info(f"[WS] Connection added for {portal_url}")
            logger.info(f"[WS] Active connections: {list(self.active_connections.keys())}")
        else:
            logger.info(f"[WS] API Key verification failed")
    
    def disconnect(self, api_key: str):
        portal_url = verify_api_key(api_key)
        if portal_url and portal_url in self.active_connections:
            del self.active_connections[portal_url]
    
    async def send_message(self, portal_url: str, message: dict):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[DEBUG] Trying to send to {portal_url}")
        logger.info(f"[DEBUG] Active connections: {list(self.active_connections.keys())}")
        if portal_url in self.active_connections:
            await self.active_connections[portal_url].send_json(message)
            logger.info(f"[DEBUG] Message sent to {portal_url}")
        else:
            logger.info(f"[DEBUG] No active connection for {portal_url}")
            # 抛出异常，让调用者知道发送失败
            raise Exception(f"No active WebSocket connection for {portal_url}")
    
    async def broadcast(self, message: dict):
        """广播消息给所有连接的 Agent"""
        import logging
        logger = logging.getLogger(__name__)
        disconnected = []
        for portal_url, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
                logger.info(f"[BROADCAST] Message sent to {portal_url}")
            except Exception as e:
                logger.error(f"[BROADCAST] Failed to send to {portal_url}: {e}")
                disconnected.append(portal_url)
        # 清理断开的连接
        for portal_url in disconnected:
            del self.active_connections[portal_url]

manager = ConnectionManager()

@app.websocket("/ws/agent")
async def websocket_endpoint(websocket: WebSocket, api_key: str):
    await manager.connect(websocket, api_key)
    import asyncio
    
    # 获取 portal_url
    portal_url = verify_api_key(api_key)
    
    # 启动心跳任务
    heartbeat_task = None
    
    async def send_heartbeat():
        """定期发送心跳保持连接"""
        while True:
            try:
                await asyncio.sleep(30)  # 每30秒发送一次心跳
                await websocket.send_json({"type": "ping"})
            except Exception:
                break
    
    # 启动心跳
    heartbeat_task = asyncio.create_task(send_heartbeat())
    
    try:
        while True:
            # 设置接收超时，避免长时间阻塞
            data = await asyncio.wait_for(websocket.receive_json(), timeout=60)
            
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.get("type") == "pong":
                # 收到心跳响应，连接正常
                pass
            
            elif data.get("type") == "sync_request":
                # 返回未送达的消息（离线期间的消息）
                portal_url = verify_api_key(api_key)
                if portal_url:
                    conn = sqlite3.connect(DATABASE_PATH)
                    cursor = conn.cursor()
                    
                    # 只查询 is_delivered = FALSE 的消息
                    cursor.execute('''
                        SELECT id, from_portal, content, message_type, created_at
                        FROM messages 
                        WHERE to_portal = ? AND is_delivered = FALSE
                        ORDER BY created_at ASC
                    ''', (portal_url,))
                    
                    messages = cursor.fetchall()
                    conn.close()
                    
                    await websocket.send_json({
                        "type": "sync_response",
                        "messages": [
                            {"id": m[0], "from": m[1], "content": m[2], "type": m[3], "created_at": m[4]}
                            for m in messages
                        ]
                    })
            
            elif data.get("type") == "ack":
                # 确认收到消息，更新 is_delivered
                message_ids = data.get("message_ids", [])
                if message_ids:
                    conn = sqlite3.connect(DATABASE_PATH)
                    cursor = conn.cursor()
                    
                    # 批量更新 is_delivered
                    placeholders = ','.join('?' * len(message_ids))
                    sql = f"UPDATE messages SET is_delivered = TRUE WHERE id IN ({placeholders})"
                    cursor.execute(sql, message_ids)
                    
                    conn.commit()
                    conn.close()
                    
                    await websocket.send_json({
                        "type": "ack_confirm",
                        "message_ids": message_ids
                    })
    
    except WebSocketDisconnect:
        manager.disconnect(api_key)

# 静态文件（管理后台）
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """前台页面 - 供其他 Agent 留言"""
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        return index_path.read_text()
    else:
        return """
        <!DOCTYPE html>
        <html>
        <head><title>Agent P2P Portal</title></head>
        <body>
            <h1>Agent P2P Portal</h1>
            <p>Status: Running</p>
            <a href="/static/admin.html">管理后台</a>
        </body>
        </html>
        """

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

# ========== 数据库迁移脚本 ==========
def get_table_columns(cursor, table_name):
    """获取表的列名"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]

def migrate_contacts_table(cursor):
    """迁移 contacts 表（只新增/重命名，不删除）"""
    columns = get_table_columns(cursor, 'contacts')
    
    # 需要新增的列
    new_columns = {
        'SHARED_KEY': 'TEXT',
    }
    
    # 需要重命名的列（从旧名到新名）
    rename_columns = {
        'contact_portal': 'portal_url',  # 旧版本
        'display_name': 'DISPLAY_NAME',  # 旧版本
    }
    
    # 1. 新增列
    for col_name, col_type in new_columns.items():
        if col_name not in columns:
            cursor.execute(f'ALTER TABLE contacts ADD COLUMN {col_name} {col_type}')
            print(f"Added column: {col_name}")
    
    # 2. 重命名列
    for old_name, new_name in rename_columns.items():
        if old_name in columns and new_name not in columns:
            cursor.execute(f'ALTER TABLE contacts RENAME COLUMN {old_name} TO {new_name}')
            print(f"Renamed column: {old_name} -> {new_name}")

def migrate_api_keys_table(cursor):
    """迁移 api_keys 表"""
    columns = get_table_columns(cursor, 'api_keys')
    
    # 需要新增的列
    new_columns = {
        'description': 'TEXT',
    }
    
    for col_name, col_type in new_columns.items():
        if col_name not in columns:
            cursor.execute(f'ALTER TABLE api_keys ADD COLUMN {col_name} {col_type}')
            print(f"Added column: {col_name}")

def run_migrations():
    """运行所有迁移"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        migrate_contacts_table(cursor)
        migrate_api_keys_table(cursor)
        conn.commit()
        print("数据库迁移完成")
    except Exception as e:
        print(f"迁移错误: {e}")
        conn.rollback()
    finally:
        conn.close()


class SentMessageRequest(BaseModel):
    """记录已发送的消息"""
    api_key: str
    to_portal: str
    content: str
    message_type: str = "text"

@app.post("/api/message/sent")
async def record_sent_message(request: SentMessageRequest, background_tasks: BackgroundTasks):
    my_portal = get_my_portal_url()
    conn = None
    
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT portal_url FROM api_keys WHERE key_id = ? AND is_active = TRUE', (request.api_key,))
        result = cursor.fetchone()
        if not result or result[0] != my_portal:
            raise HTTPException(status_code=401, detail="Invalid API Key")
        
        cursor.execute('INSERT INTO messages (from_portal, to_portal, content, message_type, sender_api_key, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (my_portal, request.to_portal, request.content, request.message_type, request.api_key, get_now().strftime('%Y-%m-%d %H:%M:%S')))
        
        message_id = cursor.lastrowid
        conn.commit()
        
        
        return {"status": "recorded", "message_id": message_id}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"记录发送消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()
