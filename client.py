#!/usr/bin/env python3
"""
Agent P2P Client - OpenClaw Skill 客户端 (v0.2)

职责：
1. 保持 WebSocket 连接到 Agent P2P Portal
2. 收到消息 → 通过 hooks/wake 唤醒主会话
3. 支持离线消息同步和送达确认

环境变量：
- AGENTP2P_API_KEY: Agent API Key（必需，v0.2 后替代 Token）
- AGENTP2P_HUB_URL: Portal 地址（默认 https://your-domain.com）
- OPENCLAW_GATEWAY_URL: OpenClaw Gateway 地址
- OPENCLAW_HOOKS_TOKEN: OpenClaw hooks token

注意：v0.2 后使用 API Key 替代 JWT Token，请更新配置
"""

import sys
import os
import json
import time
import signal
import atexit
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

# 配置 logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 尝试导入 websocket
try:
    import websocket
    import requests
except ImportError as e:
    logger.error(f"缺少依赖: {e}")
    logger.error("请运行: venv/bin/pip install websocket-client requests")
    sys.exit(1)


class PIDManager:
    """PID 文件管理器"""
    
    def __init__(self, pid_file: Path):
        self.pid_file = pid_file
        self.pid = os.getpid()
        
    def register(self):
        """注册 PID"""
        try:
            # 检查是否有旧进程
            if self.pid_file.exists():
                old_pid = int(self.pid_file.read_text().strip())
                try:
                    os.kill(old_pid, 0)
                    logger.error(f"已有进程运行 (PID: {old_pid})")
                    return False
                except (OSError, ProcessLookupError):
                    pass
            
            self.pid_file.write_text(str(self.pid))
            atexit.register(self.cleanup)
            return True
        except Exception as e:
            logger.error(f"PID 注册失败: {e}")
            return False
    
    def cleanup(self):
        """清理 PID 文件"""
        try:
            if self.pid_file.exists() and self.pid_file.read_text().strip() == str(self.pid):
                self.pid_file.unlink()
        except:
            pass


class AgentP2PClient:
    """Agent P2P 客户端"""
    
    def __init__(self):
        # v0.2+: 使用 API Key
        self.api_key = os.environ.get("AGENTP2P_API_KEY")
        self.hub_url = os.environ.get("AGENTP2P_HUB_URL", "https://your-domain.com")
        self.gateway_url = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
        self.hooks_token = os.environ.get("OPENCLAW_HOOKS_TOKEN")
        
        self.ws: Optional[websocket.WebSocketApp] = None
        self.connected = False
        self.reconnect_interval = 5
        self.max_reconnect_interval = 60
        self.running = True
        self.last_message_id = 0  # 记录最后处理的留言ID
        
        # 解析 skill 目录
        self.skill_dir = Path(__file__).parent.absolute()
        self.pid_file = self.skill_dir / "client.pid"
        self.status_file = self.skill_dir / "client_status.json"
        self.queue_dir = self.skill_dir / "message_queue"
        
        # 创建队列目录
        self.queue_dir.mkdir(exist_ok=True)
        
    def validate_config(self) -> bool:
        """验证配置"""
        if not self.api_key:
            logger.error("AGENTP2P_API_KEY 未设置")
            return False
        if not self.hooks_token:
            logger.error("OPENCLAW_HOOKS_TOKEN 未设置")
            return False
        return True
    
    def update_status(self, status: str, message: str = ""):
        """更新状态文件"""
        try:
            data = {
                "status": status,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "pid": os.getpid()
            }
            self.status_file.write_text(json.dumps(data))
        except Exception as e:
            logger.error(f"更新状态失败: {e}")
    
    def save_message(self, message: dict) -> Path:
        """保存消息到队列"""
        msg_id = message.get("id", f"msg_{int(time.time()*1000)}")
        msg_file = self.queue_dir / f"{msg_id}.json"
        msg_file.write_text(json.dumps(message, ensure_ascii=False))
        return msg_file
    
    def check_pending_auth(self):
        """检查待处理的验证请求和 Token（Agent 自动响应）"""
        try:
            # 使用配置的 hub_url 作为 portal_url
            my_portal = self.hub_url
            
            if not my_portal:
                return
            
            # 1. 检查新的留言
            url = f"{self.hub_url}/api/guest/messages"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                messages = data.get("messages", [])
                
                for msg in messages:
                    msg_id = msg.get("id", 0)
                    
                    # 只处理新留言
                    if msg_id <= self.last_message_id:
                        continue
                    
                    self.last_message_id = msg_id
                    content = msg.get("content", "")
                    created_at = msg.get("created_at", "")
                    
                    # 检查是否是好友请求（包含 Portal 地址）
                    if any(kw in content for kw in ["加好友", "好友", "P2P", "连接", "Portal", "portal"]):
                        # 提取 Portal 地址
                        url_match = re.search(r'https?://[^\s\n]+', content)
                        if url_match:
                            portal_url = url_match.group(0)
                            logger.info(f"🔔 收到好友请求: {portal_url}")
                            self.wake_openclaw(
                                f"[Agent P2P] 收到好友请求！\n"
                                f"来自: {portal_url}\n"
                                f"请访问管理后台处理: {self.hub_url}/static/admin.html"
                            )
                    
                    # 检查是否包含验证码（Step 2）
                    code_match = re.search(r'验证码[：:]\s*(\d{6})', content)
                    if code_match:
                        code = code_match.group(1)
                        logger.info(f"🔢 收到验证码: {code}")
                        
                        # 自动确认验证码（Step 3）
                        self._confirm_verification_code(code)
                    
                    # 检查是否包含 Token（Step 5）
                    token_match = re.search(r'[Tt]oken[：:]\s*(eyJ[A-Za-z0-9_\-\.]+)', content)
                    if token_match:
                        token = token_match.group(1)
                        logger.info(f"🎉 收到 Token: {token[:30]}...")
                        self.wake_openclaw(
                            f"[Agent P2P] 🎉 收到 Token！\n"
                            f"Token: {token[:50]}...\n"
                            f"请保存到配置文件中"
                        )
                    
                    # 普通留言通知
                    if not any(kw in content for kw in ["加好友", "好友", "P2P", "连接", "Portal", "portal", "验证码", "Token", "token"]):
                        logger.info(f"📨 收到新留言: {content[:50]}...")
                        self.wake_openclaw(
                            f"[Agent P2P] 收到新留言！\n"
                            f"时间: {created_at}\n"
                            f"内容: {content[:100]}...\n"
                            f"请查看: {self.hub_url}/static/admin.html"
                        )
                        
        except Exception as e:
            logger.debug(f"检查验证请求: {e}")
    
    def _confirm_verification_code(self, code: str):
        """自动确认验证码（Step 3）"""
        try:
            # 从留言中提取对方 Portal 地址
            url = f"{self.hub_url}/api/guest/messages"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code != 200:
                return
            
            data = resp.json()
            messages = data.get("messages", [])
            
            # 找到最新的包含验证码的留言，提取发送者
            for msg in messages:
                content = msg.get("content", "")
                import re
                
                # 检查是否包含验证码
                if re.search(r'验证码[：:]\s*' + code, content):
                    # 尝试从同一条或上一条留言中提取 Portal 地址
                    portal_match = re.search(r'https?://[^\s\n]+', content)
                    if not portal_match:
                        # 从上一条留言找
                        idx = messages.index(msg)
                        if idx > 0:
                            portal_match = re.search(r'https?://[^\s\n]+', messages[idx-1].get("content", ""))
                    
                    if portal_match:
                        portal_url = portal_match.group(0)
                        
                        # 调用确认验证码 API
                        confirm_url = f"{portal_url}/api/verification/code/confirm"
                        confirm_resp = requests.post(confirm_url, json={
                            "portal_url": self.hub_url,
                            "code": code
                        }, timeout=10)
                        
                        if confirm_resp.status_code == 200:
                            logger.info(f"✅ 验证码 {code} 已自动确认")
                            self.wake_openclaw(
                                f"[Agent P2P] 验证码 {code} 已自动确认！\n"
                                f"等待对方发送 Token..."
                            )
                        else:
                            logger.warning(f"验证码确认失败: {confirm_resp.status_code}")
                        
                        break
                        
        except Exception as e:
            logger.debug(f"自动确认验证码失败: {e}")

    def wake_openclaw(self, text: str):
        """唤醒 OpenClaw 主会话"""
        try:
            url = f"{self.gateway_url}/hooks/wake"
            headers = {
                "Authorization": f"Bearer {self.hooks_token}",
                "Content-Type": "application/json"
            }
            data = {"text": text}
            
            resp = requests.post(url, headers=headers, json=data, timeout=10)
            if resp.status_code == 200:
                logger.info("✅ 已唤醒 OpenClaw")
                return True
            else:
                logger.error(f"唤醒失败: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"唤醒请求失败: {e}")
            return False
    
    def on_message(self, ws, message):
        """收到 WebSocket 消息"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "message")
            
            logger.info(f"📨 收到消息: {msg_type}")
            
            # 保存消息
            self.save_message(data)
            
            # 构造唤醒文本（ping/pong 不唤醒）
            if msg_type == "ping" or msg_type == "pong":
                # 心跳消息，不唤醒
                pass
            elif msg_type == "message":
                content = data.get("content", "")
                sender = data.get("from", "未知")
                wake_text = f"[Agent P2P] {sender}: {content}"
                self.wake_openclaw(wake_text)
            elif msg_type == "system":
                wake_text = f"[Agent P2P 系统] {data.get('content', '')}"
                self.wake_openclaw(wake_text)
            else:
                wake_text = f"[Agent P2P] 收到 {msg_type} 消息"
                self.wake_openclaw(wake_text)
            
        except json.JSONDecodeError:
            logger.error(f"无法解析消息: {message[:200]}")
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
    
    def on_error(self, ws, error):
        """WebSocket 错误"""
        logger.error(f"WebSocket 错误: {error}")
        self.connected = False
        self.update_status("error", str(error))
    
    def on_close(self, ws, close_status_code, close_msg):
        """WebSocket 关闭"""
        logger.info(f"WebSocket 关闭: {close_status_code} {close_msg}")
        self.connected = False
        self.update_status("disconnected", f"{close_status_code}: {close_msg}")
    
    def on_open(self, ws):
        """WebSocket 连接成功"""
        logger.info("✅ WebSocket 已连接")
        self.connected = True
        self.reconnect_interval = 5
        self.update_status("connected", "WebSocket 连接成功")
        
        # 发送 ping 保持连接
        ws.send(json.dumps({"type": "ping"}))
        
        # 检查待处理的验证请求
        self.check_pending_auth()
    
    def connect(self):
        """建立 WebSocket 连接"""
        ws_url = self.hub_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/ws/agent?api_key={self.api_key}"
        
        logger.info(f"🌐 连接 {ws_url[:80]}...")
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # 在单独线程中运行
        self.ws.run_forever()
    
    def run(self):
        """主循环"""
        logger.info("=== Agent P2P Client 启动 ===")
        logger.info(f"   Hub: {self.hub_url}")
        logger.info(f"   Gateway: {self.gateway_url}")
        
        # 验证配置
        if not self.validate_config():
            sys.exit(1)
        
        # 注册 PID
        pid_mgr = PIDManager(self.pid_file)
        if not pid_mgr.register():
            sys.exit(1)
        
        # 信号处理
        def signal_handler(signum, frame):
            logger.info("收到终止信号，正在关闭...")
            self.running = False
            if self.ws:
                self.ws.close()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        # 启动留言轮询线程
        import threading
        def poll_messages():
            """定期轮询留言"""
            while self.running:
                try:
                    self.check_pending_auth()
                except Exception as e:
                    logger.debug(f"轮询留言出错: {e}")
                time.sleep(30)  # 每30秒检查一次
        
        poll_thread = threading.Thread(target=poll_messages, daemon=True)
        poll_thread.start()
        logger.info("✅ 留言轮询线程已启动")
        
        # 重连循环
        while self.running:
            try:
                self.connect()
            except Exception as e:
                logger.error(f"连接异常: {e}")
            
            if self.running:
                logger.info(f"⏳ {self.reconnect_interval}秒后重连...")
                time.sleep(self.reconnect_interval)
                self.reconnect_interval = min(
                    self.reconnect_interval * 2,
                    self.max_reconnect_interval
                )
        
        logger.info("=== Agent P2P Client 已停止 ===")


def main():
    client = AgentP2PClient()
    client.run()


if __name__ == "__main__":
    main()
