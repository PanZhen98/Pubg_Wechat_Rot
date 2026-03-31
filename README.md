# PUBG WeChat Bot

PUBG 游戏群专属微信机器人，支持战绩查询、赛季/排位/生涯统计、每日称号日报，运行在 Linux 服务器上，通过 [agent-wechat](https://github.com/thisnick/agent-wechat) 接入微信。

---

## 功能

- **战绩查询**：查询任意玩家今日或昨日的比赛数据（出战场数、击杀、伤害、KD、吃鸡等）
- **赛季/排位/生涯统计**：调用 PUBG Open API 获取本赛季、排位赛、生涯数据（仅显示四排）
- **玩家登记**：登记 PUBG ID 参与每日称号评选
- **每日称号日报**：每天 08:00 CST 自动推送昨日称号排行榜（击杀王、KD 冠军、华佗在世等 9 个称号）
- **自动重登陆**：服务器监测微信登出状态，自动触发重登陆；Mac 本地通过 ADB 自动点击手机确认按钮

---

## 项目结构

```
.
├── wechat_bot.py              # 主 bot 轮询逻辑，消息路由
├── pubg_api.py                # PUBG Open API 客户端及格式化输出
├── daily_report.py            # 每日称号日报生成
├── player_registry.py         # 玩家 ID 注册表（JSON 文件持久化）
├── wechat-auto-relogin.py     # 服务器端自动重登陆监控（WebSocket）
├── start-agent-wechat.sh      # 启动 agent-wechat 容器的脚本
├── entrypoint-rw.sh           # 容器入口脚本（挂载可写层）
├── wait-for-chats.sh          # 等待 agent-wechat API 就绪
├── systemd/
│   ├── agent-wechat.service   # agent-wechat Docker 容器 systemd 服务
│   ├── wechat-bot.service     # wechat_bot.py systemd 服务
│   └── wechat-auto-relogin.service  # 自动重登陆监控 systemd 服务
├── mac/
│   └── wechat-phone-confirm.py  # Mac 本地 ADB 自动点击手机确认登陆
├── .env.example               # 环境变量示例
└── .gitignore
```

---

## 环境要求

### 服务器

- Linux（Ubuntu 20.04+）
- Docker
- Python 3.11+
- 依赖包：`pip install requests httpx websockets`

### Mac（自动手机确认，可选）

- Android 手机 + ADB（`brew install android-platform-tools`）
- Python 3.10+：`pip install adb-shell`（脚本直接调用 adb 二进制）

---

## 部署

### 1. 克隆仓库

```bash
git clone https://github.com/PanZhen98/Pubg_Wechat_Rot.git
cd Pubg_Wechat_Rot
```

### 2. 配置环境变量

复制并填写密钥：

```bash
cp .env.example .env
# 编辑 .env，填入真实的 PUBG_API_KEY 和 AI_KEY
```

或直接在 systemd 服务的 `[Service]` 段添加：

```ini
Environment=PUBG_API_KEY=your_pubg_api_key
Environment=AI_KEY=your_ai_key
```

### 3. 启动 agent-wechat 容器

```bash
cp systemd/agent-wechat.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now agent-wechat
```

首次启动后通过 VNC（端口 5900）或 WebSocket 登陆微信。

### 4. 部署 bot 服务

```bash
cp wechat_bot.py pubg_api.py daily_report.py player_registry.py /opt/
cp systemd/wechat-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wechat-bot
```

### 5. 部署自动重登陆监控

```bash
pip install httpx websockets
cp wechat-auto-relogin.py /opt/
cp systemd/wechat-auto-relogin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wechat-auto-relogin
```

### 6. Mac 端手机自动确认（可选）

```bash
# 修改 mac/wechat-phone-confirm.py 中的 SERIAL 为你的手机 ADB 序列号
# (adb devices 查看)
launchctl load ~/Library/LaunchAgents/com.wechat.phone-confirm.plist
```

---

## 使用说明（微信群内）

> 所有指令需要 **@机器人** 触发（默认名：`战地助手`）

| 指令示例 | 说明 |
|---|---|
| `@战地助手 6umm` | 查询玩家今日战报 |
| `@战地助手 6umm 昨日` | 查询玩家昨日战报 |
| `@战地助手 6umm 赛季` | 查询本赛季四排数据 |
| `@战地助手 6umm 排位` | 查询本赛季排位四排数据 |
| `@战地助手 6umm 生涯` | 查询生涯四排数据 |
| `@战地助手 登记 6umm` | 登记玩家 ID 参与每日称号评选 |
| `@战地助手 帮助` | 查看所有功能 |

每天 **08:00 CST** 自动向所有群发送昨日称号日报。

---

## 环境变量

| 变量 | 说明 |
|---|---|
| `PUBG_API_KEY` | PUBG Open API JWT，在 [developer.pubg.com](https://developer.pubg.com/) 申请 |
| `AI_KEY` | AI 对话接口密钥（当前模型：gpt-4o-mini，接口：imds.ai） |

---

## 相关项目

- [agent-wechat](https://github.com/thisnick/agent-wechat) — 微信 Linux 客户端 + REST API
- [PUBG Open API](https://developer.pubg.com/) — 官方战绩数据接口
