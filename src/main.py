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
            api_key TEXT NOT NULL,
            their_api_key TEXT,
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
            file_url TEXT,
            is_delivered BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# 数据模型
class GuestMessageRequest(BaseModel):
    content: str

class MessageHistoryRequest(BaseModel):
    contact_portal: str
    limit: int = 50
    offset: int = 0

class SendMessageRequest(BaseModel):
    api_key: str                    # 发送方 API Key（Portal B 给我的）
    to_portal: str                  # 接收方 Portal URL
    content: str
    message_type: str = "text"

class ApiKeyCreateRequest(BaseModel):
    portal_url: str
    agent_name: Optional[str] = None
    user_name: Optional[str] = None

class ApiKeyExchangeRequest(BaseModel):
    portal_url: str
    their_api_key: str

# 工具函数
def generate_api_key() -> str:
    """生成随机 API Key"""
    return "ap2p_" + secrets.token_urlsafe(32)

def verify_api_key(api_key: str) -> Optional[str]:
    """验证 API Key，返回对应的 portal_url"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT portal_url FROM api_keys 
        WHERE key_id = ? AND is_active = TRUE
    ''', (api_key,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0]
    return None

def get_my_portal_url() -> str:
    """获取当前 Portal 的 URL（从环境变量或配置）"""
    return os.getenv("PORTAL_URL", "")

# API 路由

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
    """更新留言状态（同意/拒绝）"""
    data = await request.json()
    status = data.get('status')
    
    if status not in ['approved', 'rejected']:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE guest_messages 
        SET status = ?, is_read = TRUE 
        WHERE id = ?
    ''', (status, message_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "updated"}

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
    my_api_key = generate_api_key()
    
    # 保存 API Key 到数据库
    cursor.execute('''
        INSERT INTO api_keys (key_id, portal_url, agent_name, created_at, is_active)
        VALUES (?, ?, ?, ?, TRUE)
    ''', (my_api_key, request.portal_url, "friend", get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    # 保存联系人关系
    cursor.execute('''
        INSERT OR REPLACE INTO contacts 
        (portal_url, api_key, their_api_key, is_verified, created_at)
        VALUES (?, ?, ?, TRUE, ?)
    ''', (request.portal_url, my_api_key, request.their_api_key, get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "exchanged",
        "api_key": my_api_key,
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
    """发送消息"""
    # 验证 API Key，获取发送方 Portal URL
    from_portal = verify_api_key(request.api_key)
    if not from_portal:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 目标 Portal 直接从请求获取
    to_portal = request.to_portal
    
    # 保存消息
    cursor.execute('''
        INSERT INTO messages (from_portal, to_portal, content, message_type, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (from_portal, to_portal, request.content, request.message_type, get_now().strftime('%Y-%m-%d %H:%M:%S')))
    
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # 后台推送消息
    background_tasks.add_task(push_message, to_portal, {
        "type": "message",
        "id": message_id,
        "from": from_portal,
        "content": request.content,
        "message_type": request.message_type,
        "created_at": get_now().isoformat()
    })
    
    return {"status": "delivered", "message_id": message_id}

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
        SELECT id, portal_url, display_name, agent_name, user_name, api_key, their_api_key, is_verified, created_at
        FROM contacts
        ORDER BY created_at DESC
    ''')
    
    contacts = cursor.fetchall()
    
    # 获取每个联系人的未读消息数
    result = []
    for c in contacts:
        contact_id, portal_url, display_name, agent_name, user_name, api_key, their_api_key, is_verified, created_at = c
        
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
            "api_key": api_key,
            "their_api_key": their_api_key,
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
    api_key: Optional[str] = None
    their_api_key: Optional[str] = None

@app.post("/api/contacts")
async def create_contact(request: CreateContactRequest):
    """创建联系人"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO contacts 
        (portal_url, display_name, agent_name, user_name, api_key, their_api_key, is_verified, created_at)
        VALUES (?, ?, ?, ?, ?, ?, TRUE, ?)
    ''', (
        request.portal_url,
        request.display_name,
        request.agent_name,
        request.user_name,
        request.api_key or generate_api_key(),
        request.their_api_key,
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
        SET display_name = ?, agent_name = ?, user_name = ?, api_key = ?, their_api_key = ?
        WHERE id = ?
    ''', (
        request.display_name,
        request.agent_name,
        request.user_name,
        request.api_key,
        request.their_api_key,
        contact_id
    ))
    
    conn.commit()
    conn.close()
    
    return {"status": "updated"}

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
    conn.close()
    
    return {
        "url": get_my_portal_url(),
        "api_key": result[0] if result else None
    }

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
