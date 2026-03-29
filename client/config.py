"""
Agent P2P Client 配置管理
"""
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".openclaw" / "skills" / "agent-p2p-client"
CONFIG_FILE = CONFIG_DIR / "config.json"

def ensure_config_dir():
    """确保配置目录存在"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def load_config():
    """加载配置"""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}

def save_config(config):
    """保存配置"""
    ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2))

def get_portal_url():
    """获取门户地址"""
    config = load_config()
    return config.get("portal_url", "")

def set_portal_url(url):
    """设置门户地址"""
    config = load_config()
    config["portal_url"] = url
    save_config(config)

def get_api_key():
    """获取 API Key"""
    config = load_config()
    return config.get("api_key", "")

def set_api_key(api_key):
    """设置 API Key"""
    config = load_config()
    config["api_key"] = api_key
    save_config(config)

def is_configured():
    """检查是否已配置"""
    config = load_config()
    return bool(config.get("portal_url") and config.get("api_key"))
