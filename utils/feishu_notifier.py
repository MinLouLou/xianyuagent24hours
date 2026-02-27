import os
import requests
from loguru import logger


class FeishuNotifier:
    """
    飞书通知模块，支持两种模式，优先级：应用机器人 > 群 Webhook

    模式一：应用机器人私信（推荐，可直接发给你个人）
        需要配置：FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID
        获取方式见 .env.example 注释

    模式二：自定义机器人群消息（只能发群）
        需要配置：FEISHU_WEBHOOK_URL
        获取方式：飞书群 → 设置 → 机器人 → 添加自定义机器人 → 复制 Webhook

    两者都不配置则静默跳过，不影响主流程。
    """

    def __init__(self):
        self.account_name = os.getenv("ACCOUNT_NAME", "默认账号")

        # 模式一：应用机器人
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.user_id = os.getenv("FEISHU_USER_ID", "")  # 你自己的飞书 user_id 或 open_id
        self._app_token = None
        self._app_token_expire = 0

        # 模式二：Webhook
        self.webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "")

        # 判断启用哪种模式
        self.mode = None
        if self.app_id and self.app_secret and self.user_id:
            self.mode = "app"
            logger.info(f"飞书通知已启用（应用机器人私信模式），账号标识：{self.account_name}")
        elif self.webhook_url:
            self.mode = "webhook"
            logger.info(f"飞书通知已启用（群 Webhook 模式），账号标识：{self.account_name}")
        else:
            logger.info("未配置飞书通知参数，飞书通知未启用")

    # ------------------------------------------------------------------ #
    #  公开方法
    # ------------------------------------------------------------------ #

    def notify_new_message(
        self,
        customer_name: str,
        customer_id: str,
        message: str,
        item_title: str = "",
        item_id: str = "",
        chat_id: str = "",
    ):
        """买家发来新消息时发送飞书通知"""
        if not self.mode:
            return

        item_link = f"https://www.goofish.com/item?id={item_id}" if item_id else ""
        customer_link = f"https://www.goofish.com/personal?userId={customer_id}" if customer_id else ""
        item_info = f"[{item_title}]({item_link})" if item_link else (item_title or "未知商品")
        buyer_info = f"[{customer_name}]({customer_link})" if customer_link else customer_name

        card = self._build_card(
            title="🛍️ 闲鱼新咨询消息",
            template="blue",
            elements=[
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**📱 闲鱼账号**\n{self.account_name}"}
                        },
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**👤 买家**\n{buyer_info}"}
                        }
                    ]
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**🏷️ 咨询商品**\n{item_info}"}
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**💬 消息内容**\n{message}"}
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"会话ID: {chat_id}" if chat_id else "AI 客服已自动接待"}
                    ]
                }
            ]
        )
        self._send(card)

    def notify_manual_mode_change(self, chat_id: str, mode: str, item_id: str = ""):
        """人工接管 / 恢复 AI 模式切换通知"""
        if not self.mode:
            return

        if mode == "manual":
            title, template = "🔴 已切换为人工接管", "red"
            content = f"账号 **{self.account_name}** 的会话已切换为人工模式，AI 暂停自动回复。"
        else:
            title, template = "🟢 已恢复 AI 自动回复", "green"
            content = f"账号 **{self.account_name}** 的会话已恢复 AI 自动回复模式。"

        card = self._build_card(
            title=title,
            template=template,
            elements=[
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"会话ID: {chat_id}"}]
                }
            ]
        )
        self._send(card)

    # ------------------------------------------------------------------ #
    #  内部方法
    # ------------------------------------------------------------------ #

    def _build_card(self, title: str, template: str, elements: list) -> dict:
        """构建消息卡片结构"""
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": template
                },
                "elements": elements
            }
        }

    def _send(self, card: dict):
        """根据当前模式选择发送方式"""
        if self.mode == "app":
            self._send_via_app(card)
        elif self.mode == "webhook":
            self._send_via_webhook(card)

    # ---------- 模式一：应用机器人 ----------

    def _get_app_token(self) -> str:
        """获取/刷新 tenant_access_token，有效期 2 小时，提前 5 分钟刷新"""
        import time
        if self._app_token and time.time() < self._app_token_expire - 300:
            return self._app_token

        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=5
            )
            data = resp.json()
            if data.get("code") == 0:
                import time as t
                self._app_token = data["tenant_access_token"]
                self._app_token_expire = t.time() + data.get("expire", 7200)
                logger.debug("飞书 tenant_access_token 获取成功")
                return self._app_token
            else:
                logger.warning(f"飞书 token 获取失败: {data}")
                return ""
        except Exception as e:
            logger.warning(f"飞书 token 请求异常: {e}")
            return ""

    def _send_via_app(self, card: dict):
        """通过应用机器人发私信给指定用户"""
        token = self._get_app_token()
        if not token:
            return

        # 判断 user_id 类型：open_id 以 "ou_" 开头，user_id 直接用
        id_type = "open_id" if self.user_id.startswith("ou_") else "user_id"

        payload = {
            "receive_id": self.user_id,
            "msg_type": "interactive",
            "content": card["card"] if "card" in card else card,
        }
        # 飞书发消息 API 的 content 字段需要是 JSON 字符串
        import json
        payload["content"] = json.dumps(card.get("card", card), ensure_ascii=False)

        try:
            resp = requests.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={id_type}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=5
            )
            result = resp.json()
            if result.get("code") != 0:
                logger.warning(f"飞书私信发送失败: {result}")
            else:
                logger.debug("飞书私信发送成功")
        except Exception as e:
            logger.warning(f"飞书私信请求异常（不影响主流程）: {e}")

    # ---------- 模式二：群 Webhook ----------

    def _send_via_webhook(self, card: dict):
        """通过自定义机器人 Webhook 发送群消息"""
        try:
            resp = requests.post(self.webhook_url, json=card, timeout=5)
            result = resp.json()
            if result.get("code") != 0:
                logger.warning(f"飞书 Webhook 发送失败: {result}")
            else:
                logger.debug("飞书 Webhook 发送成功")
        except Exception as e:
            logger.warning(f"飞书 Webhook 请求异常（不影响主流程）: {e}")
