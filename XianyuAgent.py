"""
多专家协同的闲鱼智能客服回复引擎

架构：MessageRouter（意图路由） → 对应 Expert（专家 Agent）→ 生成回复
新增：飞书通知集成、多账号标识支持
"""
import re
import os
from typing import List, Dict, Optional
from openai import OpenAI
from loguru import logger


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _load_prompt(name: str, prompt_dir: str = "prompts") -> str:
    """
    加载提示词文件。优先读取 {name}.txt，不存在则回退到 {name}_example.txt。
    """
    primary = os.path.join(prompt_dir, f"{name}.txt")
    fallback = os.path.join(prompt_dir, f"{name}_example.txt")
    path = primary if os.path.exists(primary) else fallback
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    logger.debug(f"已加载提示词 [{name}]，路径: {path}，长度: {len(content)} 字符")
    return content


def _build_safe_filter():
    """构建安全过滤器，拦截引导站外交易的敏感词"""
    _blocked = ["微信", "QQ", "支付宝转账", "银行卡", "私下交易", "线下见面"]

    def _filter(text: str) -> str:
        return "[请通过平台沟通]" if any(kw in text for kw in _blocked) else text

    return _filter


# ---------------------------------------------------------------------------
# Expert 基类
# ---------------------------------------------------------------------------

class Expert:
    """所有专家 Agent 的基类，封装 LLM 调用逻辑"""

    def __init__(self, client: OpenAI, system_prompt: str, safe_filter):
        self.client = client
        self.system_prompt = system_prompt
        self.safe_filter = safe_filter

    # ---- 子类可覆盖的方法 ----

    def reply(
        self,
        user_msg: str,
        item_desc: str,
        history: str,
        bargain_count: int = 0,
    ) -> str:
        messages = self._compose_messages(user_msg, item_desc, history)
        raw = self._call_llm(messages)
        return self.safe_filter(raw)

    def _compose_messages(self, user_msg: str, item_desc: str, history: str) -> List[Dict]:
        system_content = (
            f"【商品信息】{item_desc}\n"
            f"【对话历史】{history}\n"
            f"{self.system_prompt}"
        )
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_msg},
        ]

    def _call_llm(
        self,
        messages: List[Dict],
        temperature: float = 0.4,
        max_tokens: int = 500,
    ) -> str:
        resp = self.client.chat.completions.create(
            model=os.getenv("MODEL_NAME", "qwen-max"),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.8,
        )
        return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# 具体专家实现
# ---------------------------------------------------------------------------

class PriceExpert(Expert):
    """议价专家：动态温度策略，随议价轮次逐步放宽"""

    def reply(self, user_msg: str, item_desc: str, history: str, bargain_count: int = 0) -> str:
        temperature = min(0.3 + bargain_count * 0.15, 0.9)
        messages = self._compose_messages(user_msg, item_desc, history)
        messages[0]["content"] += f"\n▲当前议价轮次：{bargain_count}"
        raw = self._call_llm(messages, temperature=temperature)
        return self.safe_filter(raw)


class TechExpert(Expert):
    """技术专家：回答产品参数/对比问题，通义千问模型下自动开启联网搜索"""

    def _call_llm(self, messages: List[Dict], temperature: float = 0.4, max_tokens: int = 500) -> str:
        model_name = os.getenv("MODEL_NAME", "qwen-max")
        # enable_search 是通义千问专属参数，OpenAI 等其他模型不支持
        is_qwen = "qwen" in model_name.lower()
        kwargs = dict(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.8,
        )
        if is_qwen:
            kwargs["extra_body"] = {"enable_search": True}

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content


class ClassifyExpert(Expert):
    """意图分类专家：仅用于路由，不直接面向买家"""
    pass


class DefaultExpert(Expert):
    """通用客服专家：处理物流、售后、基础咨询等"""

    def _call_llm(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 500) -> str:
        return super()._call_llm(messages, temperature=temperature, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# 意图路由器
# ---------------------------------------------------------------------------

class MessageRouter:
    """
    三级路由策略：
      1. 技术关键词快速匹配
      2. 价格关键词快速匹配
      3. LLM 分类兜底
    """

    _TECH_KEYWORDS = {"参数", "规格", "型号", "连接", "对比", "适配", "安装", "内存", "性能"}
    _TECH_PATTERNS = [r"和.+比", r"支持.+吗"]

    _PRICE_KEYWORDS = {"便宜", "价", "砍价", "少点", "优惠", "折扣", "预算", "能不能降"}
    _PRICE_PATTERNS = [r"\d+元", r"能少\d+", r"最低\d+"]

    def __init__(self, classify_expert: ClassifyExpert):
        self._classify = classify_expert

    def route(self, user_msg: str, item_desc: str, history: str) -> str:
        """返回意图标签：price / tech / default / no_reply"""
        clean = re.sub(r"[^\w\u4e00-\u9fa5]", "", user_msg)

        if any(kw in clean for kw in self._TECH_KEYWORDS):
            return "tech"
        if any(re.search(p, clean) for p in self._TECH_PATTERNS):
            return "tech"
        if any(kw in clean for kw in self._PRICE_KEYWORDS):
            return "price"
        if any(re.search(p, clean) for p in self._PRICE_PATTERNS):
            return "price"

        # LLM 兜底分类
        return self._classify.reply(user_msg=user_msg, item_desc=item_desc, history=history)


# ---------------------------------------------------------------------------
# 主入口：XianyuReplyBot
# ---------------------------------------------------------------------------

class XianyuReplyBot:
    """
    闲鱼智能回复机器人

    对外只暴露一个方法：generate_reply()
    内部维护路由器 + 四种专家 Agent
    """

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("MODEL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        self.safe_filter = _build_safe_filter()
        self._init_experts()
        self.router = MessageRouter(self.experts["classify"])
        self.last_intent: Optional[str] = None

    def _init_experts(self):
        prompts = {
            "classify": _load_prompt("classify_prompt"),
            "price":    _load_prompt("price_prompt"),
            "tech":     _load_prompt("tech_prompt"),
            "default":  _load_prompt("default_prompt"),
        }
        f = self.safe_filter
        c = self.client
        self.experts: Dict[str, Expert] = {
            "classify": ClassifyExpert(c, prompts["classify"], f),
            "price":    PriceExpert(c,    prompts["price"],    f),
            "tech":     TechExpert(c,     prompts["tech"],     f),
            "default":  DefaultExpert(c,  prompts["default"],  f),
        }

    def reload_prompts(self):
        """热重载提示词（无需重启服务）"""
        logger.info("重新加载提示词...")
        self._init_experts()
        self.router = MessageRouter(self.experts["classify"])
        logger.info("提示词重载完成")

    def generate_reply(self, user_msg: str, item_desc: str, context: List[Dict]) -> str:
        """
        生成回复主流程

        Returns:
            回复文本；返回 "-" 表示无需回复
        """
        history = self._format_history(context)
        intent = self.router.route(user_msg, item_desc, history)
        self.last_intent = intent

        if intent == "no_reply":
            logger.info("意图：no_reply，跳过回复")
            return "-"

        expert = self.experts.get(intent) or self.experts["default"]
        logger.info(f"意图：{intent}，分配专家：{type(expert).__name__}")

        bargain_count = self._extract_bargain_count(context)
        return expert.reply(
            user_msg=user_msg,
            item_desc=item_desc,
            history=history,
            bargain_count=bargain_count,
        )

    # ---- 私有工具方法 ----

    @staticmethod
    def _format_history(context: List[Dict]) -> str:
        return "\n".join(
            f"{m['role']}: {m['content']}"
            for m in context
            if m["role"] in ("user", "assistant")
        )

    @staticmethod
    def _extract_bargain_count(context: List[Dict]) -> int:
        for msg in context:
            if msg["role"] == "system" and "议价次数" in msg["content"]:
                m = re.search(r"议价次数[:：]\s*(\d+)", msg["content"])
                if m:
                    return int(m.group(1))
        return 0
