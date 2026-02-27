# 🐟 XianyuAutoAgent —— 闲鱼智能客服机器人（迭代增强版）

> 基于 [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent) 进行二次开发，在原项目多专家协同框架基础上，新增**飞书实时通知**和**多账号标识**支持。

---

## ✨ 新增特性

| 功能 | 说明 |
|---|---|
| 📲 飞书私信通知 | 买家发消息时，实时推送到你的飞书（支持应用机器人私信，无需建群） |
| 💬 飞书群通知 | 也支持群 Webhook 模式，配置更简单 |
| 🏷️ 多账号标识 | 每个实例配置 `ACCOUNT_NAME`，飞书通知中清晰区分是哪个闲鱼账号收到消息 |
| 🔴🟢 模式切换通知 | 人工接管 / 恢复 AI 时同步推送飞书提醒 |

---

## 🚀 原有核心特性

- **7×24 小时值守**：WebSocket 长连接 + 断线自动重连
- **多专家路由**：议价专家 / 技术专家 / 默认客服，自动识别意图分发
- **阶梯议价**：梯度让步策略，不一次暴露底价
- **人工接管**：输入特定关键词（默认句号）随时切换人工/AI
- **上下文记忆**：SQLite 持久化对话历史，买家重复咨询不失忆
- **模拟真人延迟**：可选开启，避免秒回显得太机器人

---

## 📦 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/你的用户名/XianyuAutoAgent.git
cd XianyuAutoAgent
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
# 网络不好可用清华镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 配置环境变量

复制配置模板并填写：

```bash
cp .env.example .env
```

必填项只有两个：

```ini
API_KEY=你的通义千问 API Key   # https://bailian.console.aliyun.com
COOKIES_STR=你的闲鱼 Cookie    # F12 → Network → 任意请求 → 复制 Cookie
```

### 4. 启动

```bash
python main.py
```

---

## 📲 飞书通知配置

### 方式一：应用机器人私信（推荐，直接发给你本人）

```ini
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxx
FEISHU_USER_ID=ou_xxxxxxxx     # 你自己的飞书 User ID
```

**获取步骤：**
1. 打开 [open.feishu.cn/app](https://open.feishu.cn/app) → 创建企业自建应用
2. 「应用凭证」页面复制 App ID 和 App Secret
3. 「权限管理」→ 开通 `im:message:send_as_bot`
4. 发布应用（测试版即可）
5. 飞书 PC 端 → 头像 → 个人设置 → 账号安全 → 复制 User ID

### 方式二：自定义机器人（发到群，配置最简单）

```ini
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx
```

飞书群 → 设置 → 机器人 → 添加自定义机器人 → 复制 Webhook 地址

> 两者都配置时，方式一优先生效。

---

## 👥 多账号部署

每个指纹浏览器/账号对应一个独立文件夹，各自配置不同的 `.env`：

```
XianyuAutoAgent-主号/     ← ACCOUNT_NAME=主号, COOKIES_STR=主号cookie
XianyuAutoAgent-小号A/    ← ACCOUNT_NAME=小号A, COOKIES_STR=小号A cookie
XianyuAutoAgent-小号B/    ← ACCOUNT_NAME=小号B, COOKIES_STR=小号B cookie
```

所有账号的消息统一推送到同一个飞书，通过账号标识区分来源。

---

## ⚙️ 完整配置说明

| 配置项 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `API_KEY` | ✅ | — | LLM API Key |
| `COOKIES_STR` | ✅ | — | 闲鱼网页版 Cookie |
| `ACCOUNT_NAME` | — | `默认账号` | 飞书通知中的账号标识 |
| `FEISHU_APP_ID` | — | — | 飞书应用 ID（私信模式） |
| `FEISHU_APP_SECRET` | — | — | 飞书应用密钥（私信模式） |
| `FEISHU_USER_ID` | — | — | 接收通知的飞书用户 ID |
| `FEISHU_WEBHOOK_URL` | — | — | 飞书群 Webhook（群消息模式） |
| `MODEL_BASE_URL` | — | 通义千问 | 模型接口地址 |
| `MODEL_NAME` | — | `qwen-max` | 模型名称 |
| `TOGGLE_KEYWORDS` | — | `。` | 人工接管切换关键词 |
| `SIMULATE_HUMAN_TYPING` | — | `False` | 是否模拟打字延迟 |
| `MANUAL_MODE_TIMEOUT` | — | `3600` | 人工接管自动超时（秒） |

---

## 🛠️ 自定义提示词

`prompts/` 目录下放置 4 个提示词文件（程序优先读取无 `_example` 后缀的文件）：

| 文件 | 用途 |
|---|---|
| `classify_prompt.txt` | 意图分类（不对买家展示） |
| `price_prompt.txt` | 议价专家回复策略 |
| `tech_prompt.txt` | 技术咨询回复策略 |
| `default_prompt.txt` | 通用客服回复策略 |

复制 example 文件后按自己的商品场景修改即可：

```bash
cp prompts/price_prompt_example.txt prompts/price_prompt.txt
```

---

## ❓ 常见问题

**Q：Cookie 多久过期？**
约一周，过期后日志会报错提示，重新从浏览器复制 Cookie 填入 `.env` 即可。

**Q：报错"哎呦喂，被挤爆了"？**
触发风控。进入 goofish.com → 点击消息 → 过滑块 → 重新复制 Cookie。

**Q：能用本地大模型吗？**
可以。用 Ollama 部署后，修改 `.env` 中的 `MODEL_BASE_URL` 和 `MODEL_NAME` 即可。

**Q：能同时跑多个账号吗？**
可以。复制多个项目文件夹，每个配置不同的 Cookie 和 ACCOUNT_NAME，分别启动。

---

## 📝 致谢

- 原项目：[shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent)
- 飞书开放平台：[open.feishu.cn](https://open.feishu.cn)

---

## ⚠️ 免责声明

本项目仅供学习与技术研究使用，请遵守闲鱼平台用户协议，勿用于违规用途。
