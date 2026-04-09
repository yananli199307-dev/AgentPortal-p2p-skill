# develop 本地联调说明

`develop/` 下的内容仅用于本地开发和调试，不作为生产部署入口。

## 目录

- `docker/`：Dockerfile 与 compose 模板
- `scripts/`：环境生成与联调编排脚本
- `runtime/`：本地生成的多环境配置与数据库（已忽略提交）

## 一环境一 Agent 原则

每个 `envN` 只绑定一个独立的龙虾 Agent 身份：

- 独立 API Key
- 独立联系人数据
- 独立日志和状态

不要复用同一个 `envN` 给多个 Agent，避免通信关系串线。

## 快速开始（2 套环境）

```bash
python3 develop/scripts/gen_envs.py --count 2
bash develop/scripts/dev_stack.sh start --count 2
```

启动后：

- **本机浏览器访问 Portal**：优先 **`http://portalN.localhost:1808x`**（`dev_stack.sh` 启动日志里也是这个）；亦可 **`http://localhost:1808x`**。**不要**在本机浏览器依赖 **`http://portalN.ap2p.internal:…`**：该名字默认只出现在 **容器**的 `extra_hosts` 里，Mac 自己不解析；若你坚持本机也用该域名，需在 `/etc/hosts` 手写 `127.0.0.1 portal1.ap2p.internal …`。
- **镜像之间**（龙虾 / bridge 容器里用 HTTP 调 Portal 的**宿主机映射端口**）：用 **`AGENTP2P_PORTAL_PUBLIC_URL`**，即 **`http://portalN.ap2p.internal:1808x`**。`compose` 已为 **lobster* / bridge*** 配好 `portalN.ap2p.internal` → `host-gateway`。容器内不要用 `http://portalN.localhost:…` 调 Portal：Node 会把 **`*.localhost` 固定当成容器自己的 `127.0.0.1`**，与宿主机上映射无关。
- **容器内只连 Portal 服务名**时仍可用 **`http://portalN:8080`**（compose 网络，不经宿主机端口），与上一条场景不同。
- Lobster **仪表盘**：**`http://lobsterN.localhost:18443`**（浏览器安全上下文）。亦可 `http://127.0.0.1:1808x` / `http://localhost:1808x` 打开 Portal。
- Portal 在库内使用的规范地址为 **`http://portalN:8080`**（与 bridge 容器内互通）。新增/交换联系人时，**同一 compose 里的对方请填 `http://portal2:8080` 这类服务名**，勿填 `localhost`，否则 bridge 在容器里会把 `localhost` 指到自身，消息推不到 OpenClaw。若你之前用过旧版脚本（库里是 localhost），请删掉对应的 `develop/runtime/envN/portal.db` 后重新 `dev_stack.sh start` 完成 key 引导。

## 扩容到 3 套

```bash
sudo bash develop/scripts/dev_stack.sh scale --count 3
```

## 每环境独立龙虾容器（可选）

默认桥接到宿主机龙虾网关；如果你希望每个环境一个独立龙虾容器，启动时加参数：

```bash
sudo bash develop/scripts/dev_stack.sh start --count 2 --with-lobster
```

可指定镜像：

```bash
sudo bash develop/scripts/dev_stack.sh start --count 2 --with-lobster --lobster-image your/lobster:image
```

启用后：

- 自动生成 `lobster1..lobsterN` 服务
- `bridgeN` 的 `OPENCLAW_GATEWAY_URL` 自动切到 `http://lobsterN:18789`
- 运行数据挂载到 `develop/runtime/envN/lobster-home`
- 本仓库根目录绑定到容器内 `~/.openclaw/workspace/skills/agent-p2p`，OpenClaw 会按 workspace 技能加载 **agent-p2p**，便于本地改 skill 代码后直接调试
- 宿主机访问入口：`http://127.0.0.1:18790`（lobster1）、`http://127.0.0.1:18791`（lobster2）...

并且每个 `develop/runtime/envN/gateway.env` 会包含：

- `LOBSTER_API_KEY=CHANGE_ME`（请替换成你的龙虾 key）
- `LOBSTER_MODEL=kimi`（默认模型）

另外 `AGENTP2P_API_KEY` 会在 `dev_stack.sh start/scale` 过程中自动写回，不需要手工填写。
`OPENCLAW_HOOKS_TOKEN` 用于 bridge 调网关的 `/hooks/wake`，与仪表盘无关；连接 **OpenClaw 网关仪表盘** 请在 `gateway.env` 里使用 **`OPENCLAW_GATEWAY_TOKEN`**（启动时终端会打印带该 token 的 URL）。若误用 hooks token 反复连接失败，会触发「too many failed authentication attempts」，可重启对应 `lobsterN` 容器或等待几分钟后重试。

若 Control UI 卡在 **pairing required** 或**反复 Authorization 失败**（token 已确认是 `OPENCLAW_GATEWAY_TOKEN`）：本仓库生成的 `openclaw.json` 会对 **`gateway.controlUi`** 打开开发用绕过项 **`dangerouslyDisableDeviceAuth`** 与 **`allowInsecureAuth`**（仅 `develop/runtime`，勿用于生产）。更新后请执行 `python3 develop/scripts/gen_envs.py --patch-moonshot-only --count N` 并 **`docker compose … restart lobsterN`**。访问 **lobster2** 时请用打印里的 **`http://lobster2.localhost:18443/?token=…`**，不要混用 `127.0.0.1:18791`（与 lobster1 共用 Cookie 仍会失败）。若仍异常，可改用 **`#token=…` 放在 URL 哈希** 再试（部分版本对 query token 更敏感）。

若仪表盘里**一直显示正在输入、始终没有回复**或 **401**：国内开放平台密钥必须走 **`https://api.moonshot.cn/v1`**（`gen_envs.py` 现已默认该线路；若你显式写过 `LOBSTER_MOONSHOT_BASE_URL=https://api.moonshot.ai/v1` 且未设 `LOBSTER_MOONSHOT_REGION=intl`，会自动改回 `.cn`）。国际密钥才需要 `LOBSTER_MOONSHOT_REGION=intl`。改完后执行 `gen_envs.py`（或 `--patch-moonshot-only`）并重启 lobster；仍异常时用 `docker logs ap2p-lobster-1` 看网关错误。

会话 jsonl 里若出现 **`401 Invalid Authentication`**（Moonshot），先确认密钥与线路（国际/国内）一致。若 `openclaw.json` 里已是 `sk-...` 仍 401，多半是 **`agents/*/agent/models.json` 被网关写回占位符 `"MOONSHOT_API_KEY"`**（不是环境变量替换）。执行 `python3 develop/scripts/gen_envs.py --patch-moonshot-only --count N` 写回真实密钥（并维护 `lobster-home/.env`），然后 `docker compose -f develop/docker/docker-compose.generated.yml restart lobster1`（按需加 lobster2…）。`dev_stack.sh start --with-lobster` 已自动做一轮 patch + restart。

## 匿名留言与联系人（多环境联调）

- 对方 Agent 在 Portal 前台 **留言** 只会写入 **`guest_messages`**，**不会自动出现联系人**；这是设计（见根目录 **`SKILL.md`**「留言审批」）。
- 要建联：由 **portal2 的主人或龙虾2** 调用 **`POST /api/guest/messages/{message_id}/approve`**，Body 里带上从留言里读到的 **`portal_url`、`agent_name`、`user_name`**（见 `vps/main.py`）。管理后台也可操作。
- **bridge** 通过 WebSocket 收到留言后会 **`/hooks/wake` 对应环境的龙虾**；若你刚更新了本仓库里的 **`local/bridge.py`**，请 **`docker compose build portalN` / `bridgeN` 并重启**（Portal 与 bridge 镜像会打进当前代码）。

## 常用命令

```bash
bash develop/scripts/dev_stack.sh status
bash develop/scripts/dev_stack.sh logs portal 1
bash develop/scripts/dev_stack.sh logs bridge 2
bash develop/scripts/dev_stack.sh stop
```

## 容器外调试命令

使用 `develop/scripts/send_dev.py` 和 `develop/scripts/start_dev.py` 按环境读取 `develop/runtime/envN/gateway.env`：

```bash
python3 develop/scripts/send_dev.py --env-index 1 --list
python3 develop/scripts/send_dev.py "hello" --to-contact 1 --env-index 1
python3 develop/scripts/start_dev.py status --env-index 1
```
