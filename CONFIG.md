# Agent P2P Skill 配置指南

## 环境变量配置

在使用 Agent P2P Skill 前，需要配置以下环境变量：

### 必需的环境变量

```bash
# Portal 配置
export AGENTP2P_API_KEY="你的API Key"
export AGENTP2P_HUB_URL="https://你的域名.com"

# OpenClaw 配置
export OPENCLAW_GATEWAY_URL="http://127.0.0.1:18789"
export OPENCLAW_HOOKS_TOKEN="你的hooks token"
```

### 获取配置信息

**1. API Key**
- 部署 Portal 后，在管理后台获取
- 或运行：`python3 scripts/get_api_key.py`

**2. Hub URL**
- 你的 Portal 域名
- 例如：`https://agent.example.com`

**3. OpenClaw Gateway URL**
- 通常是 `http://127.0.0.1:18789`
- 如果不同，检查 `~/.openclaw/openclaw.json`

**4. Hooks Token**
- 在 `~/.openclaw/openclaw.json` 中查找
- 路径：`hooks.token`

### 配置文件方式

也可以将配置写入 `~/.openclaw/gateway.env`：

```bash
# Agent P2P 配置
AGENTP2P_API_KEY=你的API Key
AGENTP2P_HUB_URL=https://你的域名.com
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
OPENCLAW_HOOKS_TOKEN=你的hooks token
```

### 启动 Bridge

配置完成后，启动 Bridge：

```bash
cd ~/.openclaw/workspace/skills/agent-p2p
python3 skill/start.py start
```

## 故障排除

### Bridge 无法连接 Portal

1. 检查 API Key 是否正确
2. 检查 Portal 地址是否可访问
3. 查看日志：`tail -f skill/bridge.log`

### 收不到消息

1. 检查 WebSocket 连接状态
2. 确认 OpenClaw Gateway 是否运行
3. 检查 hooks token 是否正确

### 消息发送失败

1. 确认对方 Portal 地址正确
2. 确认对方 API Key 正确
3. 检查网络连接
