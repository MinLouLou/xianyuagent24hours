"""
闲鱼平台 API 封装

负责：登录态维护、accessToken 获取、商品详情查询。
Cookie 失效时提供交互式更新入口，支持自动写回 .env 文件。
"""
import os
import re
import sys
import time
from http.cookies import SimpleCookie

import requests
from loguru import logger

from utils.xianyu_utils import generate_sign


class XianyuApis:
    """闲鱼 H5 API 客户端"""

    _TOKEN_API = "https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/"
    _ITEM_API  = "https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/"
    _LOGIN_API = "https://passport.goofish.com/newlogin/hasLogin.do"

    _DEFAULT_HEADERS = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "origin": "https://www.goofish.com",
        "referer": "https://www.goofish.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self._DEFAULT_HEADERS)

    # ------------------------------------------------------------------ #
    #  Cookie 管理
    # ------------------------------------------------------------------ #

    def clear_duplicate_cookies(self):
        """去除重复 Cookie，保留最新的同名项，并同步写回 .env"""
        seen: set = set()
        new_jar = requests.cookies.RequestsCookieJar()
        for cookie in reversed(list(self.session.cookies)):
            if cookie.name not in seen:
                new_jar.set_cookie(cookie)
                seen.add(cookie.name)
        self.session.cookies = new_jar
        self._sync_cookies_to_env()

    def _sync_cookies_to_env(self):
        """将当前 Cookie 字符串同步写回 .env 文件"""
        env_path = os.path.join(os.getcwd(), ".env")
        if not os.path.exists(env_path):
            return
        try:
            cookie_str = "; ".join(f"{c.name}={c.value}" for c in self.session.cookies)
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            new_content = re.sub(r"COOKIES_STR=.*", f"COOKIES_STR={cookie_str}", content)
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            logger.debug(".env 中的 COOKIES_STR 已同步更新")
        except Exception as e:
            logger.warning(f"同步 Cookie 到 .env 失败: {e}")

    def _update_cookies_from_str(self, cookie_str: str):
        """解析并替换当前 Session 的 Cookie"""
        jar = SimpleCookie()
        jar.load(cookie_str)
        self.session.cookies.clear()
        for key, morsel in jar.items():
            self.session.cookies.set(key, morsel.value, domain=".goofish.com")

    # ------------------------------------------------------------------ #
    #  登录态检查
    # ------------------------------------------------------------------ #

    def check_login(self, retry: int = 0) -> bool:
        """调用 hasLogin 接口确认登录态"""
        if retry >= 2:
            logger.error("登录检查失败，重试次数超限")
            return False
        try:
            data = {
                "hid": self.session.cookies.get("unb", ""),
                "appName": "xianyu",
                "appEntrance": "web",
                "_csrf_token": self.session.cookies.get("XSRF-TOKEN", ""),
                "hsiz": self.session.cookies.get("cookie2", ""),
                "bizParams": "taobaoBizLoginFrom=web",
                "mainPage": "false",
                "isMobile": "false",
                "lang": "zh_CN",
                "returnUrl": "",
                "fromSite": "77",
                "isIframe": "true",
                "documentReferer": "https://www.goofish.com/",
                "defaultView": "hasLogin",
                "deviceId": self.session.cookies.get("cna", ""),
            }
            resp = self.session.post(
                self._LOGIN_API,
                params={"appName": "xianyu", "fromSite": "77"},
                data=data,
            )
            if resp.json().get("content", {}).get("success"):
                self.clear_duplicate_cookies()
                return True
            logger.warning(f"登录态检查失败: {resp.json()}")
            time.sleep(0.5)
            return self.check_login(retry + 1)
        except Exception as e:
            logger.error(f"登录检查请求异常: {e}")
            time.sleep(0.5)
            return self.check_login(retry + 1)

    # ------------------------------------------------------------------ #
    #  Token 获取
    # ------------------------------------------------------------------ #

    def get_token(self, device_id: str, retry: int = 0) -> dict:
        """获取 WebSocket 连接所需的 accessToken"""
        if retry >= 2:
            logger.warning("Token 获取失败，尝试重新登录...")
            if self.check_login():
                return self.get_token(device_id, 0)
            logger.error("重新登录失败，Cookie 已失效，程序退出")
            sys.exit(1)

        t = str(int(time.time()) * 1000)
        data_val = f'{{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"{device_id}"}}'
        token = self.session.cookies.get("_m_h5_tk", "").split("_")[0]

        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t,
            "sign": generate_sign(t, token, data_val),
            "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
            "dataType": "json", "timeout": "20000",
            "api": "mtop.taobao.idlemessage.pc.login.token",
            "sessionOption": "AutoLoginOnly", "spm_cnt": "a21ybx.im.0.0",
        }

        try:
            resp = self.session.post(self._TOKEN_API, params=params, data={"data": data_val})
            result = resp.json()
            ret = result.get("ret", [])

            if not any("SUCCESS" in r for r in ret):
                err = str(ret)
                if "RGV587_ERROR" in err or "被挤爆" in err:
                    return self._handle_risk_control(device_id)
                logger.warning(f"Token API 调用失败: {ret}")
                if "Set-Cookie" in resp.headers:
                    self.clear_duplicate_cookies()
                time.sleep(0.5)
                return self.get_token(device_id, retry + 1)

            logger.info("Token 获取成功")
            return result

        except Exception as e:
            logger.error(f"Token 请求异常: {e}")
            time.sleep(0.5)
            return self.get_token(device_id, retry + 1)

    def _handle_risk_control(self, device_id: str) -> dict:
        """触发风控时，等待 Cookie 文件更新后自动重试（支持插件远程更新）"""
        logger.error("触发风控（被挤爆），请通过插件同步新 Cookie，程序将自动恢复")
        logger.warning("每 15 秒检查一次 Cookie 是否已更新，请用插件同步后等待...")

        import os
        from dotenv import dotenv_values

        env_file = os.getenv("_ACCOUNT_ENV_PATH", os.path.join(os.getcwd(), ".env"))
        current_tk = self.session.cookies.get("_m_h5_tk", "")

        while True:
            time.sleep(15)
            try:
                values = dotenv_values(env_file)
                new_cookie_str = values.get("COOKIES_STR", "")
                if new_cookie_str:
                    self._update_cookies_from_str(new_cookie_str)
                    new_tk = self.session.cookies.get("_m_h5_tk", "")
                    if new_tk and new_tk != current_tk:
                        logger.success("检测到新 Cookie，正在重新连接...")
                        return self.get_token(device_id, 0)
                    else:
                        logger.info("Cookie 未变化，继续等待插件同步...")
            except Exception as e:
                logger.debug(f"检查 Cookie 时出错: {e}")

    # ------------------------------------------------------------------ #
    #  商品信息
    # ------------------------------------------------------------------ #

    def get_item_info(self, item_id: str, retry: int = 0) -> dict:
        """获取商品详情，失败自动重试"""
        if retry >= 3:
            return {"error": "获取商品信息失败，重试次数超限"}

        t = str(int(time.time()) * 1000)
        data_val = f'{{"itemId":"{item_id}"}}'
        token = self.session.cookies.get("_m_h5_tk", "").split("_")[0]

        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t,
            "sign": generate_sign(t, token, data_val),
            "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
            "dataType": "json", "timeout": "20000",
            "api": "mtop.taobao.idle.pc.detail",
            "sessionOption": "AutoLoginOnly", "spm_cnt": "a21ybx.im.0.0",
        }

        try:
            resp = self.session.post(self._ITEM_API, params=params, data={"data": data_val})
            result = resp.json()
            ret = result.get("ret", [])

            if not any("SUCCESS" in r for r in ret):
                logger.warning(f"商品 API 失败: {ret}")
                if "Set-Cookie" in resp.headers:
                    self.clear_duplicate_cookies()
                time.sleep(0.5)
                return self.get_item_info(item_id, retry + 1)

            logger.debug(f"商品信息获取成功: {item_id}")
            return result

        except Exception as e:
            logger.error(f"商品 API 请求异常: {e}")
            time.sleep(0.5)
            return self.get_item_info(item_id, retry + 1)
