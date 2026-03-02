"""
多账号 Cookie 管理服务

功能：
  - 读取 accounts_config.json，为每个启用的账号启动独立的 main.py 进程
  - 监听 localhost:8899，接收 Chrome 插件发来的 Cookie 更新请求
  - 自动更新对应账号的 .env 文件并重启该账号的进程

启动方式：
    conda activate py311_work
    python cookie_server.py
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from loguru import logger

PORT = 8899
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "accounts_config.json")
MAIN_PATH = os.path.join(BASE_DIR, "main.py")

# 账号进程注册表：{账号名: subprocess.Popen}
_processes: dict = {}


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------

def load_accounts() -> list:
    """读取 accounts_config.json，返回已启用的账号列表"""
    if not os.path.exists(CONFIG_PATH):
        logger.error(f"账号配置文件不存在: {CONFIG_PATH}")
        return []
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    enabled = [a for a in config.get("accounts", []) if a.get("enabled", False)]
    logger.info(f"已启用账号: {[a['name'] for a in enabled]}")
    return enabled


def get_env_path(account: dict) -> str:
    """获取账号的 .env 文件绝对路径"""
    return os.path.join(BASE_DIR, account["env_dir"], ".env")


# ---------------------------------------------------------------------------
# 进程管理
# ---------------------------------------------------------------------------

def start_account(account: dict):
    """启动指定账号的 main.py 进程"""
    name = account["name"]
    env_path = get_env_path(account)

    if not os.path.exists(env_path):
        logger.warning(f"账号 [{name}] 的 .env 不存在，跳过: {env_path}")
        return

    # 为每个账号创建独立的 data 目录
    data_dir = os.path.join(BASE_DIR, account["env_dir"], "data")
    os.makedirs(data_dir, exist_ok=True)

    # 设置环境变量，让 context_manager 的数据库写到账号目录下
    env = os.environ.copy()
    env["DB_PATH"] = os.path.join(data_dir, "chat_history.db")

    proc = subprocess.Popen(
        [sys.executable, MAIN_PATH, "--env", env_path],
        cwd=BASE_DIR,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    _processes[name] = proc
    logger.success(f"账号 [{name}] 已启动，PID: {proc.pid}")


def stop_account(name: str):
    """停止指定账号的进程"""
    proc = _processes.get(name)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        logger.info(f"账号 [{name}] 进程已停止")


def restart_account(name: str):
    """重启指定账号的进程"""
    stop_account(name)
    time.sleep(1)

    accounts = load_accounts()
    account = next((a for a in accounts if a["name"] == name), None)
    if account:
        start_account(account)
        logger.success(f"账号 [{name}] 已重启")
    else:
        logger.error(f"找不到账号配置: {name}")


def start_all():
    """启动所有已启用的账号"""
    accounts = load_accounts()
    if not accounts:
        logger.warning("没有已启用的账号，请检查 accounts_config.json")
        return
    for account in accounts:
        start_account(account)


def stop_all():
    """停止所有账号进程"""
    for name in list(_processes.keys()):
        stop_account(name)


# ---------------------------------------------------------------------------
# Cookie 更新
# ---------------------------------------------------------------------------

def update_cookie(account_name: str, new_cookie: str) -> bool:
    """更新指定账号的 Cookie"""
    accounts = load_accounts()
    # 也查找未启用的账号（Cookie 可以先更新，之后再启用）
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        all_accounts = json.load(f).get("accounts", [])

    account = next((a for a in all_accounts if a["name"] == account_name), None)
    if not account:
        logger.error(f"找不到账号: {account_name}")
        return False

    env_path = get_env_path(account)
    if not os.path.exists(env_path):
        logger.error(f".env 不存在: {env_path}")
        return False

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "COOKIES_STR=" in content:
            new_content = re.sub(r"COOKIES_STR=.*", f"COOKIES_STR={new_cookie}", content)
        else:
            new_content = content + f"\nCOOKIES_STR={new_cookie}\n"

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        logger.success(f"账号 [{account_name}] Cookie 已更新")
        return True
    except Exception as e:
        logger.error(f"更新 Cookie 失败: {e}")
        return False


# ---------------------------------------------------------------------------
# HTTP 处理器
# ---------------------------------------------------------------------------

class CookieHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        """返回所有账号列表（供插件展示下拉选择）"""
        if self.path != "/accounts":
            self._respond(404, {"success": False, "message": "路径不存在"})
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            accounts = [
                {"name": a["name"], "enabled": a.get("enabled", False)}
                for a in config.get("accounts", [])
            ]
            self._respond(200, {"success": True, "accounts": accounts})
        except Exception as e:
            self._respond(500, {"success": False, "message": str(e)})

    def do_POST(self):
        if self.path != "/update-cookie":
            self._respond(404, {"success": False, "message": "路径不存在"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            account_name = data.get("account_name", "").strip()
            new_cookie = data.get("cookie", "").strip()

            if not account_name:
                self._respond(400, {"success": False, "message": "请指定账号名称"})
                return
            if not new_cookie:
                self._respond(400, {"success": False, "message": "Cookie 不能为空"})
                return

            logger.info(f"收到账号 [{account_name}] 的 Cookie 更新请求（长度: {len(new_cookie)}）")

            if not update_cookie(account_name, new_cookie):
                self._respond(500, {"success": False, "message": "更新 Cookie 失败"})
                return

            self._respond(200, {"success": True,
                                "message": f"账号 [{account_name}] Cookie 已更新，正在重启..."})

            # 延迟重启对应账号进程
            threading.Timer(0.5, restart_account, args=[account_name]).start()

        except json.JSONDecodeError:
            self._respond(400, {"success": False, "message": "请求格式错误"})
        except Exception as e:
            logger.error(f"处理请求失败: {e}")
            self._respond(500, {"success": False, "message": str(e)})

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def _respond(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        pass


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format=" {time:HH:mm:ss} | {level: <7} | {message}")

    logger.info("启动多账号闲鱼客服管理服务...")
    start_all()

    server = HTTPServer(("0.0.0.0", PORT), CookieHandler)
    logger.info(f"Cookie 接收服务已启动，监听 localhost:{PORT}")
    logger.info("Chrome 插件选择账号后点击「同步」即可自动更新 Cookie 并重启对应账号")
    logger.info("按 Ctrl+C 退出所有进程")

    def shutdown(sig, frame):
        logger.info("正在关闭所有账号进程...")
        stop_all()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    server.serve_forever()


if __name__ == "__main__":
    main()
