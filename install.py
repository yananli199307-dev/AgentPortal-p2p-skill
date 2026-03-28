#!/usr/bin/env python3
"""
Agent P2P Skill 完整安装流程

支持多 Portal 管理，就像一个人可以有多个电话号码。

用户只需要提供：
1. VPS IP 地址
2. SSH 私钥（或让 Agent 生成）
3. 域名（已解析到 VPS）
4. 邮箱（SSL 证书用）

Agent 自动完成：
1. 部署 Portal 到 VPS
2. 获取 Agent Token
3. 配置本地客户端
4. 启动客户端连接

配置存储：
- ~/.openclaw/gateway.env - 环境变量
- ~/.openclaw/agent-p2p/portals.json - 多 Portal 配置
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict


@dataclass
class PortalConfig:
    """单个 Portal 配置"""
    name: str                    # 门户名称（如 "主门户"、"测试门户"）
    vps_ip: str                  # VPS IP
    domain: str                  # 域名
    email: str                   # 邮箱
    ssh_key_path: str            # SSH 私钥路径
    agent_token: Optional[str] = None  # Agent Token
    hub_url: Optional[str] = None      # Portal 地址
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "PortalConfig":
        return cls(**data)


class MultiPortalManager:
    """多 Portal 管理器"""
    
    def __init__(self):
        self.config_dir = Path.home() / ".openclaw" / "agent-p2p"
        self.config_file = self.config_dir / "portals.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.portals: Dict[str, PortalConfig] = {}
        self.load_config()
    
    def load_config(self):
        """加载配置"""
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
                for name, portal_data in data.get("portals", {}).items():
                    self.portals[name] = PortalConfig.from_dict(portal_data)
            except Exception as e:
                print(f"⚠️  加载配置失败: {e}")
    
    def save_config(self):
        """保存配置"""
        data = {
            "portals": {name: portal.to_dict() for name, portal in self.portals.items()}
        }
        self.config_file.write_text(json.dumps(data, indent=2))
    
    def add_portal(self, portal: PortalConfig):
        """添加 Portal"""
        self.portals[portal.name] = portal
        self.save_config()
    
    def get_portal(self, name: str) -> Optional[PortalConfig]:
        """获取 Portal 配置"""
        return self.portals.get(name)
    
    def list_portals(self) -> List[str]:
        """列出所有 Portal"""
        return list(self.portals.keys())
    
    def remove_portal(self, name: str):
        """删除 Portal"""
        if name in self.portals:
            del self.portals[name]
            self.save_config()


class AgentP2PInstaller:
    """Agent P2P 安装器"""
    
    def __init__(self):
        self.skill_dir = Path(__file__).parent.parent.absolute()
        self.gateway_env = Path.home() / ".openclaw" / "gateway.env"
        self.openclaw_config = Path.home() / ".openclaw" / "openclaw.json"
        self.portal_manager = MultiPortalManager()
        
        # 当前安装的 Portal
        self.current_portal: Optional[PortalConfig] = None
        
    def check_prerequisites(self) -> bool:
        """检查前置条件"""
        print("=== 检查前置条件 ===\n")
        
        # 检查 Python 版本
        if sys.version_info < (3, 8):
            print("❌ 需要 Python 3.8+")
            return False
        print("✅ Python 版本检查通过")
        
        # 检查 paramiko
        try:
            import paramiko
            print("✅ paramiko 已安装")
        except ImportError:
            print("⚠️  安装 paramiko...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "paramiko"], check=True)
            print("✅ paramiko 安装完成")
        
        return True
    
    def show_existing_portals(self):
        """显示已有 Portal"""
        portals = self.portal_manager.list_portals()
        if portals:
            print(f"\n📱 你已有 {len(portals)} 个 Portal:")
            for name in portals:
                portal = self.portal_manager.get_portal(name)
                print(f"  - {name}: {portal.domain} ({portal.vps_ip})")
            print()
    
    def collect_info(self) -> bool:
        """收集用户信息"""
        print("\n=== 配置信息收集 ===\n")
        
        # 显示已有 Portal
        self.show_existing_portals()
        
        print("欢迎使用 Agent P2P Skill！")
        print("这个 skill 会帮你部署个人 Portal 服务器，实现 Agent P2P 通信。\n")
        print("💡 提示：就像一个人可以有多个电话号码，")
        print("   你也可以部署多个 Portal，每个都是独立的通信体系。\n")
        
        # Portal 名称
        default_name = f"Portal-{len(self.portal_manager.list_portals()) + 1}"
        name_input = input(f"1. 给这个 Portal 起个名字 [{default_name}]: ").strip()
        portal_name = name_input or default_name
        
        # 检查是否已存在
        if portal_name in self.portal_manager.list_portals():
            print(f"⚠️  '{portal_name}' 已存在，将覆盖配置")
            confirm = input("确认覆盖? [y/N]: ").strip().lower()
            if confirm not in ('y', 'yes'):
                print("已取消")
                return False
        
        # VPS IP
        vps_ip = input("2. VPS IP 地址: ").strip()
        if not vps_ip:
            print("❌ IP 地址不能为空")
            return False
        
        print("   💡 建议：腾讯云/阿里云轻量应用服务器，新加坡/香港节点，免备案")
        
        # SSH 私钥
        default_key = "~/.ssh/id_rsa"
        key_input = input(f"3. SSH 私钥路径 [{default_key}]: ").strip()
        ssh_key_path = key_input or default_key
        ssh_key_path = os.path.expanduser(ssh_key_path)
        
        if not os.path.exists(ssh_key_path):
            print(f"❌ 私钥文件不存在: {ssh_key_path}")
            print("\n如果你没有 SSH 密钥，可以按以下步骤生成：")
            print("  1. 在本地运行: ssh-keygen -t rsa -b 4096 -C 'agent-p2p'")
            print("  2. 将公钥添加到 VPS: ssh-copy-id -i ~/.ssh/id_rsa.pub root@<vps-ip>")
            return False
        
        # 域名
        domain = input("4. 域名（已解析到 VPS）: ").strip()
        if not domain:
            print("❌ 域名不能为空")
            return False
        
        print("   💡 建议：.com 域名审核更快，提前在 DNS 添加 A 记录指向 VPS IP")
        
        # 邮箱
        email = input("5. 邮箱（用于 SSL 证书到期提醒）: ").strip()
        if not email or "@" not in email:
            print("❌ 请输入有效的邮箱地址")
            return False
        
        print("   💡 提示：请使用真实有效的邮箱，确保证书到期能收到通知")
        
        # 创建配置
        self.current_portal = PortalConfig(
            name=portal_name,
            vps_ip=vps_ip,
            domain=domain,
            email=email,
            ssh_key_path=ssh_key_path
        )
        
        print("\n=== 配置确认 ===")
        print(f"Portal 名称: {portal_name}")
        print(f"VPS IP: {vps_ip}")
        print(f"SSH 密钥: {ssh_key_path}")
        print(f"域名: {domain}")
        print(f"邮箱: {email}")
        
        confirm = input("\n确认以上信息正确? [Y/n]: ").strip().lower()
        if confirm and confirm not in ('y', 'yes'):
            print("已取消")
            return False
        
        return True
    
    def deploy_portal(self) -> bool:
        """部署 Portal"""
        print(f"\n=== 部署 Portal: {self.current_portal.name} ===\n")
        
        deploy_script = self.skill_dir / "scripts" / "deploy_portal.py"
        
        cmd = [
            sys.executable, str(deploy_script),
            "--host", self.current_portal.vps_ip,
            "--ssh-key", self.current_portal.ssh_key_path,
            "--domain", self.current_portal.domain,
            "--email", self.current_portal.email
        ]
        
        result = subprocess.run(cmd)
        if result.returncode != 0:
            return False
        
        # 更新配置
        self.current_portal.hub_url = f"https://{self.current_portal.domain}"
        return True
    
    def get_agent_token(self) -> bool:
        """获取 Agent Token"""
        print(f"\n=== 获取 Agent Token ===\n")
        
        print(f"Portal 已部署: {self.current_portal.hub_url}")
        print(f"\n请访问: {self.current_portal.hub_url}/static/admin.html")
        print("登录管理后台，创建一个新的 Agent。\n")
        print("默认管理员账号:")
        print("  用户名: admin")
        print("  密码: AgentP2P2024")
        print("\n（建议登录后立即修改密码）")
        
        token = input("\n请输入生成的 Agent Token: ").strip()
        if not token:
            print("❌ Token 不能为空")
            return False
        
        self.current_portal.agent_token = token
        return True
    
    def configure_local(self) -> bool:
        """配置本地环境"""
        print(f"\n=== 配置本地环境 ===\n")
        
        # 保存到多 Portal 配置
        self.portal_manager.add_portal(self.current_portal)
        print(f"✅ Portal '{self.current_portal.name}' 已保存到配置")
        
        # 更新 gateway.env（默认使用最新 Portal）
        self.gateway_env.parent.mkdir(parents=True, exist_ok=True)
        
        env_content = f"""# Agent P2P 配置
# 默认 Portal: {self.current_portal.name}
AGENTP2P_TOKEN={self.current_portal.agent_token}
AGENTP2P_HUB_URL={self.current_portal.hub_url}
"""
        
        self.gateway_env.write_text(env_content)
        print(f"✅ 默认配置已写入: {self.gateway_env}")
        
        # 创建虚拟环境
        venv_path = self.skill_dir / "venv"
        if not venv_path.exists():
            print("创建虚拟环境...")
            subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
        
        # 安装依赖
        print("安装依赖...")
        pip_cmd = str(venv_path / "bin" / "pip")
        subprocess.run([pip_cmd, "install", "-q", "websocket-client", "requests"], check=True)
        print("✅ 依赖安装完成")
        
        return True
    
    def start_client(self) -> bool:
        """启动客户端"""
        print(f"\n=== 启动 Agent 客户端 ===\n")
        
        # 检查是否需要配置 OpenClaw hooks
        hooks_token = None
        if self.openclaw_config.exists():
            try:
                config = json.loads(self.openclaw_config.read_text())
                hooks_token = config.get("hooks", {}).get("token")
            except:
                pass
        
        if not hooks_token:
            import secrets
            hooks_token = secrets.token_urlsafe(32)
            
            # 更新 gateway.env
            with open(self.gateway_env, "a") as f:
                f.write(f"OPENCLAW_HOOKS_TOKEN={hooks_token}\n")
                f.write("OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789\n")
            
            print("⚠️  需要配置 OpenClaw Gateway")
            print(f"\n请在 {self.openclaw_config} 中添加:")
            print(json.dumps({
                "hooks": {
                    "enabled": True,
                    "path": "/hooks",
                    "token": hooks_token
                }
            }, indent=2))
            print("\n然后运行: openclaw restart")
            
            input("\n配置完成后按回车继续...")
        
        # 启动客户端
        client_script = self.skill_dir / "client.py"
        log_file = self.skill_dir / f"client_{self.current_portal.name}.log"
        pid_file = self.skill_dir / f"client_{self.current_portal.name}.pid"
        
        # 停止旧进程
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                os.kill(old_pid, 9)
                print(f"停止旧进程 (PID: {old_pid})")
            except:
                pass
        
        # 启动新进程
        env = os.environ.copy()
        env["AGENTP2P_TOKEN"] = self.current_portal.agent_token
        env["AGENTP2P_HUB_URL"] = self.current_portal.hub_url
        env["OPENCLAW_HOOKS_TOKEN"] = hooks_token
        env["OPENCLAW_GATEWAY_URL"] = "http://127.0.0.1:18789"
        
        with open(log_file, "w") as log:
            process = subprocess.Popen(
                [str(self.skill_dir / "venv" / "bin" / "python3"), str(client_script)],
                stdout=log,
                stderr=log,
                env=env,
                cwd=str(self.skill_dir)
            )
        
        import time
        time.sleep(3)
        
        if process.poll() is None:
            print(f"✅ 客户端已启动 (PID: {process.pid})")
            pid_file.write_text(str(process.pid))
            
            # 保存 PID 到配置
            self.current_portal.agent_token = f"{self.current_portal.agent_token}"
            self.portal_manager.save_config()
        else:
            print("❌ 客户端启动失败")
            print(f"查看日志: {log_file}")
            return False
        
        return True
    
    def install(self) -> bool:
        """执行完整安装"""
        print("\n" + "="*60)
        print("Agent P2P Skill 安装向导")
        print("="*60)
        
        steps = [
            ("检查前置条件", self.check_prerequisites),
            ("收集配置信息", self.collect_info),
            ("部署 Portal", self.deploy_portal),
            ("获取 Agent Token", self.get_agent_token),
            ("配置本地环境", self.configure_local),
            ("启动客户端", self.start_client),
        ]
        
        for name, step_func in steps:
            print(f"\n{'─'*60}")
            print(f"步骤: {name}")
            print(f"{'─'*60}")
            
            if not step_func():
                print(f"\n❌ 安装失败于步骤: {name}")
                return False
        
        # 显示完成信息
        print("\n" + "="*60)
        print("🎉 Agent P2P Skill 安装完成！")
        print("="*60)
        print(f"\nPortal '{self.current_portal.name}' 已就绪:")
        print(f"  地址: {self.current_portal.hub_url}")
        print(f"  管理后台: {self.current_portal.hub_url}/static/admin.html")
        
        # 显示所有 Portal
        all_portals = self.portal_manager.list_portals()
        if len(all_portals) > 1:
            print(f"\n你共有 {len(all_portals)} 个 Portal:")
            for name in all_portals:
                portal = self.portal_manager.get_portal(name)
                status = "✅ 当前默认" if name == self.current_portal.name else ""
                print(f"  - {name}: {portal.domain} {status}")
        
        print(f"\n现在你可以：")
        print("1. 访问管理后台查看留言和联系人")
        print("2. 让其他 Agent 访问你的 Portal 建立联系")
        print("3. 使用 ./send.py 发送消息给其他 Agent")
        print(f"\n查看客户端日志: tail -f {self.skill_dir}/client_{self.current_portal.name}.log")
        print("\n管理多个 Portal: 查看 SKILL.md '多 Portal 管理' 章节")
        print("\n")
        
        return True


def main():
    installer = AgentP2PInstaller()
    success = installer.install()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
