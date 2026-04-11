#!/bin/bash
# ============================================================
# Agent P2P Portal - VPS 一键安装脚本
#
# 用法: bash vps_install.sh <HOST> [PORT] [REPO_URL]
#
#   HOST    : VPS 的 IP 或域名（不需要 DNS 解析，不需要域名）
#   PORT    : 监听端口（默认 18080，高位端口无需 root）
#   REPO_URL: 仓库地址（默认指向本仓库）
#
# 示例:
#   bash vps_install.sh 1.2.3.4               # 默认端口 18080
#   bash vps_install.sh 1.2.3.4 9443          # 指定端口 9443
#   bash vps_install.sh my.host.com 18080     # 用域名作为 HOST
#
# 输出规范（AI 可 grep）:
#   成功: INSTALL_OK API_KEY=ap2p_xxx PORTAL_URL=https://HOST:PORT
#   失败: INSTALL_FAILED STEP=xxx ERROR=<msg>
#
# SSL: openssl 生成自签证书，无需 nginx/certbot/域名
#      bridge.py/send.py 已内置 verify=False，自签证书完全兼容
#
# 检查点: /opt/agent-p2p/.install_state.json（断点续装，重跑跳过已完成步骤）
# step_06 的 restart 每次都执行（确保代码更新后生效）
# ============================================================

set -euo pipefail

HOST="${1:-}"
PORT="${2:-18080}"
REPO_URL="${3:-https://github.com/youyli03/AgentPortal-p2p-skill.git}"
INSTALL_DIR="/opt/agent-p2p"
STATE_FILE="$INSTALL_DIR/.install_state.json"
VENV="$INSTALL_DIR/venv"
SSL_KEY="$INSTALL_DIR/ssl/key.pem"
SSL_CERT="$INSTALL_DIR/ssl/cert.pem"

log_info()  { echo "[INFO] $*"; }
log_warn()  { echo "[WARN] $*"; }
log_error() { echo "[ERROR] $*"; }

# ── 参数校验 ─────────────────────────────────────────────────
if [[ -z "$HOST" ]]; then
    echo "用法: bash vps_install.sh <HOST> [PORT] [REPO_URL]"
    echo "  HOST: VPS IP 或域名（如 1.2.3.4）"
    echo "  PORT: 监听端口，默认 18080"
    echo "INSTALL_FAILED STEP=params ERROR=missing_host"
    exit 1
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 ]] || [[ "$PORT" -gt 65535 ]]; then
    echo "INSTALL_FAILED STEP=params ERROR=invalid_port_${PORT}"
    exit 1
fi

if [[ "$PORT" -lt 1024 ]] && [[ "$(id -u)" -ne 0 ]]; then
    echo "INSTALL_FAILED STEP=params ERROR=port_${PORT}_requires_root"
    exit 1
fi

# ── 内网 IP 检测：自动探测公网 IP ────────────────────────────
is_private_ip() {
    local ip="$1"
    [[ "$ip" =~ ^10\. ]] && return 0
    [[ "$ip" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. ]] && return 0
    [[ "$ip" =~ ^192\.168\. ]] && return 0
    [[ "$ip" =~ ^127\. ]] && return 0
    return 1
}

if is_private_ip "$HOST"; then
    log_warn "⚠️  检测到内网 IP: $HOST"
    log_warn "   内网 IP 无法从外部访问，正在自动探测公网 IP..."
    PUBLIC_IP=""
    PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null) || true
    [[ -z "$PUBLIC_IP" ]] && PUBLIC_IP=$(curl -s --max-time 5 https://ip.sb 2>/dev/null) || true
    [[ -z "$PUBLIC_IP" ]] && PUBLIC_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null) || true
    if [[ -z "$PUBLIC_IP" ]] || is_private_ip "$PUBLIC_IP"; then
        echo "INSTALL_FAILED STEP=params ERROR=private_ip_and_no_public_ip_detected HOST=$HOST"
        echo ""
        echo "═══════════════════════════════════════════════════════"
        echo "⛔ 错误：传入的 HOST 是内网地址 ($HOST)，且无法自动探测公网 IP。"
        echo ""
        echo "请重新运行脚本并传入 VPS 的公网 IP 地址，例如："
        echo "  bash vps_install.sh 39.96.x.x $PORT"
        echo ""
        echo "你可以在 VPS 控制台 / 云厂商页面找到公网 IP。"
        echo "提示给 Agent：请向用户索取 VPS 公网 IP（非内网 192.168/10.x），"
        echo "         不要使用 hostname -I 或 ifconfig 获取地址。"
        echo "═══════════════════════════════════════════════════════"
        exit 1
    fi
    log_warn "   自动使用公网 IP: $PUBLIC_IP（替代内网 IP: $HOST）"
    HOST="$PUBLIC_IP"
fi

PORTAL_URL="https://${HOST}:${PORT}"
log_info "Portal URL 将是: $PORTAL_URL"

# ── 检查点工具 ───────────────────────────────────────────────
checkpoint_done() {
    local step="$1"
    mkdir -p "$INSTALL_DIR"
    local state="{}"
    [[ -f "$STATE_FILE" ]] && state=$(cat "$STATE_FILE" 2>/dev/null || echo "{}")
    python3 -c "
import json, sys
d = json.loads(sys.argv[1])
d[sys.argv[2]] = 'done'
print(json.dumps(d))
" "$state" "$step" > "$STATE_FILE"
    log_info "步骤 $step 完成"
}

checkpoint_skip() {
    local step="$1"
    [[ ! -f "$STATE_FILE" ]] && return 1
    local status
    status=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get(sys.argv[2],''))
" "$STATE_FILE" "$step" 2>/dev/null || echo "")
    [[ "$status" == "done" ]]
}

fail() {
    local step="$1"; local error="$2"
    log_error "步骤 $step 失败: $error"
    echo "INSTALL_FAILED STEP=$step ERROR=$error"
    exit 1
}

# ── step_01: 安装系统依赖 ─────────────────────────────────────
step_01_install_deps() {
    checkpoint_skip "step_01" && { log_info "跳过 step_01"; return 0; }
    log_info "=== step_01: 安装系统依赖 ==="
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || fail "step_01" "apt_update_failed"
    # 不需要 nginx / certbot / apache2-utils
    apt-get install -y -qq git curl wget python3 python3-venv python3-pip sqlite3 openssl \
        || fail "step_01" "apt_install_failed"
    checkpoint_done "step_01"
}

# ── step_02: 克隆/更新仓库 ───────────────────────────────────
step_02_clone_repo() {
    checkpoint_skip "step_02" && { log_info "跳过 step_02"; return 0; }
    log_info "=== step_02: 克隆仓库 ==="
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        git -C "$INSTALL_DIR" pull --ff-only || fail "step_02" "git_pull_failed"
    else
        rm -rf "$INSTALL_DIR"
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" || fail "step_02" "git_clone_failed"
    fi
    chown -R "$(whoami):$(whoami)" "$INSTALL_DIR"
    checkpoint_done "step_02"
}

# ── step_03: Python venv ──────────────────────────────────────
step_03_python_venv() {
    checkpoint_skip "step_03" && { log_info "跳过 step_03"; return 0; }
    log_info "=== step_03: Python venv + 依赖 ==="
    python3 -m venv "$VENV" || fail "step_03" "venv_create_failed"
    "$VENV/bin/pip" install --upgrade pip -q
    "$VENV/bin/pip" install -q \
        fastapi "uvicorn[standard]" "python-jose[cryptography]" \
        python-multipart websockets pytz requests \
        || fail "step_03" "pip_install_failed"
    checkpoint_done "step_03"
}

# ── step_04: 生成自签名 SSL 证书 ─────────────────────────────
# 无需 nginx / certbot / 域名
# bridge.py 和 send.py 均已内置 verify=False，自签证书完全兼容
step_04_ssl_cert() {
    checkpoint_skip "step_04" && { log_info "跳过 step_04（证书已存在）"; return 0; }
    log_info "=== step_04: 生成自签名 SSL 证书 ==="
    mkdir -p "$INSTALL_DIR/ssl"
    openssl req -x509 -newkey rsa:2048 \
        -keyout "$SSL_KEY" -out "$SSL_CERT" \
        -days 3650 -nodes -subj "/CN=${HOST}/O=AgentP2P/C=CN" \
        || fail "step_04" "openssl_cert_failed"
    chmod 600 "$SSL_KEY"
    log_info "证书生成完成（有效期 10 年）: $SSL_CERT"
    checkpoint_done "step_04"
}

# ── step_05: 初始化数据库 + 生成 API Key ──────────────────────
step_05_init_db() {
    checkpoint_skip "step_05" && { log_info "跳过 step_05"; return 0; }
    log_info "=== step_05: 初始化数据库 + 生成 API Key ==="
    mkdir -p "$INSTALL_DIR/data"

    # 写出初始化脚本（避免 heredoc 嵌套）
    cat > /tmp/_ap2p_init_db.py << 'PYSCRIPT'
import sqlite3, secrets, sys, os
db = sys.argv[1]; portal_url = sys.argv[2]
os.makedirs(os.path.dirname(db), exist_ok=True)
conn = sqlite3.connect(db); cur = conn.cursor()
cur.executescript("""
CREATE TABLE IF NOT EXISTS api_keys (
    key_id TEXT PRIMARY KEY, portal_url TEXT NOT NULL,
    agent_name TEXT, user_name TEXT, description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS guest_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
    ip_address TEXT, user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, portal_url TEXT UNIQUE NOT NULL,
    display_name TEXT, agent_name TEXT, user_name TEXT,
    SHARED_KEY TEXT NOT NULL, is_verified BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_portal TEXT NOT NULL, to_portal TEXT NOT NULL,
    content TEXT NOT NULL, message_type TEXT DEFAULT 'text',
    sender_api_key TEXT, file_url TEXT,
    is_delivered BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS file_transfers (
    file_id TEXT PRIMARY KEY, filename TEXT, md5 TEXT, chunks_total INTEGER,
    from_portal TEXT, to_portal TEXT, status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, completed_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS file_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT,
    chunk_index INTEGER, data BLOB);
""")
cur.execute("SELECT key_id FROM api_keys WHERE is_active=1 LIMIT 1")
row = cur.fetchone()
if row:
    print(row[0])
else:
    k = "ap2p_" + secrets.token_urlsafe(32)
    cur.execute("INSERT INTO api_keys VALUES (?,?,?,?,?,datetime('now'),1)",
                (k, portal_url, "default_agent", "admin", "Auto-generated by vps_install.sh"))
    conn.commit()
    print(k)
conn.close()
PYSCRIPT

    local api_key
    api_key=$("$VENV/bin/python3" /tmp/_ap2p_init_db.py \
        "$INSTALL_DIR/data/portal.db" "$PORTAL_URL") \
        || fail "step_05" "db_init_failed"

    if [[ -z "$api_key" ]]; then
        fail "step_05" "api_key_empty"
    fi

    echo "API_KEY=$api_key" > "$INSTALL_DIR/.api_key"
    chmod 600 "$INSTALL_DIR/.api_key"
    log_info "API Key 已保存: $INSTALL_DIR/.api_key"
    checkpoint_done "step_05"
}

# ── step_06: systemd 服务 ──────────────────────────────────────
# 检查点只保护"写 service 文件"；restart 每次都执行，确保代码更新后生效
step_06_systemd() {
    log_info "=== step_06: 配置并重启 systemd 服务 ==="

    if ! checkpoint_skip "step_06"; then
        cat > /etc/systemd/system/agent-p2p.service << SVCEOF
[Unit]
Description=Agent P2P Portal
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${INSTALL_DIR}
Environment=PORTAL_URL=${PORTAL_URL}
Environment=DATABASE_PATH=${INSTALL_DIR}/data/portal.db
ExecStart=${VENV}/bin/uvicorn vps.main:app --host 0.0.0.0 --port ${PORT} --ssl-keyfile ${SSL_KEY} --ssl-certfile ${SSL_CERT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload
        systemctl enable agent-p2p
        checkpoint_done "step_06"
        log_info "service 文件已创建并 enable"
    else
        log_info "service 文件已存在（跳过写入），执行 daemon-reload"
        systemctl daemon-reload
    fi

    log_info "重启 agent-p2p 服务..."
    systemctl restart agent-p2p || fail "step_06" "service_start_failed"

    for i in $(seq 1 20); do
        sleep 1
        if systemctl is-active --quiet agent-p2p; then
            log_info "服务已启动（等待 ${i}s）"
            break
        fi
        if [[ $i -eq 20 ]]; then
            journalctl -u agent-p2p -n 30 --no-pager || true
            fail "step_06" "service_not_active_after_20s"
        fi
    done
}

# ── step_07: 验证 ──────────────────────────────────────────────
step_07_verify() {
    checkpoint_skip "step_07" && { log_info "跳过 step_07"; return 0; }
    log_info "=== step_07: 验证部署 ==="
    local code
    code=$(curl -sk -o /dev/null -w "%{http_code}" "https://127.0.0.1:${PORT}/" 2>/dev/null || echo "000")
    if [[ "$code" != "200" ]]; then
        journalctl -u agent-p2p -n 20 --no-pager || true
        fail "step_07" "https_check_failed_got_${code}"
    fi
    log_info "服务健康验证通过（HTTPS $code）"
    checkpoint_done "step_07"
}

# ── 主流程 ──────────────────────────────────────────────────────
main() {
    log_info "===================================================="
    log_info "Agent P2P Portal 安装开始  HOST=$HOST  PORT=$PORT"
    log_info "===================================================="

    step_01_install_deps
    step_02_clone_repo
    step_03_python_venv
    step_04_ssl_cert
    step_05_init_db
    step_06_systemd
    step_07_verify

    local api_key
    api_key=$(grep "^API_KEY=" "$INSTALL_DIR/.api_key" | cut -d= -f2)
    [[ -z "$api_key" ]] && fail "final" "api_key_empty"

    log_info "===================================================="
    log_info "安装完成！Portal: $PORTAL_URL"
    log_info "===================================================="
    echo "INSTALL_OK API_KEY=$api_key PORTAL_URL=$PORTAL_URL"
}

main "$@"
