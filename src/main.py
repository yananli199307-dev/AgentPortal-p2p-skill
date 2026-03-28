from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, File, UploadFile, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import json
import secrets
import hashlib
from datetime import datetime, timedelta
from jose import JWTError, jwt
import os

app = FastAPI(title="Agent P2P Portal")

# 配置
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 365
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/portal.db")

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
            is_read BOOLEAN DEFAULT FALSE
        )
    ''')
    
    # 联系人表（已验证）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portal_url TEXT UNIQUE NOT NULL,
            display_name TEXT,
            token TEXT NOT NULL,
            their_token TEXT,
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
            is_synced BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 验证挑战表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portal_url TEXT NOT NULL,
            challenge_code TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# 数据模型
class GuestMessageRequest(BaseModel):
    content: str

class AuthInitiateRequest(BaseModel):
    portal_url: str

class AuthCompleteRequest(BaseModel):
    portal_url: str
    challenge_response: str
    their_token: Optional[str] = None

class SendMessageRequest(BaseModel):
    to_portal: str
    token: str
    content: str
    message_type: str = "text"

class TokenData(BaseModel):
    portal_url: Optional[str] = None

# 工具函数
def create_token(portal_url: str) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    to_encode = {"sub": portal_url, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

def generate_challenge() -> str:
    return secrets.token_hex(16)

# API 路由

@app.post("/api/guest/leave-message")
async def leave_message(request: GuestMessageRequest, request_obj: Request):
    """匿名留言"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO guest_messages (content, ip_address, user_agent)
        VALUES (?, ?, ?)
    ''', (request.content, request_obj.client.host, request_obj.headers.get("user-agent")))
    
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
        SELECT id, content, created_at, is_read 
        FROM guest_messages 
        ORDER BY created_at DESC
    ''')
    
    messages = cursor.fetchall()
    conn.close()
    
    return {
        "messages": [
            {"id": m[0], "content": m[1], "created_at": m[2], "is_read": m[3]}
            for m in messages
        ]
    }

@app.post("/api/auth/initiate")
async def auth_initiate(request: AuthInitiateRequest):
    """发起身份验证"""
    challenge = generate_challenge()
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 保存挑战码
    cursor.execute('''
        INSERT INTO challenges (portal_url, challenge_code, expires_at)
        VALUES (?, ?, ?)
    ''', (request.portal_url, challenge, expires_at))
    
    conn.commit()
    conn.close()
    
    # TODO: 发送挑战码到对方门户
    # 这里需要异步发送，暂时返回挑战码
    
    return {
        "challenge": challenge,
        "expires_at": expires_at.isoformat()
    }

@app.post("/api/auth/complete")
async def auth_complete(request: AuthCompleteRequest):
    """完成身份验证"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 验证挑战码
    cursor.execute('''
        SELECT challenge_code FROM challenges 
        WHERE portal_url = ? AND expires_at > ?
        ORDER BY created_at DESC LIMIT 1
    ''', (request.portal_url, datetime.utcnow()))
    
    result = cursor.fetchone()
    if not result or result[0] != request.challenge_response:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid challenge")
    
    # 生成 Token
    token = create_token(request.portal_url)
    expires_at = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    
    # 保存联系人
    cursor.execute('''
        INSERT OR REPLACE INTO contacts 
        (portal_url, token, their_token, expires_at)
        VALUES (?, ?, ?, ?)
    ''', (request.portal_url, token, request.their_token, expires_at))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "verified",
        "your_token": token,
        "expires_at": expires_at.isoformat()
    }

async def push_message(to_portal: str, message: dict):
    """异步推送消息到 WebSocket"""
    try:
        await manager.send_message(to_portal, message)
    except Exception as e:
        print(f"WebSocket 推送失败: {e}")

@app.post("/api/message/send")
async def send_message(request: SendMessageRequest, background_tasks: BackgroundTasks):
    """发送消息"""
    # 验证 Token
    portal_url = verify_token(request.token)
    if not portal_url:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 保存消息
    cursor.execute('''
        INSERT INTO messages (from_portal, to_portal, content, message_type)
        VALUES (?, ?, ?, ?)
    ''', (portal_url, request.to_portal, request.content, request.message_type))
    
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    

    
    # 后台推送消息
    background_tasks.add_task(push_message, request.to_portal, {
        "type": "message",
        "id": message_id,
        "from": portal_url,
        "content": request.content,
        "message_type": request.message_type,
        "created_at": datetime.utcnow().isoformat()
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
        SELECT portal_url, display_name, is_verified, created_at
        FROM contacts
        ORDER BY created_at DESC
    ''')
    
    contacts = cursor.fetchall()
    conn.close()
    
    return {
        "contacts": [
            {
                "portal_url": c[0],
                "display_name": c[1],
                "is_verified": c[2],
                "created_at": c[3]
            }
            for c in contacts
        ]
    }

# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}
    
    async def connect(self, websocket: WebSocket, token: str):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[WS] Connection attempt with token: {token[:30]}...")
        await websocket.accept()
        portal_url = verify_token(token)
        logger.info(f"[WS] Token verified, portal_url: {portal_url}")
        if portal_url:
            self.active_connections[portal_url] = websocket
            logger.info(f"[WS] Connection added for {portal_url}")
            logger.info(f"[WS] Active connections: {list(self.active_connections.keys())}")
        else:
            logger.info(f"[WS] Token verification failed")
    
    def disconnect(self, token: str):
        portal_url = verify_token(token)
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
async def websocket_endpoint(websocket: WebSocket, token: str):
    await manager.connect(websocket, token)
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif data.get("type") == "sync_request":
                # 返回未同步的消息
                portal_url = verify_token(token)
                if portal_url:
                    conn = sqlite3.connect(DATABASE_PATH)
                    cursor = conn.cursor()
                    
                    last_sync = data.get("last_sync")
                    if last_sync:
                        cursor.execute('''
                            SELECT from_portal, content, message_type, created_at
                            FROM messages 
                            WHERE to_portal = ? AND created_at > ?
                            ORDER BY created_at ASC
                        ''', (portal_url, last_sync))
                    else:
                        cursor.execute('''
                            SELECT from_portal, content, message_type, created_at
                            FROM messages 
                            WHERE to_portal = ?
                            ORDER BY created_at ASC
                        ''', (portal_url,))
                    
                    messages = cursor.fetchall()
                    conn.close()
                    
                    await websocket.send_json({
                        "type": "sync_response",
                        "messages": [
                            {"from": m[0], "content": m[1], "type": m[2], "created_at": m[3]}
                            for m in messages
                        ]
                    })
    
    except WebSocketDisconnect:
        manager.disconnect(token)

# 静态文件（管理后台）
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Agent P2P Portal</title>
    </head>
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
