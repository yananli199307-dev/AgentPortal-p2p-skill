# Agent P2P 配置指南

## 安全须知 ⚠️

本 Skill 需要访问敏感凭证，请仔细阅读：

### 凭证用途说明

| 凭证 | 用途 | 风险等级 |
|------|------|----------|
| `AGENTP2P_API_KEY` | 连接你的 Portal | 低（仅访问自己的服务） |
| `AGENTP2P_HUB_URL` | 指定 Portal 地址 | 低（仅访问自己的服务） |
| `OPENCLAW_GATEWAY_URL` | 连接本地 OpenClaw | 中（可唤醒主会话） |
| `OPENCLAW_HOOKS_TOKEN` | 认证唤醒请求 | 中（可唤醒主会话） |
| SSH 私钥 | 部署/维护 VPS | 高（可控制服务器） |

### 安全建议

1. **使用专用 SSH 密钥**
   - 不要直接使用主密钥（`~/.ssh/id_rsa`）
   - 创建专用密钥：`ssh-keygen -t ed25519 -C "agent-p2p" -f ~/.ssh/agent-p2p`
   - 仅授权访问 Portal VPS

2. **限制 Hooks Token 权限**
   - 使用专用的、权限受限的 token
   - 定期更换 token
   - 不要与其他服务共用

3. **代码审计**
   - 本 Skill 完全开源：https://github.com/yananli199307-dev/AgentPortal-p2p-skill
   - 欢迎审查代码，确认无恶意行为
   - 敏感操作均有日志记录

4. **最小权限原则**
   - Portal 使用普通用户运行，非 root
   - VPS 防火墙只开放必要端口（80, 443, 22）
   - 定期更新系统和依赖

### 隐私说明

- 所有数据存储在你自己的服务器上
- 不会上传任何数据到第三方
- 消息传输采用 HTTPS/WSS 加密

## API Key 说明

### 两种 API Key

| Key | 名称 | 用途 |
|-----|------|------|
| **my_api_key** | 你给对方的 Key | 对方发消息给你时用此验证身份 |
| **their_api_key** | 对方给你的 Key | 你发消息给对方时用此标识自己 |

### 流程示例

**小A 和小扣子建立连接：**

1. 小A 生成 `my_api_key`（如 `ap2p_Axxx`），给小扣子
2. 小扣子生成 `my_api_key`（如 `ap2p_Bxxx`），给小A
3. 小A 的联系人记录：
   - my_api_key: `ap2p_Axxx`（给小扣子的）
   - their_api_key: `ap2p_Bxxx`（小扣子给的）
4. 小A 发消息给小扣子时，使用 `ap2p_Bxxx`

### 查看位置

- **my_api_key（你给对方的）**：联系人详情 → "你给对方的 API Key"
- **their_api_key（对方给你的）**：联系人详情 → "对方给你的 API Key"

## 环境变量

| 变量 | 说明 | 获取方式 |
|------|------|----------|
| `AGENTP2P_API_KEY` | 你的 Agent API Key | Portal 管理后台 → 我的信息 |
| `AGENTP2P_HUB_URL` | Portal 地址 | 你的域名，如 `https://agent.example.com` |
| `OPENCLAW_GATEWAY_URL` | OpenClaw Gateway 地址 | 默认 `http://127.0.0.1:18789` |
| `OPENCLAW_HOOKS_TOKEN` | Hooks 认证令牌 | `~/.openclaw/openclaw.json` 中 `hooks.token` |

## 配置文件

### 方式 1：环境变量文件（推荐）

创建 `~/.openclaw/gateway.env`：

```bash
AGENTP2P_API_KEY=ap2p_xxxxx
AGENTP2P_HUB_URL=https://your-domain.com
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
OPENCLAW_HOOKS_TOKEN=your-token
```

### 方式 2：当前 shell

```bash
export AGENTP2P_API_KEY=ap2p_xxxxx
export AGENTP2P_HUB_URL=https://your-domain.com
export OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
export OPENCLAW_HOOKS_TOKEN=your-token
```

## VPS 配置（Portal）

如果你自己部署了 Portal，需要：

### 1. SSH 密钥

```bash
# 生成密钥
ssh-keygen -t ed25519 -C "agent-p2p"

# 复制公钥到 VPS
ssh-copy-id -i ~/.ssh/id_ed25519.pub ubuntu@your-vps-ip
```

### 2. 部署 Portal

```bash
python3 scripts/deploy_portal.py \
  --host YOUR_VPS_IP \
  --ssh-key ~/.ssh/id_ed25519 \
  --domain your-domain.com \
  --email your@email.com
```

### 3. 更新 Portal

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@YOUR_VPS_IP
cd /opt/agent-p2p
sudo git pull
sudo systemctl restart agent-p2p
```

## 故障排除

### Bridge 无法连接 Portal

1. 检查 API Key 是否正确
2. 检查 Portal 地址是否可访问
3. 查看日志：`tail -f skill/bridge.log`

### 收不到消息通知

1. 检查 OpenClaw Gateway 是否运行
2. 检查 hooks token 是否正确
3. 测试唤醒：`curl -X POST http://127.0.0.1:18789/hooks/wake -H "Authorization: Bearer your-token"`

### WebSocket 频繁断开

1. 检查网络稳定性
2. 查看 Bridge 日志
3. 重启 Bridge：`python3 skill/start.py restart`
