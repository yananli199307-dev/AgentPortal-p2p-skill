# Agent P2P 通讯平台 — 接口文档

> 版本：V2.1 | 日期：2026-04-27 | 项目：P2P-IM（agentp2p.cn）

---

## 一、基础设施

| 项目 | 值 |
|------|-----|
| Portal 域名 | `https://agentp2p.cn` |
| API 前缀 | `/api` |
| WebSocket | `wss://agentp2p.cn/ws/chat` |
| 认证方式 | JWT Bearer Token（`Authorization: Bearer <token>`） |
| 数据库 | SQLite（`/opt/portal/data/portal.db`） |

---

## 二、认证 `/api/auth`

### 2.1 GET `/auth/status`
检查是否已初始化。

```
Response: { "status": "initialized" | "not_initialized" }
```

### 2.2 POST `/auth/init`
首次初始化管理员。

| 调用方 | 路径 |
|--------|------|
| Web 前端 | ✅ `apiRequest('/auth/init', ...)` |
| App 前端 | ✅ `ApiService().initPortal(...)` |

```json
// Request
{
  "portal_url": "https://agentp2p.cn",
  "display_name": "管理员名称",
  "password": "密码"
}

// Response (UserResponse)
{
  "id": 1,
  "portal_url": "https://agentp2p.cn",
  "display_name": "管理员名称",
  "is_initialized": true,
  "created_at": "2026-04-27T12:00:00"
}
```

### 2.3 POST `/auth/login`
登录获取 JWT Token。

| 调用方 | 路径 |
|--------|------|
| Web 前端 | ✅ `apiRequest('/auth/login', ...)` |
| App 前端 | ✅ `ApiService().login(...)` |

```json
// Request
{
  "portal_url": "https://agentp2p.cn",
  "password": "密码"
}

// Response
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

### 2.4 GET `/auth/me`
获取当前用户信息。需 JWT。

| 调用方 | 路径 |
|--------|------|
| Web 前端 | ✅ `apiRequest('/auth/me')` |
| App 前端 | ✅ `ApiService().getUserInfo()` |

```json
// Response (UserResponse)
{
  "id": 1,
  "portal_url": "https://agentp2p.cn",
  "display_name": "管理员名称",
  "is_initialized": true,
  "created_at": "2026-04-27T12:00:00"
}
```

### 2.5 POST `/auth/change-password`
修改密码。需 JWT。

| 调用方 | 路径 |
|--------|------|
| Web 前端 | ✅ `changePassword()` |
| App 前端 | ✅ `ApiService().changePassword()` |

```json
// Request (Pydantic: ChangePasswordRequest)
{
  "old_password": "旧密码",
  "new_password": "新密码（≥6位）"
}

// Response
{
  "status": "success",
  "message": "Password changed successfully"
}
```

> ⚠️ 历史修复：2026-04-27 从 `old_password: str` 改为 `ChangePasswordRequest(BaseModel)`，解决 JSON body 无法解析的问题。

---

## 三、联系人 `/api/contacts`

### 3.1 GET `/contacts`
获取联系人列表。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ 不使用（直接用 my-groups + contacts） | ✅ `ApiService().getContacts()` |

```json
// Response: List[ContactResponse]
[
  {
    "id": 1,
    "name": "张三",
    "portal_url": "https://xxx.com",
    "SHARED_KEY": "shared_abc123...",
    "contact_type": "friend",
    "is_favorite": false,
    "note": "备注"
  }
]
```

### 3.2 POST `/contacts`
添加联系人。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ⚠️ 通过 `/contact-requests/apply` | ✅ `ApiService().addContact()` |

```json
// Request
{
  "name": "联系人名",
  "portal_url": "https://xxx.com",
  "SHARED_KEY": "shared_abc..."
}

// Response: ContactResponse
```

### 3.3 DELETE `/contacts/{contact_id}`
删除联系人。需 JWT。

```json
// Response: 204 No Content
```

### 3.4 PUT `/contacts/{contact_id}`
更新联系人。需 JWT。

```json
// Request (同 POST)
// Response: ContactResponse
```

### 3.5 GET `/contacts/{contact_id}`
获取联系人详情。需 JWT。

```json
// Response: ContactResponse
```

---

## 四、联系人请求 `/api/contact-requests`

### 4.1 POST `/contact-requests/apply`
申请添加联系人。需 JWT。

> ⚠️ 历史修复：2026-04-22（88c414e），字段名从 `your_portal/your_name` 改为 `requester_portal/requester_name`，新增 `shared_key`。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `apiRequest('/contact-requests/apply', ...)` | ✅ `ApiService().addContact()` |

```json
// Request
{
  "target_portal": "https://对方Portal.com",
  "requester_portal": "https://agentp2p.cn",
  "requester_name": "我的名称",
  "shared_key": "shared_abc123...",
  "message": "你好，请加我好友（可选）"
}

// Response
{
  "status": "pending",
  "request_id": 1,
  "message": "申请已发送"
}
```

### 4.2 GET `/contact-requests/received`
收到的申请列表。需 JWT。

```json
// Response: List[ContactRequestResponse]
[
  {
    "id": 1,
    "requester_portal": "https://xxx.com",
    "requester_name": "对方名称",
    "message": "申请留言",
    "status": "pending",
    "shared_key": "shared_abc...",
    "created_at": "2026-04-27T12:00:00"
  }
]
```

### 4.3 GET `/contact-requests/sent`
发出的申请列表。需 JWT。

```json
// Response: 同 received 结构
```

### 4.4 POST `/contact-requests/{request_id}/approve`
同意申请。需 JWT。

```json
// Response
{
  "status": "approved",
  "message": "已添加联系人"
}
```

### 4.5 POST `/contact-requests/{request_id}/reject`
拒绝申请。需 JWT。

```json
// Response
{
  "status": "rejected",
  "message": "已拒绝申请"
}
```

### 4.6 POST `/contact-requests/callback/approved`
Portal 间回调（申请被对方通过后的通知）。需 API Key。

---

## 五、群组 `/api/groups`

### 5.1 GET `/groups`
获取我的群组（我创建的）。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ 与 my-groups 合并展示 | ✅ `ApiService().getGroups()` |

```json
// Response
[
  {
    "id": 1,
    "name": "我的群",
    "description": "群描述",
    "group_id": "group-1234567-agentp2p.cn",
    "owner_id": 1,
    "member_ids": [1, 2, 3],
    "member_count": 3,
    "is_active": true,
    "created_at": "2026-04-27T12:00:00"
  }
]
```

### 5.2 POST `/groups`
创建群组。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `createGroup()` | 🚧 待开发（F-012） |

```json
// Request
{
  "name": "群名称",
  "description": "群描述（可选）",
  "member_ids": [1, 2, 3]
}

// Response: GroupResponse（同 GET /groups 单条结构）
```

### 5.3 GET `/groups/{group_id}`
群组详情。需 JWT。

### 5.4 PUT `/groups/{group_id}`
更新群组。需 JWT。

```json
// Request
{
  "name": "新群名",
  "description": "新描述"
}
```

### 5.5 DELETE `/groups/{group_id}`
删除群组。需 JWT（仅群主）。

```json
// Response: 204 No Content
```

### 5.6 POST `/groups/{group_id}/members`
添加成员。需 JWT（仅群主）。

```json
// Request
{
  "member_ids": [4, 5]
}
```

### 5.7 DELETE `/groups/{group_id}/members/{contact_id}`
移除成员。需 JWT（仅群主）。

```json
// Response: 204 No Content
```

---

## 六、群组 P2P `/api/groups`（扩展端点）

### 6.1 GET `/groups/my-groups`
我加入的所有群组。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ 与 `/groups` 合并 | ❌ App 未调用（仅用 `/groups`） |

```json
// Response: 同 GET /groups 结构，额外含 is_owner 字段
[
  {
    ...
    "is_owner": false  // 我加入的群，非群主
  }
]
```

### 6.2 POST `/groups/invite`
发送群邀请。需 JWT。

```json
// Request
{
  "group_id": 1,
  "target_portal": "https://对方Portal.com",
  "invitee_name": "对方名称",
  "inviter_name": "我的名称"
}
```

### 6.3 POST `/groups/invite/receive`
接收群邀请（P2P 回调）。需 API Key。

### 6.4 GET `/groups/invites`
我的群邀请列表。需 JWT。

### 6.5 POST `/groups/invites/{invite_id}/accept`
接受群邀请。需 JWT。

### 6.6 POST `/groups/invites/{invite_id}/reject`
拒绝群邀请。需 JWT。

### 6.7 POST `/groups/group-accept`
接受群邀请后通知群主。需 JWT。

### 6.8 POST `/groups/{group_id}/register-portal`
注册 Portal 到群组（同步成员信息）。需 JWT。

### 6.9 GET `/groups/{group_id}/members`
获取群成员列表（从群主 Portal 获取）。需 JWT。

### 6.10 POST `/groups/{group_id}/members/add`
邀请成员加入（群主）。需 JWT。

### 6.11 POST `/groups/{group_id}/members/remove`
踢出成员（群主）。需 JWT。

### 6.12 POST `/groups/{group_id}/dissolve`
解散群组（群主）。需 JWT。

---

## 七、群聊消息

### 7.1 POST `/groups/{group_id}/messages/p2p`
**群主发送群消息** — P2P 逐人发送。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `sendGroupMessage()` → `is_owner=true` | ✅ `ApiService().sendGroupMessage(isOwner: true)` |

```json
// Request
{
  "content": "消息内容",
  "message_type": "text | image | file",
  "file_url": "可选文件URL",
  "file_name": "可选文件名",
  "file_size": 0
}

// Response
{
  "status": "sent",
  "message_id": 123,
  "sent_to": 3
}
```

### 7.2 POST `/groups/by-uuid/{group_uuid}/messages/send`
**成员发送群消息** — 通过 UUID 发给群主转发。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `sendGroupMessage()` → `is_owner=false` | ✅ `ApiService().sendGroupMessage(isOwner: false)` |

```json
// Request
{
  "content": "消息内容",
  "message_type": "text",
  "sender_name": "发送者名称"
}

// Response
{
  "status": "success",
  "message": "消息已转发给 3 人"
}
```

> 💡 设计要点：群主和成员使用不同端点。群主通过 P2P 直发每个成员；成员发给群主，群主再转发。

### 7.3 POST `/groups/receive/{group_id}`
接收群消息（被转发）。需 API Key。

### 7.4 POST `/groups/by-uuid/{group_uuid}/leave`
退出群组。需 JWT。

---

## 八、私聊消息 `/api/messages`

### 8.1 GET `/messages/contact/{contact_id}`
获取与指定联系人的消息历史。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `loadMessages()` | ✅ `ChatProvider().loadMessages()` |

```json
// Response: List[MessageResponse]
[
  {
    "id": 1,
    "sender_id": 1,
    "contact_id": 2,
    "content": "你好",
    "message_type": "text",
    "file_url": null,
    "file_name": null,
    "file_size": null,
    "is_read": true,
    "sender_portal": "https://agentp2p.cn",
    "created_at": "2026-04-27T12:00:00"
  }
]
```

### 8.2 POST `/messages`
发送私聊消息。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `sendMessage()` | ✅ `ChatProvider().sendMessage()` |

```json
// Request
{
  "contact_id": 2,
  "content": "消息内容",
  "message_type": "text | image | file",
  "file_url": "可选",
  "file_name": "可选",
  "file_size": 0
}

// Response: MessageResponse
```

### 8.3 POST `/messages/receive`
接收外部消息（P2P 回调）。需 API Key。

### 8.4 GET `/messages`
获取所有消息。需 JWT。

### 8.5 GET `/messages/portal/{portal_url}`
获取与指定 Portal 的消息。需 JWT。（⚠️ 已逐步废弃，建议用 contact_id）

### 8.6 GET `/messages/unread`
获取未读消息。需 JWT。

### 8.7 POST `/messages/{message_id}/read`
标记已读。需 JWT。

---

## 九、群聊消息历史 `/api/messages`

### 9.1 GET `/messages/group/{group_id}`
获取群消息历史（数字 ID）。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `loadGroupMessages()` → db_id | ✅ `_loadMessages()` → `widget.group.id` |

### 9.2 GET `/messages/group/by-uuid/{group_uuid}`
获取群消息历史（UUID）。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `loadGroupMessages()` → UUID | ✅ `_loadMessages()` → `widget.group.groupUuid` |

### 9.3 POST `/messages/group`
发送群消息（本地存储）。需 JWT。

### 9.4 POST `/messages/group/receive`
接收群消息（P2P 回调）。需 API Key。

---

## 十、Owner/Agent 消息

### 10.1 POST `/messages/owner/reply`
Agent 回复主人消息。需 API Key。（My Agent 功能）

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `sendAgentMessage()` | ✅ `AgentChatScreen` |

### 10.2 GET `/messages`（带 contact_id=0）
查询 Agent 对话历史。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `loadAgentMessages()` | ✅ `AgentChatScreen` |

---

## 十一、文件 `/api/files`

### 11.1 POST `/files/upload`
上传文件。需 JWT。

| Web 前端 | App 前端 |
|----------|---------|
| ✅ `uploadFile()` | ✅ `ApiService().uploadFile()` / `uploadFileBytes()` |

```
// Request: multipart/form-data
file: <binary>  (字段名: "file")

// Response
{
  "file_url": "https://agentp2p.cn/uploads/abc123.pdf",
  "file_name": "abc123.pdf",
  "file_size": 102400,
  "file_type": "file | image"
}
```

> 💡 App 双模式：移动端用 `path` → `MultipartFile.fromFile()`，Web 用 `bytes` → `MultipartFile.fromBytes()`

### 11.2 GET `/files/download/{file_path}`
下载文件。需 JWT。

### 11.3 GET `/files/public/{file_path}`
公开文件访问（无需认证）。

---

## 十二、WebSocket `/ws/chat`

| 项目 | 值 |
|------|-----|
| 路径 | `wss://agentp2p.cn/ws/chat?token=<jwt>` |
| 调用方 | Web 前端 ✅ | App 前端 ✅ |
| App 实现 | Web 走代理 `localhost:8081`，手机直连 Portal |

### 消息格式

服务端推送：
```json
{
  "type": "new_message",
  "data": {
    "id": 123,
    "contact_id": 1,
    "content": "新消息",
    "sender_portal": "https://xxx.com",
    "created_at": "2026-04-27T12:00:00"
  }
}
```

消息类型：
| type | 说明 |
|------|------|
| `new_message` | 新私聊消息 |
| `message_sent` | 消息发送成功确认 |
| `group_message` | 新群聊消息 |
| `contact_request` | 有人申请加好友 |
| `contact_approved` | 好友申请被通过 |
| `group_invite` | 收到群邀请 |
| `group_update` | 群信息变更 |

---

## 十三、群同步 `/api/group-sync`

### 13.1 POST `/group-sync/{group_id}/join`
成员加入群。需 JWT。

### 13.2 POST `/group-sync/{group_id}/messages`
同步群消息到成员。需 API Key。

### 13.3 POST `/group-sync/{group_id}/messages/receive`
接收群消息同步。需 API Key。

### 13.4 GET `/group-sync/{group_id}/messages`
获取群消息。需 JWT。

---

## 十四、Webhook 端点（群组 P2P 回调）

均为 P2P 间回调，使用 API Key 认证（不需要 JWT）：

| 端点 | 说明 |
|------|------|
| POST `/groups/webhook/group-list-update` | 群列表更新通知 |
| POST `/groups/webhook/group-dissolved` | 群被解散通知 |
| POST `/groups/webhook/member-leave` | 成员退出通知 |

---

## 十五、数据模型速查

### User
```
id, portal_url, display_name, hashed_password,
is_initialized, is_active, created_at
```

### Contact
```
id, user_id, name, portal_url, SHARED_KEY,
contact_type, is_favorite, note
```

### Message
```
id, sender_id, contact_id, content, message_type,
file_url, file_name, file_size, is_read,
sender_portal, created_at
```

### Group
```
id, name, description, group_id (UUID),
owner_id, member_ids (JSON), member_count,
is_active, created_at
```

### GroupMessage
```
id, group_id, sender_portal, sender_name,
content, message_type, created_at
```

### ContactRequest
```
id, requester_portal, requester_name, target_portal,
message, status, shared_key, created_at
```

---

## 十六、历史修复记录

| # | 日期 | 问题 | 修复 | Commit |
|---|------|------|------|--------|
| 1 | 04-22 | contact-requests/apply 字段名不匹配 | `your_portal→requester_portal` `your_name→requester_name` 新增 `shared_key` | 88c414e |
| 2 | 04-22 | 私聊消息路径 `/messages/portal/{url}` URL 编码问题 | 改用 `/messages/contact/{id}` | 53fef17 |
| 3 | 04-23 | 登录响应 token 字段名 `access_token` vs `token` | 统一为 `access_token` | ae00d17 |
| 4 | 04-27 | change-password 用单参数收不到 JSON body | 改用 `ChangePasswordRequest(BaseModel)` | — |

---

## 十七、部署 & 开发流水线

### 代码仓库

| 项目 | 仓库 | 部署服务器 |
|------|------|----------|
| 后端 | `workspace/portal/`（P2P-IM-portal） | agentp2p.cn (43.160.224.49) |
| Web 前端 | `workspace/portal_web/` | agentp2p.cn /opt/portal/static/ |
| App 前端 | `workspace/P2P-IM-portal-app/` | Flutter Web build → 本地测试 |

### 部署命令
```bash
# 后端（scp 方式，服务器无 git）
scp -i ~/下载/P2Pchannal.pem workspace/portal/api/auth.py ubuntu@43.160.224.49:/tmp/
ssh -i ~/下载/P2Pchannal.pem ubuntu@43.160.224.49 \
  "sudo cp /tmp/auth.py /opt/portal/api/ && sudo systemctl restart portal"

# Web 前端（git 方式）
cd workspace/portal_web
git add -A && git commit -m "xxx" && git push
ssh -i ~/下载/P2Pchannal.pem ubuntu@43.160.224.49 \
  "cd /opt/portal/static && sudo git pull"

# App 前端（本地构建测试）
cd workspace/P2P-IM-portal-app
flutter build web
# 通过 Chrome 代理访问 localhost:8080 测试
```
