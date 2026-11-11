#!/usr/bin/env bash
# 智能拍照学习助手 · 一键部署（Ubuntu 22.04 / 24.04，Debian 12）
#
# 用法：
#   sudo bash deploy/deploy.sh
#
# 前提：
#   1. 仓库已 clone 到目标目录（推荐 /opt/learnmate）
#   2. 前端已在本地构建并把 dist 传上来（2G 内存不建议在服务器跑 vite build）
#   3. backend/dev.db 与 backend/kb_images 已就位
#
# 脚本可重复执行：已装的跳过，配置会被覆盖为最新版本。

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="learnmate"
BACKEND="$APP_DIR/backend"
PY="$BACKEND/.venv/bin/python"
PIP="$BACKEND/.venv/bin/pip"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

# ---------------- 0. 前置检查 ----------------
[ "$(id -u)" -eq 0 ] || die "请用 root 运行：sudo bash deploy/deploy.sh"
command -v apt-get >/dev/null || die "本脚本只支持 Debian/Ubuntu。CentOS 请改 yum 并自行调整包名。"

say "部署目录 $APP_DIR"
[ -f "$BACKEND/app/main.py" ] || die "找不到 backend/app/main.py，请确认在项目根目录执行"
[ -d "$APP_DIR/frontend/dist" ] || die "缺少 frontend/dist。请在本地 npm run build 后把整个 dist 目录传上来"
[ -f "$BACKEND/dev.db" ] || warn "缺 backend/dev.db，首次启动会自动建空库（没有题库数据）"

PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
say "系统 Python 版本 $PYVER"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || die "需要 Python 3.11+（Ubuntu 22.04 自带 3.10，请装 3.11：apt install python3.11 python3.11-venv）"

# ---------------- 1. 系统依赖 ----------------
say "安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx python3-venv python3-pip sqlite3 curl >/dev/null
ok "nginx / python3-venv / sqlite3 就绪"

# ---------------- 2. 运行用户 ----------------
if id "$APP_USER" &>/dev/null; then
  ok "用户 $APP_USER 已存在"
else
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
  ok "已创建系统用户 $APP_USER"
fi

# ---------------- 3. 虚拟环境 + 运行时依赖 ----------------
say "准备 Python 虚拟环境（只装运行时依赖，不含 OCR/PDF 重型包）"
if [ ! -x "$PY" ]; then
  python3 -m venv "$BACKEND/.venv"
  ok "已创建 venv"
else
  ok "venv 已存在"
fi
"$PIP" install -q --upgrade pip
"$PIP" install -q -r "$APP_DIR/deploy/requirements-runtime.txt"
ok "运行时依赖安装完成（跳过 onnxruntime/opencv/pymupdf，省 500MB 磁盘与 300MB 内存）"

# ---------------- 4. 配置文件 ----------------
say "检查 backend/.env"
if [ ! -f "$BACKEND/.env" ]; then
  cp "$APP_DIR/deploy/env.production.example" "$BACKEND/.env"
  warn "已生成 .env，请填入 DEEPSEEK_API_KEY 与 SMTP 授权码，然后重新执行本脚本"
fi
chown "$APP_USER:$APP_USER" "$BACKEND/.env"
chmod 600 "$BACKEND/.env"
ok ".env 权限已收紧为 600（仅 $APP_USER 可读）"

# ---------------- 5. 目录权限 ----------------
say "修正目录权限"
mkdir -p "$BACKEND/uploads"
# SQLite 写入时要在数据库**同目录**创建 journal 文件。
# 只给 dev.db 授权是不够的：目录若不属于服务用户，第一次写就会报
# "attempt to write a readonly database"。（实测踩过）
# 用「属组 + 775」：项目所有者仍能改代码，服务用户能写数据。
chown "$APP_USER:$APP_USER" "$BACKEND/dev.db" 2>/dev/null || true
chgrp "$APP_USER" "$BACKEND" 2>/dev/null || true
chmod 775 "$BACKEND" 2>/dev/null || true
chown -R "$APP_USER:$APP_USER" "$BACKEND/uploads" 2>/dev/null || true
[ -d "$BACKEND/profiles" ] && chown -R "$APP_USER:$APP_USER" "$BACKEND/profiles" 2>/dev/null || true
# 题库图片只读即可
chmod -R a+rX "$BACKEND/kb_images" 2>/dev/null || true
ok "dev.db 可写（含同目录 journal）、uploads/profiles 可写、kb_images 只读"

# ---------------- 6. systemd ----------------
say "安装 systemd 服务"
sed "s#/opt/learnmate#$APP_DIR#g" "$APP_DIR/deploy/learnmate.service" \
  > /etc/systemd/system/learnmate.service
systemctl daemon-reload
systemctl enable learnmate >/dev/null 2>&1
systemctl restart learnmate
ok "learnmate.service 已启动"

# ---------------- 7. Nginx ----------------
say "配置 Nginx"
sed "s#/opt/learnmate#$APP_DIR#g" "$APP_DIR/deploy/nginx-learnmate.conf" \
  > /etc/nginx/sites-available/learnmate
ln -sf /etc/nginx/sites-available/learnmate /etc/nginx/sites-enabled/learnmate
# 默认站点会抢占 80 端口的默认 server，去掉以免干扰
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null
systemctl reload nginx
ok "Nginx 已加载站点配置"

# ---------------- 8. 自检 ----------------
say "自检"
sleep 3
if curl -fsS --max-time 10 http://127.0.0.1:8000/api/v1/health >/dev/null; then
  ok "后端健康检查通过"
else
  warn "后端未就绪，查看日志：journalctl -u learnmate -n 50 --no-pager"
fi

if curl -fsS --max-time 10 http://127.0.0.1/ >/dev/null; then
  ok "前端页面可访问"
else
  warn "Nginx 返回异常，检查：tail -50 /var/log/nginx/error.log"
fi

IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo '服务器公网IP')"
cat <<EOF

────────────────────────────────────────────
 部署完成

   访问地址   http://$IP
   接口文档   http://$IP/api/v1/health
   校对后台   http://$IP/review

   查看日志   journalctl -u learnmate -f
   重启服务   systemctl restart learnmate
   内存占用   systemctl status learnmate | head -5

 下一步：
   1. 确认 backend/.env 里 ALLOW_DEMO_LOGIN=0（公网必须关）
   2. 阿里云安全组放行 80 端口
   3. 想上 HTTPS 且有域名，见 deploy/nginx-learnmate.conf 末尾说明
────────────────────────────────────────────
EOF
