#!/bin/bash
# ============================================================
# Agent P2P Portal - VPS 全量清理脚本
# 用法: bash vps_uninstall.sh
# 幂等：服务/文件不存在时不报错
# ============================================================

set -euo pipefail

INSTALL_DIR="/opt/agent-p2p"

log_info() { echo "[INFO] $*"; }

log_info "=== Agent P2P Portal 卸载开始 ==="

# 1. 停止并禁用 systemd 服务
log_info "停止 systemd 服务..."
systemctl stop agent-p2p 2>/dev/null || true
systemctl disable agent-p2p 2>/dev/null || true
rm -f /etc/systemd/system/agent-p2p.service
systemctl daemon-reload 2>/dev/null || true

# 2. 删除安装目录（含 SSL 证书、数据库、venv）
if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    log_info "已删除: $INSTALL_DIR"
else
    log_info "目录不存在，跳过: $INSTALL_DIR"
fi

# 3. 清理临时文件
rm -f /tmp/_ap2p_init_db.py /tmp/vps_install.sh /tmp/vps_uninstall.sh 2>/dev/null || true

# 4. 验证
[[ -d "$INSTALL_DIR" ]] && echo "[WARN] $INSTALL_DIR 仍存在" || log_info "OK: $INSTALL_DIR 已删除"
systemctl is-active agent-p2p 2>/dev/null && echo "[WARN] 服务仍在运行" || log_info "OK: 服务已停止"

log_info "=== 卸载完成 ==="
echo "UNINSTALL_OK"
