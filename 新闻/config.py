"""站点配置：媒体源、时间窗口、输出路径与代理。"""
from pathlib import Path
from urllib.parse import quote_plus


def gnews(query: str) -> str:
    """构造 Google News RSS 检索地址（用于按来源/公司/人物筛选）。"""
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = BASE_DIR / "site"
ARCHIVE_DIR = SITE_DIR / "archive"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

SITE_TITLE = "每日国际新闻"

# 本地网页服务：页面上的“立即更新”按钮依赖它，仅监听本机
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765

# 本机代理（Clash 默认端口）。设为 None 时直连/走系统代理；
# 代理连不上时会自动回退尝试直连。
PROXY = "http://127.0.0.1:7897"

# “当天新闻”时间窗口：默认 24 小时，某分类条目不足时放宽到 48 小时
WINDOW_HOURS = 24
FALLBACK_HOURS = 48
# 个别板块的窗口按需调整：AI 官方博客更新不频繁，观点类内容用 7 天
CATEGORY_WINDOW = {"ai": 168, "voices": 168}
CATEGORY_FALLBACK = {"ai": 168, "voices": 168}
CATEGORY_MIN_ITEMS = 4

# 每个媒体在每个分类中的最多条数；商业/科技/AI 给更大的配额
PER_SOURCE_CAP = {"world": 5, "business": 8, "tech": 8, "ai": 6, "voices": 3, "sport": 6}
# 每个分类页面上的总条数上限
CATEGORY_CAP = {"world": 32, "business": 48, "tech": 48, "ai": 36, "voices": 24, "sport": 18}

# 抓取超时（秒）与整体并发数
TIMEOUT = 20
MAX_WORKERS = 8

SOURCES = [
    # ── 国际 ──────────────────────────────────────────────
    {"name": "BBC", "category": "world",
     "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "CNN", "category": "world",
     "url": gnews("source:CNN when:2d")},
    {"name": "卫报", "category": "world",
     "url": "https://www.theguardian.com/world/rss"},
    {"name": "半岛电视台", "category": "world",
     "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "NPR", "category": "world",
     "url": "https://feeds.npr.org/1004/rss.xml"},

    # ── 商业（专业财经媒体为主）───────────────────────────
    {"name": "BBC", "category": "business",
     "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    {"name": "CNBC", "category": "business",
     "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "金融时报", "category": "business",
     "url": "https://www.ft.com/rss/home"},
    {"name": "商业内幕", "category": "business",
     "url": "https://www.businessinsider.com/rss"},
    {"name": "卫报", "category": "business",
     "url": "https://www.theguardian.com/business/rss"},
    {"name": "NPR", "category": "business",
     "url": "https://feeds.npr.org/1006/rss.xml"},

    # ── 科技（专业科技媒体为主）───────────────────────────
    {"name": "TechCrunch", "category": "tech",
     "url": "https://techcrunch.com/feed/"},
    {"name": "The Verge", "category": "tech",
     "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "Ars Technica", "category": "tech",
     "url": "https://feeds.arstechnica.com/arstechnica/index"},
    {"name": "MIT科技评论", "category": "tech",
     "url": "https://www.technologyreview.com/feed/"},
    {"name": "CNBC", "category": "tech",
     "url": "https://www.cnbc.com/id/19854910/device/rss/rss.html"},
    {"name": "BBC", "category": "tech",
     "url": "https://feeds.bbci.co.uk/news/technology/rss.xml"},
    {"name": "卫报", "category": "tech",
     "url": "https://www.theguardian.com/uk/technology/rss"},
    {"name": "NPR", "category": "tech",
     "url": "https://feeds.npr.org/1019/rss.xml"},

    # ── AI 动态（官方发布 + 专业 AI 媒体）─────────────────
    {"name": "OpenAI", "category": "ai",
     "url": "https://openai.com/news/rss.xml"},
    {"name": "Anthropic", "category": "ai",
     "url": gnews("site:anthropic.com/news when:7d")},
    {"name": "Google DeepMind", "category": "ai",
     "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "Hugging Face", "category": "ai",
     "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "TechCrunch", "category": "ai",
     "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "The Verge", "category": "ai",
     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},

    # ── 人物观点（Google News 言论检索，近 7 天）───────────
    {"name": "Sam Altman", "category": "voices",
     "url": gnews('"Sam Altman" (OpenAI OR AI OR says OR said OR interview OR warns OR argues) when:7d')},
    {"name": "Dario Amodei", "category": "voices",
     "url": gnews('"Dario Amodei" (Anthropic OR AI OR says OR said OR interview OR warns OR argues) when:7d')},
    {"name": "Elon Musk", "category": "voices",
     "url": gnews('"Elon Musk" (AI OR Grok OR xAI OR says OR said OR interview OR warns OR predicts) when:7d')},
    {"name": "Ray Dalio", "category": "voices",
     "url": gnews('"Ray Dalio" (says OR said OR warns OR predicts OR interview OR economy OR debt OR market) when:7d')},
    {"name": "Demis Hassabis", "category": "voices",
     "url": gnews('"Demis Hassabis" (AI OR DeepMind OR says OR said OR interview OR predicts) when:7d')},
    {"name": "黄仁勋", "category": "voices", "aliases": ["Jensen Huang"],
     "url": gnews('"Jensen Huang" (AI OR Nvidia OR says OR said OR interview OR predicts) when:7d')},
    {"name": "Ilya Sutskever", "category": "voices",
     "url": gnews('"Ilya Sutskever" (AI OR SSI OR says OR said OR interview OR believes) when:7d')},
    {"name": "李飞飞", "category": "voices", "aliases": ["Fei-Fei Li"],
     "url": gnews('"Fei-Fei Li" (AI OR Stanford OR says OR said OR interview OR believes) when:7d')},

    # ── 体育 ──────────────────────────────────────────────
    {"name": "BBC", "category": "sport",
     "url": "https://feeds.bbci.co.uk/sport/rss.xml"},
]
