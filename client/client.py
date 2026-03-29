"""
Agent P2P Client WebSocket 连接
"""
import asyncio
import websockets
import json
import time
import os
from .config import get_portal_url, get_api_key

# 本地存储文件路径
STATE_FILE = os.path.expanduser("~/.agent_p2p_state.json")

class PortalClient:
    def __init__(self, message_callback=None):
        self.portal_url = None
        self.api_key = None
        self.ws = None
        self.running = False
        self.message_callback = message_callback
        self.reconnect_delay = 5  # 重连延迟（秒）
        self.pending_acks = []  # 待确认的消息ID
    
    def _load_state(self):
        """加载本地状态（最后同步时间等）"""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Agent P2P] 加载状态失败: {e}")
        return {}
    
    def _save_state(self, state):
        """保存本地状态"""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[Agent P2P] 保存状态失败: {e}")
    
    def _notify_user(self, message):
        """通知用户（默认实现：打印到控制台）"""
        print(f"\n{'='*50}")
        print(f"🔔 Agent P2P 通知")
        print(f"{'='*50}")
        print(message)
        print(f"{'='*50}\n")
    
    def load_config(self):
        """加载配置"""
        self.portal_url = get_portal_url()
        self.api_key = get_api_key()
        return bool(self.portal_url and self.api_key)
    
    def get_ws_url(self):
        """获取 WebSocket URL"""
        ws_url = self.portal_url.replace('https://', 'wss://').replace('http://', 'ws://')
        return f"{ws_url}/ws/agent?api_key={self.api_key}"
    
    async def connect(self):
        """连接门户"""
        if not self.load_config():
            print("[Agent P2P] 未配置，请先配置门户地址和 API Key")
            return False
        
        try:
            ws_url = self.get_ws_url()
            print(f"[Agent P2P] 正在连接: {ws_url}")
            
            self.ws = await websockets.connect(ws_url)
            self.running = True
            
            print(f"[Agent P2P] 已连接到门户: {self.portal_url}")
            
            # 发送同步请求，获取离线消息
            await self._send_sync_request()
            
            return True
        except Exception as e:
            print(f"[Agent P2P] 连接失败: {e}")
            return False
    
    async def _send_sync_request(self):
        """发送同步请求，获取离线期间的消息"""
        state = self._load_state()
        last_sync = state.get("last_sync")
        
        await self.ws.send(json.dumps({
            "type": "sync_request",
            "last_sync": last_sync
        }))
        print(f"[Agent P2P] 请求同步消息 (last_sync: {last_sync})")
    
    async def _send_ack(self, message_ids):
        """发送消息确认"""
        if not message_ids or not self.ws:
            return
        
        try:
            await self.ws.send(json.dumps({
                "type": "ack",
                "message_ids": message_ids
            }))
            print(f"[Agent P2P] 确认收到 {len(message_ids)} 条消息")
        except Exception as e:
            print(f"[Agent P2P] 发送确认失败: {e}")
    
    async def handle_messages(self):
        """处理消息"""
        while self.running and self.ws:
            try:
                message = await self.ws.recv()
                data = json.loads(message)
                
                # 处理不同类型的消息
                if data.get("type") == "pong":
                    pass  # 心跳响应
                
                elif data.get("type") == "new_message":
                    msg_id = data.get("id")
                    msg = f"📩 新消息来自 {data.get('from')}: {data.get('content')}"
                    print(f"[Agent P2P] {msg}")
                    
                    # 立即确认收到
                    if msg_id:
                        await self._send_ack([msg_id])
                    
                    if self.message_callback:
                        await self.message_callback(data)
                    else:
                        self._notify_user(msg)
                
                elif data.get("type") == "new_guest_message":
                    msg = f"💬 新留言: {data.get('content')}"
                    print(f"[Agent P2P] {msg}")
                    if self.message_callback:
                        await self.message_callback(data)
                    else:
                        self._notify_user(msg)
                
                elif data.get("type") == "sync_response":
                    messages = data.get("messages", [])
                    if messages:
                        print(f"[Agent P2P] 同步到 {len(messages)} 条离线消息")
                        
                        # 处理离线消息
                        ack_ids = []
                        for msg in messages:
                            msg_id = msg.get("id")
                            content = msg.get("content")
                            from_portal = msg.get("from")
                            
                            display_msg = f"📩 [离线消息] 来自 {from_portal}: {content}"
                            print(f"[Agent P2P] {display_msg}")
                            
                            if self.message_callback:
                                await self.message_callback(msg)
                            else:
                                self._notify_user(display_msg)
                            
                            if msg_id:
                                ack_ids.append(msg_id)
                        
                        # 批量确认收到的离线消息
                        if ack_ids:
                            await self._send_ack(ack_ids)
                    else:
                        print("[Agent P2P] 没有离线消息")
                    
                    # 更新最后同步时间
                    state = self._load_state()
                    state["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    self._save_state(state)
                
                elif data.get("type") == "ack_confirm":
                    # 服务器确认收到我们的 ack
                    pass
                
            except websockets.exceptions.ConnectionClosed:
                print("[Agent P2P] 连接已关闭")
                self.running = False
                break
            except Exception as e:
                print(f"[Agent P2P] 消息处理错误: {e}")
    
    async def run(self):
        """运行客户端（自动重连）"""
        while True:
            if await self.connect():
                await self.handle_messages()
            
            # 断线后等待重连
            print(f"[Agent P2P] {self.reconnect_delay}秒后重连...")
            await asyncio.sleep(self.reconnect_delay)
    
    async def send_message(self, to_portal, content):
        """发送消息（通过 HTTP API）"""
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.portal_url}/api/message/send",
                    json={
                        "to_portal": to_portal,
                        "api_key": self.api_key,
                        "content": content
                    }
                )
                return response.json()
        except Exception as e:
            print(f"[Agent P2P] 发送消息失败: {e}")
            return None
    
    async def get_guest_messages(self):
        """获取留言列表"""
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.portal_url}/api/guest/messages")
                return response.json()
        except Exception as e:
            print(f"[Agent P2P] 获取留言失败: {e}")
            return None
    
    async def get_messages(self, contact_portal):
        """获取消息记录"""
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.portal_url}/api/messages",
                    params={"contact_portal": contact_portal}
                )
                return response.json()
        except Exception as e:
            print(f"[Agent P2P] 获取消息失败: {e}")
            return None

# 全局客户端实例
_client = None

def get_client():
    """获取客户端实例"""
    global _client
    if _client is None:
        _client = PortalClient()
    return _client
