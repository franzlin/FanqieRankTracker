# 🏆 番茄风向标 · Fanqie Rank Tracker

[![English](https://img.shields.io/badge/lang-English-blue)](README_EN.md)

> 👗👨 专注于**番茄小说男频 + 女频新书榜**，每日自动追踪排行数据并结合 AI 生成趋势分析，部署在自建 VPS 看板。

---

## ✨ 功能概览

| 功能 | 说明 |
|------|------|
| 🕷️ 自动爬取 | 每日定时抓取番茄男频 + 女频各个分类的新书榜 Top 30 |
| 📊 趋势对比 | 自动对比相邻两天数据：新上榜 / 掉榜 / 排名变化 / 阅读量增长 |
| 🤖 AI 风向分析 | 接入 OpenAI 兼容 API，按分类生成市场趋势速评 |
| 🧭 类型风向标 | 独立趋势页聚合多日数据，用 AI 总结综合赛道、具体热门分类和高频题材；未配置 API 时自动规则兜底 |
| 📚 短篇推荐 | 访问时按 100+ 个题材标签实时读取短故事，展示封面、摘要、阅读时长和互动数据，不落盘推荐内容 |
| 🔄 频道切换 | 侧边栏和趋势页均支持女频 / 男频 / 全部频道切换 |
| 🖥️ 精美看板 | 暗色编辑风格仪表盘，带打字机动画和瀑布流书籍卡片 |
| 📱 移动适配 | 完整的移动端适配，侧边栏抽屉式菜单 |
| 🔌 数据接口 | 生成静态 `lastest` JSON 接口，可按类型读取最新数据 |
| ⚡ VPS 全自动化 | Caddy 静态托管 + cron 定时任务，独立服务器零依赖托管平台 |

---

## 🚀 VPS 部署指南

### 前置条件

- **Linux VPS**（已测试 Ubuntu 24.04 ARM 4核/23G）
- **Python 3.10+** 与 **Node.js 18+**（可选的 Playwright 已在部分环境预装）
- **Caddy**（自动 HTTPS）或其他静态服务器
- （可选）一个 OpenAI 兼容 API 的密钥，用于 AI 分析

### 第一步：上传项目到服务器

```bash
# 在项目目录执行（替换为你的服务器信息）
ssh ubuntu@<服务器IP>
sudo mkdir -p /opt/fanqie-rank && sudo chown $USER:$USER /opt/fanqie-rank

# 本机打包上传
tar czf - --exclude='.git' . | ssh ubuntu@<服务器IP> "cat > /tmp/fanqie.tar.gz && sudo tar xzf /tmp/fanqie.tar.gz -C /opt/fanqie-rank"
```

### 第二步：安装依赖

```bash
cd /opt/fanqie-rank
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install playwright openai requests

# 复用服务器已有浏览器，或手动安装
# 如果 /opt/ms-playwright 已有 chromium，直接指向即可：
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
# 否则：./venv/bin/playwright install chromium
```

### 第三步：创建每日自动任务脚本

将 `run_daily.sh` 写入项目目录：

```bash
cat > /opt/fanqie-rank/run_daily.sh << 'SCRIPT'
#!/bin/bash
set -e
cd /opt/fanqie-rank
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
export API_BASE_URL='https://你的API地址/v1'
export API_KEY='你的API密钥'
export API_MODEL='你的模型名'
mkdir -p logs
echo "===== [$(date '+%F %T')] start =====" >> logs/daily.log
./venv/bin/python scrape_fanqie_ranks.py >> logs/daily.log 2>&1 || echo "SCRAPE FAILED" >> logs/daily.log
./venv/bin/python scripts/build_latest.py >> logs/daily.log 2>&1 || echo "BUILD FAILED" >> logs/daily.log
echo "===== [$(date '+%F %T')] done =====" >> logs/daily.log
SCRIPT
chmod +x /opt/fanqie-rank/run_daily.sh
```

### 第四步：配置 cron 定时任务

```bash
crontab -e
# 添加一行：每天北京时间 08:15（UTC 00:15）自动爬取 + 构建
15 0 * * * /opt/fanqie-rank/run_daily.sh
```

### 第五步：配置 Caddy 静态站点

```bash
# 追加到 /etc/caddy/Caddyfile 并 reload
```

```caddy
fanqie.lylwz.com {
    tls /etc/caddy/lylwz-origin.crt /etc/caddy/lylwz-origin.key
    encode gzip
    header {
        -Server
        X-Content-Type-Options nosniff
        X-Frame-Options SAMEORIGIN
        Referrer-Policy strict-origin-when-cross-origin
    }
    root * /opt/fanqie-rank
    try_files {path} /index.html
    file_server
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

### 第六步：配置 DNS

在 Cloudflare 面板为你的域名添加 A 记录指向 VPS IP，开启橙色云朵代理。解析生效后即可访问看板。

### 第七步：验证

```bash
curl -I https://你的域名/
curl -I https://你的域名/data/latest_ranks.json
```

> **💡 提示：** 任何 OpenAI 兼容接口均可使用（如 Moonshot / DeepSeek / 自建服务等）。如果不配置 API 环境变量，系统将自动使用基于规则的摘要替代 AI 分析，**不影响核心功能**。

---

## 🔌 最新数据接口

看板目录下会生成静态 JSON 接口：

| 类型 | 路径 | 说明 |
|---|---|---|
| 类型索引 | `api/lastest.json` | 返回所有可用类型及对应 URL |
| 全量数据 | `api/lastest/all.json` | 返回全部分类、趋势和书籍 |
| 单类型数据 | `api/lastest/<类型>.json` | 返回指定类型的数据，例如 `api/lastest/古风世情.json` |

示例：

```bash
curl https://你的域名/api/lastest/all.json
curl https://你的域名/api/lastest/古风世情.json
```

---

## 🔧 本地开发

```bash
# 1. 克隆仓库
git clone https://github.com/<你的用户名>/FanqieRankTracker.git
cd FanqieRankTracker

# 2. 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright  # 复用VPS浏览器，或: playwright install chromium

# 4. 运行爬虫（每个分类抓取 Top 30）
python scrape_fanqie_ranks.py

# 5. 构建看板数据（可选，带 AI 分析需设置环境变量）
pip install openai
export API_BASE_URL="https://your-api-endpoint/v1"
export API_KEY="your-api-key"
export API_MODEL="your-model-name"
python scripts/build_latest.py

# 6. 本地预览前端
python -m http.server 8000
# 打开 http://localhost:8000
```

---

## 📁 项目结构

```
FanqieRankTracker/
├── css/
│   └── style.css               # 暗色编辑风格主题样式
├── js/
│   └── app.js                  # 前端渲染逻辑（瀑布流 + 打字机动画）
├── scripts/
│   └── build_latest.py         # 趋势对比 + AI 分析构建脚本
├── data/
│   ├── fanqie_new_ranks_YYYYMMDD.json         # 每日原始快照（男频+女频）
│   ├── fanqie_female_new_ranks_YYYYMMDD.json  # 历史女频快照（兼容保留）
│   ├── latest_ranks.json       # 最新聚合数据（看板数据源）
│   ├── market_summary.json     # 全站热点 AI/规则总结
│   └── trends/
│       └── YYYY-MM-DD.json     # 趋势归档
├── api/
│   └── lastest/                # 最新数据静态接口（all + 按类型拆分）
├── index.html                  # 仪表盘入口页
├── trend.html                  # 类型风向标趋势分析页
├── shorts.html                 # 短篇推荐页
├── scrape_fanqie_ranks.py      # 番茄小说爬虫（Playwright）
├── run_daily.sh                # VPS 每日任务脚本
├── requirements.txt            # Python 依赖
└── README.md                   # 本文件
```

---

## ⚙️ 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                    VPS cron (每日 08:15 北京时间)            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  Playwright   │───▶│  build_latest │───▶│  写入 data/  │  │
│  │  爬取榜单数据  │    │  趋势对比      │    │  目录        │  │
│  │              │    │  + AI 分析     │    │              │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                             │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                      Caddy 静态托管
                      用户访问在线看板 🌐
```

---

## 📝 常见问题

<details>
<summary><b>Q: 爬虫运行失败怎么办？</b></summary>

检查 `logs/daily.log` 中的错误信息。常见原因：
- 番茄小说页面结构变更 → 需要更新爬虫选择器
- Playwright 浏览器未安装 → 检查 `PLAYWRIGHT_BROWSERS_PATH` 指向的浏览器目录
- 网络波动导致 SPA 书单未渲染 → 爬虫已内置 3 次重试，仍失败可手动重跑

</details>

<details>
<summary><b>Q: 不配置 AI API 也能用吗？</b></summary>

可以！系统会自动 fallback 到基于规则的摘要（如"新增3本上榜；《XX》排名上升+5位"）。只是没有 AI 自然语言分析而已。

</details>

<details>
<summary><b>Q: 可以换成男频或其他榜单吗？</b></summary>

本项目已支持男频 + 女频双频道！爬虫会自动抓取两个频道的所有分类。侧边栏的频道切换开关可以在女频 / 男频 / 全部之间切换。

如果要只抓单个频道，修改 `scrape_fanqie_ranks.py` 中的 `CHANNELS` 列表，只保留需要的频道即可。

</details>

---

## 📜 License

MIT

---

<p align="center">
  <sub>Made with ☕ and 🤖 — 数据每日自动更新，无需手动维护</sub>
</p>