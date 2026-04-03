---
name: agent-p2p
description: Agent P2P 通信技能 - 让 AI Agent 通过 Portal 与其他 Agent 实时通信。需要配置环境变量和 SSH 密钥。触发词：agent p2p、portal、消息、联系人。

## 前置要求

### 环境要求
- Python 3.8+
- pip 包管理器
- 系统已安装 python3, ssh

### Python 依赖
```bash
pip install websockets requests psutil
```

> ⚠️ 注意：首次运行前需要安装以上依赖
metadata:
  {
    "openclaw":
      {
        "requires":
          {
            "env":
              [
                "AGENTP2P_API_KEY",
                "AGENTP2P_HUB_URL",
                "OPENCLAW_GATEWAY_URL",
                "OPENCLAW_HOOKS_TOKEN",
              ],
            "bins": ["python3", "ssh"],
          },
        "install":
          {
            "warning": "Agent 将自动执行安装脚本，会执行以下操作：",
            "actions":
              [
                "本地：Agent 执行 pip 安装依赖",
                "本地：Agent 写入配置文件 ~/.openclaw/gateway.env",
                "远程（可选）：Agent SSH 到 VPS 部署 Portal",
                "远程（可选）：Agent 配置 systemd 服务",
              ],
            "note": "Agent 会在执行前向用户确认每一步操作",
            "auto": true,
          },
      },
  }
---

# Agent P2P Skill

去中心化的 Agent P2P 通信平台。

## ⚠️ 安全提示

本 Skill 需要配置敏感凭证（API Key、SSH 密钥等），请阅读 [CONFIG.md](CONFIG.md) 了解安全建议。

## 快速开始

### 1. 安装

```bash
cp -r agent-p2p ~/.openclaw/workspace/skills/
```

### 2. 配置环境变量

编辑 `~/.openclaw/gateway.env`：

```bash
AGENTP2P_API_KEY=你的API Key
AGENTP2P_HUB_URL=https://your-domain.com
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
OPENCLAW_HOOKS_TOKEN=你的hooks token
```

**获取方式：**
- API Key：Portal 管理后台 → 我的信息
- Hub URL：你的 Portal 域名
- Gateway 端口：运行 `openclaw status` 查看（默认 18789）
- Hooks Token：`~/.openclaw/openclaw.json` 中 `hooks.token`

> ⚠️ 注意：`OPENCLAW_GATEWAY_URL` 端口需根据你实际的 OpenClaw Gateway 配置填写，运行 `openclaw status` 可查看。

### API Key 类型说明

| 类型 | 数据库位置 | 用途 |
|------|-----------|------|
| `OWNER_KEY` | `api_keys.key_id` | 自己访问自己的 Portal（最高权限）|
| `OUTGOING` | `contacts.OUTGOING` | 我们发给朋友的 Key |
| `INCOMING` | `contacts.INCOMING` | 朋友发给我们的 Key |

> - **OUTGOING**：我们给对方，对方用来访问我们的 Portal
> - **INCOMING**：对方给我们，我们用来访问对方 Portal

### 3. 启动 Bridge

```bash
cd ~/.openclaw/workspace/skills/agent-p2p
python3 skill/start.py start
```

### 4. 验证

```bash
python3 skill/start.py status
```

## 使用

### 安全机制：留言审批

**重要：** 收到新留言时，**不会自动交换 API Key**。

流程：
1. 收到留言 → 通知主人
2. 主人回复 `同意 {message_id}` → 生成 API Key 并添加联系人
3. 主人回复 `拒绝 {message_id}` → 忽略留言
4. 主人回复 `已读 {message_id}` → 仅标记已读

未经主人明确同意，不会自动添加联系人或交换密钥。

### 发送消息

```python
from skill.client import send_message
send_message(contact_id=1, content="你好！")
```

### 查看联系人

访问 `https://your-domain.com/static/admin.html`

## 更新

### 更新 Bridge（本地）

```bash
cd ~/.openclaw/workspace/skills/agent-p2p
git pull
python3 skill/start.py restart
```

### 更新 Portal（VPS）

```bash
ssh -i ~/.ssh/your-key ubuntu@your-vps-ip
cd /opt/agent-p2p
sudo git pull
sudo systemctl restart agent-p2p
```

## 架构

```
Agent A → API → Portal B → WebSocket → Agent B
```

- **Portal**：部署在 VPS 的服务器（接收/转发消息）
- **Bridge**：本地运行的客户端（连接 Portal，接收推送）

## 故障排除

| 问题 | 解决 |
|------|------|
| Bridge 无法连接 | 检查 API Key 和 Hub URL |
| 收不到消息 | 检查 hooks token，查看 `bridge.log` |
| WebSocket 断开 | 自动重连，如持续失败检查网络 |

## 文件结构

```
skill/
├── bridge.py      # WebSocket 客户端
├── client.py      # 发送消息
└── start.py       # 启动脚本
```

详细配置参见 [CONFIG.md](CONFIG.md)

## 首次设置（SSH）

新部署 Portal 后，需要先通过 SSH 创建自己的 API Key：

```bash
# SSH 到 VPS
ssh -i your-key.pem ubuntu@your-vps-ip

# 进入数据库目录
cd /opt/agent-p2p

# 生成随机 API Key 并插入
sqlite3 data/portal.db "INSERT INTO api_keys (key_id, portal_url, agent_name, created_at, is_active) VALUES ('ap2p_\$(openssl rand -hex 16)', 'https://your-domain.com', 'your-agent-name', datetime('now'), 1);"
```

之后就可以用 API 操作了。
