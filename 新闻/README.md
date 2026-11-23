# 每日国际新闻（本地版）

每天自动抓取 BBC、CNN、卫报、半岛电视台、NPR，以及 TechCrunch、The Verge、
Ars Technica、CNBC、金融时报等专业科技/商业媒体的公开 RSS，生成一个本地静态新闻页。

另有三个专题板块：

- **AI 动态**：OpenAI、Anthropic、Google DeepMind、Hugging Face 官方发布，
  以及 TechCrunch AI、The Verge AI 的行业报道（最近 7 天）。
- **人物观点**：追踪 Sam Altman、Dario Amodei、Elon Musk、Ray Dalio、
  Demis Hassabis、黄仁勋、Ilya Sutskever、李飞飞等人的言论与访谈（最近 7 天）。
- 商业、科技板块在配额上更侧重专业媒体。

## 快速开始

- **推荐**：双击 `start_server.bat`，打开 <http://127.0.0.1:8765/>，
  点右上角「立即更新」即可随时抓取最新新闻；更新完页面会自动刷新。
- 直接双击 `site\index.html` 也能阅读，但此时更新按钮不可用。
- 手动更新一次：双击 `run_daily.bat`，或运行 `python fetch_news.py`
- 注册每天自动更新（07:30 与 19:30）：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
```

- 取消自动更新：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1 -Remove
```

- 设置本地服务随登录自动启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_autostart.ps1
```

- 取消登录自启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_autostart.ps1 -Remove
```

## 目录说明

| 路径 | 作用 |
| --- | --- |
| `fetch_news.py` | 抓取、过滤、去重并生成网页 |
| `news_core.py` | RSS/Atom 解析、时间过滤、HTML 生成等核心逻辑 |
| `config.py` | 媒体源、时间窗口、代理、条数上限 |
| `server.py` | 本地网页服务，提供页面与「立即更新」接口 |
| `start_server.bat` | 在后台启动本地服务 |
| `setup_autostart.ps1` | 创建/删除“登录时启动服务”的快捷方式 |
| `tests/` | 单元测试（`python -m unittest discover -s tests -t .`） |
| `site/index.html` | 今日新闻页面（自动生成） |
| `site/archive/` | 按天归档的页面（自动生成） |
| `data/` | 每天的结构化 JSON 数据（自动生成） |
| `logs/run.log` | 每次抓取的日志 |
| `logs/server.log` | 本地服务的日志 |

## 更新规则

更新有三种方式：每天 07:30/19:30 的计划任务自动更新、页面上「立即更新」按钮
（需本地服务运行）、双击 `run_daily.bat` 手动更新。

- 国际、商业、科技、体育默认收录最近 24 小时的新闻；某个分类条目不足时自动放宽到 48 小时，并在页面上注明。
- AI 动态与人物观点使用 7 天窗口（官方博客和人物发言都不是每天更新）。
- 人物观点通过 Google News 按“人名 + 言论动词”检索，并过滤影视、诉讼、通讯社转述等非观点内容。
- 同一链接去重；同一媒体的相同标题只保留一条；不同媒体对同一事件的报道会同时保留。
- 每个媒体在每个分类最多若干条（商业、科技、AI 配额更高），防止单一媒体刷屏。
- 抓取失败不会中断整次运行：页面会标注失败的来源；若全部失败，则保留上一次的页面。

## 常见问题

**「立即更新」按钮是灰的 / 提示“本地服务未启动”**
说明页面是通过 `file://` 直接打开的，或者本地服务没有运行。双击 `start_server.bat`
（或运行 `setup_autostart.ps1` 设为登录自启动），然后访问 <http://127.0.0.1:8765/>。

**点击更新后提示失败**
查看 `logs/server.log` 与 `logs/run.log`；最常见原因是本机代理离线。若提示端口被占用，
说明服务已在运行，直接访问 <http://127.0.0.1:8765/> 即可。

**页面没有更新 / 出现“失败”标记**
检查本机代理是否在线（默认 `http://127.0.0.1:7897`），可在 `config.py` 中修改 `PROXY`。
查看 `logs/run.log` 了解具体哪个源失败。

**计划任务没有运行**
任务设置为“错过就尽快补跑”，电脑开机后会补上；也可以在任务计划程序中右键
`NewsDailyUpdate` → 运行。

**CNN 的链接为什么先跳到 Google News**
CNN 官方 RSS 已于 2023 年停更，因此通过 Google News 按来源筛选 CNN 的新闻。
点击后会先经过 Google News 跳转到 CNN 原文。

## 说明与限制

- 只展示标题、摘要和原文链接，不抓取全文；内容版权归原媒体所有。
- 需要这台电脑开机且有可用的代理网络才能更新。
- Anthropic 没有公开 RSS，其官方动态通过 Google News 的 `site:anthropic.com/news` 检索获得。
- 人物观点的判定基于标题关键词的启发式规则，仍可能有少量“关于该人物的报道”混入，
  或漏掉标题不含言论动词的优质访谈；点开原文即可确认。
- Google News 对并发请求较敏感，程序已对这类请求做了串行化和重试。
- 目前是纯本地站点，不对外发布；后续可迁移到 GitHub Pages 公网托管。
