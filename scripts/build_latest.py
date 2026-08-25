"""
构建 latest_ranks.json：
1. 加载最近两天的 JSON 快照
2. 按分类对比趋势（新上榜/掉榜/排名变化/阅读量变化）
3. 可选调用 Gemini Flash 生成 AI 总结
4. 输出 latest_ranks.json + trends/YYYY-MM-DD.json
"""
import os
import re
import json
import glob
import sys
import argparse
from urllib.parse import quote


def parse_reads(reads_str: str) -> float:
    """将 '15.2万' 这样的字符串转为数值，用于比较。"""
    if not reads_str or reads_str == "未知":
        return 0
    s = reads_str.strip().replace(",", "")
    try:
        if "万" in s:
            return float(s.replace("万", "")) * 10000
        return float(s)
    except ValueError:
        return 0


def format_reads_change(diff: float) -> str:
    """格式化阅读量变化。"""
    if abs(diff) >= 10000:
        return f"{'+' if diff > 0 else ''}{diff / 10000:.1f}万"
    return f"{'+' if diff > 0 else ''}{int(diff)}"


def load_snapshot(path: str) -> dict:
    """加载一个 JSON 快照文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cat_key(cat: dict) -> str:
    """用 channel:name 做唯一键，兼容老数据（无 channel 字段当 female）。"""
    return f"{cat.get('channel', 'female')}:{cat['name']}"


def compare_categories(today_cats: list, prev_cats: list) -> dict:
    """
    对比两天的分类数据，返回每个分类的趋势信息。
    key = "channel:分类名", value = trend dict
    """
    # 构建 prev 的索引: cat_key -> {url: (rank, reads_str, title)}
    prev_index = {}
    for cat in prev_cats:
        url_map = {}
        for i, book in enumerate(cat.get("books", [])):
            url_map[book["url"]] = {
                "rank": i + 1,
                "reads": book.get("reads", "未知"),
                "title": book.get("title", "未知"),
                "intro": book.get("intro", "暂无简介"),
            }
        prev_index[cat_key(cat)] = url_map

    trends = {}
    for cat in today_cats:
        ck = cat_key(cat)
        prev_urls = prev_index.get(ck, {})
        today_books = cat.get("books", [])

        new_books = []
        dropped_books = []
        risers = []
        fallers = []
        reads_growth = []

        today_urls = set()
        for i, book in enumerate(today_books):
            url = book["url"]
            today_urls.add(url)
            today_rank = i + 1
            title = book.get("title", "未知")

            if url in prev_urls:
                prev_info = prev_urls[url]
                prev_rank = prev_info["rank"]
                rank_change = prev_rank - today_rank  # 正数=上升

                if rank_change > 0:
                    risers.append({"title": title, "change": f"+{rank_change}"})
                elif rank_change < 0:
                    fallers.append({"title": title, "change": str(rank_change)})

                # 阅读量变化
                today_reads = parse_reads(book.get("reads", ""))
                prev_reads = parse_reads(prev_info["reads"])
                if today_reads > 0 and prev_reads > 0:
                    diff = today_reads - prev_reads
                    if diff != 0:
                        reads_growth.append(
                            {"title": title, "growth": format_reads_change(diff)}
                        )
            else:
                new_books.append(title)

        # 掉出榜单的书（含简介以便 AI 分析题材）
        for url, info in prev_urls.items():
            if url not in today_urls:
                dropped_books.append({
                    "title": info["title"],
                    "intro": info.get("intro", "暂无简介")[:100],
                })

        # 排序：涨幅最大的在前
        risers.sort(key=lambda x: int(x["change"].replace("+", "")), reverse=True)
        fallers.sort(key=lambda x: int(x["change"]))
        reads_growth.sort(
            key=lambda x: parse_reads(x["growth"].replace("+", "")), reverse=True
        )

        trends[ck] = {
            "new_count": len(new_books),
            "dropped_count": len(dropped_books),
            "new_books": new_books[:5],
            "dropped_books": dropped_books[:5],
            "top_risers": risers[:3],
            "top_fallers": fallers[:3],
            "reads_growth": reads_growth[:3],
            "summary": "",  # AI 总结，由 generate_ai_summaries 填充
        }

    return trends


def generate_trend_summary_text(cat_name: str, trend: dict) -> str:
    """生成基于规则的简短趋势文本（作为 AI 总结不可用时的 fallback）。"""
    parts = []
    if trend["new_count"] > 0:
        parts.append(f"新增{trend['new_count']}本上榜")
    if trend["dropped_count"] > 0:
        dropped_titles = [d["title"] if isinstance(d, dict) else d
                          for d in trend.get("dropped_books", [])]
        if dropped_titles:
            parts.append(f"{trend['dropped_count']}本掉出（{'、'.join('《' + t + '》' for t in dropped_titles)}）")
        else:
            parts.append(f"{trend['dropped_count']}本掉出")
    if trend["top_risers"]:
        r = trend["top_risers"][0]
        parts.append(f"《{r['title']}》排名上升{r['change']}位")
    if trend["reads_growth"]:
        g = trend["reads_growth"][0]
        parts.append(f"《{g['title']}》阅读量{g['growth']}")
    if not parts:
        parts.append("榜单无明显变动")
    return "；".join(parts) + "。"


def build_ai_prompt(cat_name: str, cat: dict, trend: dict) -> str:
    """构建 AI 总结的 prompt（统一模板）。"""
    # 当前榜单书籍
    intros = []
    for i, book in enumerate(cat.get("books", [])[:20]):
        intros.append(
            f"{i+1}. 《{book['title']}》- {book.get('author', '未知')}\n"
            f"   在读：{book.get('reads', '未知')}\n"
            f"   简介：{book.get('intro', '无')[:200]}"
        )
    intros_text = "\n".join(intros)

    # 新上榜书籍
    new_books = trend.get("new_books", [])
    new_text = "、".join(f"《{t}》" for t in new_books) if new_books else "无"

    # 掉出榜单书籍（含简介）
    dropped = trend.get("dropped_books", [])
    if dropped:
        dropped_lines = []
        for d in dropped:
            if isinstance(d, dict):
                dropped_lines.append(f"《{d['title']}》（{d.get('intro', '暂无简介')[:50]}）")
            else:
                dropped_lines.append(f"《{d}》")
        dropped_text = "、".join(dropped_lines)
    else:
        dropped_text = "无"

    # 排名变动
    risers = trend.get("top_risers", [])
    risers_text = "、".join(f"《{r['title']}》{r['change']}" for r in risers) if risers else "无"
    fallers = trend.get("top_fallers", [])
    fallers_text = "、".join(f"《{f['title']}》{f['change']}" for f in fallers) if fallers else "无"

    channel_label = "男频" if cat.get("channel") == "male" else "女频"
    return f"""你是一位网文行业分析师。请根据以下数据，为番茄小说{channel_label}「{cat_name}」分类新书榜生成结构化分析。

## 当前榜单 Top 20
{intros_text}

## 榜单变动
- 新上榜：{new_text}
- 掉出榜单：{dropped_text}
- 排名上升：{risers_text}
- 排名下降：{fallers_text}

## 输出要求（请严格按以下格式输出，使用 Markdown）

**🔥 题材趋势**
用1-2句话总结当前分类的主流题材和高频元素（如穿书/重生/系统/种田等），点明哪些设定扎堆出现。

**📖 读者偏好**
用1句话概括读者口味方向（甜宠/虐/爽/日常/暗黑等），以及金手指类型偏好。

**🆕 新上榜作品**
列出新上榜书名，每本用一句话点评其题材亮点或差异化卖点。

**📉 掉出榜单**
列出掉出书名及其题材方向，简要分析可能掉出的原因（如题材饱和、同质化等）。

**💡 值得关注**
挑1-2本有差异化潜力的作品，说明理由。

要求：每个板块2-3句话，总字数250字以内。语言简洁专业，像行业快报。"""


BATCH_SIZE = 3  # 每批合并的分类数

MARKET_PERIODS = [("7", 7), ("14", 14), ("30", 30), ("all", None)]

# --- 女频综合赛道 ---
FEMALE_GENRE_GROUPS = [
    {"name": "古风言情", "channel": "female", "categories": ["female:古风世情", "female:古言脑洞", "female:宫斗宅斗", "female:种田"]},
    {"name": "现代言情", "channel": "female", "categories": ["female:现言脑洞", "female:豪门总裁", "female:职场婚恋", "female:青春甜宠"]},
    {"name": "幻想言情", "channel": "female", "categories": ["female:玄幻言情", "female:科幻末世", "female:悬疑脑洞", "female:女频悬疑"]},
    {"name": "快穿衍生", "channel": "female", "categories": ["female:快穿", "female:女频衍生"]},
    {"name": "年代民国", "channel": "female", "categories": ["female:年代", "female:民国言情"]},
    {"name": "娱乐星光", "channel": "female", "categories": ["female:星光璀璨"]},
    {"name": "游戏体育", "channel": "female", "categories": ["female:游戏体育"]},
]

# --- 男频综合赛道 ---
MALE_GENRE_GROUPS = [
    {"name": "玄幻仙侠", "channel": "male", "categories": ["male:东方仙侠", "male:西方奇幻", "male:传统玄幻", "male:玄幻脑洞"]},
    {"name": "都市群像", "channel": "male", "categories": ["male:都市日常", "male:都市修真", "male:都市高武", "male:都市脑洞", "male:都市种田"]},
    {"name": "历史军事", "channel": "male", "categories": ["male:历史古代", "male:历史脑洞", "male:抗战谍战"]},
    {"name": "悬疑灵异", "channel": "male", "categories": ["male:悬疑脑洞", "male:悬疑灵异"]},
    {"name": "衍生其他", "channel": "male", "categories": ["male:动漫衍生", "male:男频衍生", "male:游戏体育"]},
    {"name": "战神赘婿", "channel": "male", "categories": ["male:战神赘婿"]},
    {"name": "科幻末世", "channel": "male", "categories": ["male:科幻末世"]},
]

GENRE_GROUPS = FEMALE_GENRE_GROUPS + MALE_GENRE_GROUPS

MARKET_KEYWORDS = [
    # 女频高频
    "重生", "穿书", "快穿", "系统", "空间", "团宠", "萌宝", "幼崽", "女配", "炮灰",
    "反派", "权臣", "宅斗", "宫斗", "和离", "替嫁", "逃荒", "种田", "美食", "经商",
    "年代", "七零", "八零", "军婚", "豪门", "总裁", "真假千金", "先婚后爱", "追妻",
    "甜宠", "双洁", "强制爱", "无CP", "末世", "废土", "天灾", "囤货", "异能",
    "国运", "星际", "修仙", "玄学", "无限流", "悬疑", "直播", "综艺", "娱乐圈",
    "校园", "暗恋", "青梅竹马", "民国", "兽世", "远古", "基建",
    # 男频高频
    "系统流", "无敌流", "升级流", "扮猪吃虎", "杀伐果断", "诸天", "洪荒", "模拟器",
    "签到", "夺舍", "鉴宝", "赘婿", "战神", "兵王", "神医", "特种兵", "御兽",
    "氪金", "炼体", "苟道", "横推", "无敌", "诸天流", "签到流", "掠夺", "气运",
    "炼丹", "宗门", "渡劫", "化神", "血脉", "武道", "灵气复苏", "诡异", "规则怪谈",
]


def build_batch_ai_prompt(batch: list) -> str:
    """构建批量 AI 总结的 prompt。

    batch: list of (cat_name, cat_data, trend_data) tuples
    """
    sections = []
    for cat_name, cat, trend in batch:
        intros = []
        for i, book in enumerate(cat.get("books", [])[:20]):
            intros.append(
                f"{i+1}. 《{book['title']}》- {book.get('author', '未知')}\n"
                f"   在读：{book.get('reads', '未知')}\n"
                f"   简介：{book.get('intro', '无')[:200]}"
            )
        intros_text = "\n".join(intros)

        new_books = trend.get("new_books", [])
        new_text = "、".join(f"《{t}》" for t in new_books) if new_books else "无"

        dropped = trend.get("dropped_books", [])
        if dropped:
            dropped_lines = []
            for d in dropped:
                if isinstance(d, dict):
                    dropped_lines.append(
                        f"《{d['title']}》（{d.get('intro', '暂无简介')[:50]}）"
                    )
                else:
                    dropped_lines.append(f"《{d}》")
            dropped_text = "、".join(dropped_lines)
        else:
            dropped_text = "无"

        risers = trend.get("top_risers", [])
        risers_text = (
            "、".join(f"《{r['title']}》{r['change']}" for r in risers)
            if risers else "无"
        )
        fallers = trend.get("top_fallers", [])
        fallers_text = (
            "、".join(f"《{f['title']}》{f['change']}" for f in fallers)
            if fallers else "无"
        )

        sections.append(
            f"### 分类：{cat_name}（{'男频' if cat.get('channel') == 'male' else '女频'}）\n\n"
            f"**当前榜单 Top 20：**\n{intros_text}\n\n"
            f"**榜单变动：**\n"
            f"- 新上榜：{new_text}\n"
            f"- 掉出榜单：{dropped_text}\n"
            f"- 排名上升：{risers_text}\n"
            f"- 排名下降：{fallers_text}"
        )

    all_sections = "\n\n---\n\n".join(sections)
    cat_names = [b[0] for b in batch]

    output_examples = "\n\n".join(
        f"===BEGIN: {name}===\n"
        f"**🔥 题材趋势** ...\n"
        f"**📖 读者偏好** ...\n"
        f"**🆕 新上榜作品** ...\n"
        f"**📉 掉出榜单** ...\n"
        f"**💡 值得关注** ...\n"
        f"===END: {name}==="
        for name in cat_names
    )

    return (
        f"你是一位网文行业分析师。请根据以下数据，"
        f"为番茄小说的多个分类新书榜分别生成结构化分析。\n\n"
        f"{all_sections}\n\n"
        f"## 输出要求\n\n"
        f"请严格按照以下格式，为每个分类分别输出分析。"
        f"每个分类的分析必须包裹在对应的标记中：\n\n"
        f"{output_examples}\n\n"
        f"每个板块2-3句话，每个分类总字数250字以内。"
        f"语言简洁专业，像行业快报。\n"
        f"注意：必须为每个分类都输出完整分析，不可省略任何分类。"
    )


def parse_batch_response(response_text: str, cat_names: list) -> dict:
    """解析批量 AI 响应，返回 {cat_name: summary} 字典。"""
    results = {}
    for name in cat_names:
        pattern = rf"===BEGIN:\s*{re.escape(name)}\s*===(.*?)===END:\s*{re.escape(name)}\s*==="
        match = re.search(pattern, response_text, re.DOTALL)
        if match:
            summary = match.group(1).strip()
            if summary:
                results[name] = summary
    return results


def _save_trends_incremental(trend_path: str, date: str,
                             prev_date: str, trends: dict):
    """增量保存趋势数据到文件（每批成功后立即写入）。"""
    if not trend_path:
        return
    trend_output = {
        "date": date,
        "prev_date": prev_date,
        "trends": trends,
    }
    with open(trend_path, "w", encoding="utf-8") as f:
        json.dump(trend_output, f, ensure_ascii=False, indent=2)


def api_type_filename(type_name: str) -> str:
    """将类型名转成适合作为静态 JSON 文件名的名称。"""
    name = (type_name or "").strip()
    name = re.sub(r"[\\/]+", "_", name)
    name = re.sub(r"[^\w\u4e00-\u9fff\s-]", "_", name)
    name = re.sub(r"\s+", "_", name).strip("._")
    return name or "unknown"


def write_json(path: str, payload: dict):
    """统一写 JSON，确保中文可读。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def build_lastest_api(output: dict, base_dir: str):
    """生成静态 lastest 数据接口。

    GitHub Pages 不支持动态 query API，因此这里将 type 参数映射为静态文件：
    - api/lastest/all.json：全量数据
    - api/lastest/<type>.json：单个类型数据
    - api/lastest.json / api/lastest/index.json：类型索引
    """
    api_root = os.path.join(base_dir, "api")
    lastest_dir = os.path.join(api_root, "lastest")
    os.makedirs(lastest_dir, exist_ok=True)
    for old_path in glob.glob(os.path.join(lastest_dir, "*.json")):
        os.remove(old_path)

    date = output.get("date", "")
    prev_date = output.get("prev_date", "")
    categories = output.get("categories", [])

    all_payload = {
        "type": "all",
        "date": date,
        "prev_date": prev_date,
        "categories": categories,
    }
    write_json(os.path.join(lastest_dir, "all.json"), all_payload)

    types = [{
        "type": "all",
        "url": "api/lastest/all.json",
        "category_count": len(categories),
        "book_count": sum(len(cat.get("books", [])) for cat in categories),
    }]

    used_filenames = {"all"}
    for cat in categories:
        type_name = cat.get("name", "")
        filename = api_type_filename(type_name)
        base_filename = filename
        suffix = 2
        while filename in used_filenames:
            filename = f"{base_filename}_{suffix}"
            suffix += 1
        used_filenames.add(filename)

        payload = {
            "type": type_name,
            "date": date,
            "prev_date": prev_date,
            "category": cat,
            "categories": [cat],
        }
        write_json(os.path.join(lastest_dir, f"{filename}.json"), payload)

        url = f"api/lastest/{quote(filename)}.json"
        types.append({
            "type": type_name,
            "url": url,
            "book_count": len(cat.get("books", [])),
        })

    index_payload = {
        "date": date,
        "prev_date": prev_date,
        "types": types,
    }
    write_json(os.path.join(lastest_dir, "index.json"), index_payload)
    write_json(os.path.join(api_root, "lastest.json"), index_payload)

    return lastest_dir


def parse_change(change: str) -> int:
    """解析 '+3' / '-2' 这类排名变化。"""
    try:
        return int(str(change or "0").replace("+", ""))
    except ValueError:
        return 0


def normalize_trend_key(key: str) -> str:
    """将老格式的趋势键（纯分类名）标准化为 channel:name 格式。"""
    key = str(key or "")
    if ":" in key:
        return key
    return f"female:{key}"


def load_trend_rows(trends_dir: str) -> list:
    """加载全部趋势归档，按日期升序排列。兼容老格式键名。"""
    rows = []
    for path in sorted(glob.glob(os.path.join(trends_dir, "*.json"))):
        try:
            data = load_snapshot(path)
            # 标准化趋势键名：老格式 "古风世情" -> "female:古风世情"
            raw_trends = data.get("trends", {})
            normalized = {normalize_trend_key(k): v for k, v in raw_trends.items()}
            rows.append({
                "date": data.get("date", ""),
                "prev_date": data.get("prev_date", ""),
                "trends": normalized,
            })
        except Exception as e:
            print(f"  ⚠️  跳过趋势文件 {path}: {e}")
    return sorted([r for r in rows if r["date"]], key=lambda x: x["date"])


def summarize_market_rows(rows: list) -> dict:
    """汇总某个分类在一组趋势行中的动能指标。"""
    totals = {
        "new_count": 0,
        "dropped_count": 0,
        "riser_count": 0,
        "faller_count": 0,
        "read_count": 0,
        "read_growth_total": 0,
        "active_days": 0,
    }
    for row in rows:
        trend = row.get("trend") or {}
        riser_count = len(trend.get("top_risers", []))
        faller_count = len(trend.get("top_fallers", []))
        read_count = len(trend.get("reads_growth", []))
        read_growth_total = sum(
            parse_reads(item.get("growth", ""))
            for item in trend.get("reads_growth", [])
        )
        totals["new_count"] += int(trend.get("new_count", 0) or 0)
        totals["dropped_count"] += int(trend.get("dropped_count", 0) or 0)
        totals["riser_count"] += riser_count
        totals["faller_count"] += faller_count
        totals["read_count"] += read_count
        totals["read_growth_total"] += read_growth_total
        if (
            trend.get("new_count", 0) or trend.get("dropped_count", 0)
            or riser_count or faller_count or read_count
        ):
            totals["active_days"] += 1
    return totals


def market_score(totals: dict) -> int:
    """计算全站热点分：综合赛道和具体分类只看新增在读量。"""
    return round(totals["read_growth_total"])


def format_market_reads(value: float) -> str:
    """格式化市场层面的新增在读量。"""
    if abs(value) >= 10000:
        return f"{value / 10000:.1f}万"
    return str(round(value))


def collect_market_hot_types(category_keys: list, rows_window: list) -> list:
    """统计具体分类热度。category_keys 是 ["female:古风世情", "male:战神赘婿", ...] 格式。"""
    result = []
    for ck in category_keys:
        rows = [
            {"trend": row.get("trends", {}).get(ck)}
            for row in rows_window
            if row.get("trends", {}).get(ck)
        ]
        totals = summarize_market_rows(rows)
        score = market_score(totals)
        if score <= 0:
            continue
        result.append({
            "name": ck.split(":", 1)[-1] if ":" in ck else ck,
            "channel": ck.split(":", 1)[0] if ":" in ck else "female",
            "key": ck,
            "score": score,
            "new_count": totals["new_count"],
            "dropped_count": totals["dropped_count"],
            "read_count": totals["read_count"],
            "read_growth_total": totals["read_growth_total"],
            "active_days": totals["active_days"],
        })
    return sorted(
        result,
        key=lambda x: (x["read_growth_total"], x["read_count"]),
        reverse=True
    )


def collect_market_hot_genres(category_keys: list, hot_types: list) -> list:
    """按综合赛道聚合具体分类热度。category_keys 是 cat_key 列表。"""
    type_map = {item["key"]: item for item in hot_types}
    genres = []
    for group in GENRE_GROUPS:
        matched = []
        for ck in group["categories"]:
            if ck not in category_keys:
                continue
            matched.append(type_map.get(ck, {
                "name": ck.split(":", 1)[-1],
                "channel": ck.split(":", 1)[0],
                "key": ck,
                "score": 0,
                "new_count": 0,
                "dropped_count": 0,
                "read_count": 0,
                "read_growth_total": 0,
                "active_days": 0,
            }))
        if not matched:
            continue
        read_growth_total = sum(item["read_growth_total"] for item in matched)
        if read_growth_total <= 0:
            continue
        lead = sorted(
            matched,
            key=lambda x: (x["read_growth_total"], x["read_count"]),
            reverse=True
        )[0]
        genres.append({
            "name": group["name"],
            "channel": group.get("channel", ""),
            "score": round(read_growth_total),
            "new_count": sum(item["new_count"] for item in matched),
            "dropped_count": sum(item["dropped_count"] for item in matched),
            "read_count": sum(item["read_count"] for item in matched),
            "read_growth_total": read_growth_total,
            "active_days": sum(item["active_days"] for item in matched),
            "lead_category": lead["name"],
            "categories": [item["name"] for item in matched],
        })
    return sorted(
        genres,
        key=lambda x: (x["read_growth_total"], x["read_count"]),
        reverse=True
    )


def add_theme_hits(score_map: dict, text: str, category_name: str, weight: int):
    """给命中的题材关键词加权。"""
    source = str(text or "")
    if not source:
        return
    for keyword in MARKET_KEYWORDS:
        if keyword not in source:
            continue
        item = score_map[keyword]
        item["count"] += weight
        item["categories"].add(category_name)


def collect_market_hot_themes(output: dict, rows_window: list,
                              category_keys: list) -> list:
    """只统计近期新上榜作品中的高频题材词。"""
    score_map = {
        name: {"name": name, "count": 0, "categories": set()}
        for name in MARKET_KEYWORDS
    }
    latest_book_map = {}
    for cat in output.get("categories", []):
        for book in cat.get("books", []):
            title = book.get("title", "")
            if title:
                latest_book_map[title] = book

    for row in rows_window:
        for ck in category_keys:
            trend = row.get("trends", {}).get(ck)
            if not trend:
                continue
            for title in trend.get("new_books", []):
                book = latest_book_map.get(title, {})
                add_theme_hits(
                    score_map,
                    f"{title} {book.get('intro', '')}",
                    ck,
                    1
                )

    themes = []
    for item in score_map.values():
        if item["count"] <= 0:
            continue
        themes.append({
            "name": item["name"],
            "count": item["count"],
            "category_count": len(item["categories"]),
        })
    return sorted(
        themes,
        key=lambda x: (x["count"], x["category_count"]),
        reverse=True
    )


def build_rule_market_summary(period_label: str, hot_genres: list,
                              hot_types: list, hot_themes: list) -> str:
    """基于统计结果生成全站热点兜底文案。"""
    top_genres = "、".join(item["name"] for item in hot_genres[:2])
    top_types = "、".join(item["name"] for item in hot_types[:3])
    top_themes = "、".join(item["name"] for item in hot_themes[:6])
    if not top_genres and not top_types:
        return f"{period_label}暂无足够数据判断全站热点。"
    return (
        f"{period_label}里，{top_genres or top_types} 的阅读增长更强，"
        f"具体分类以 {top_types} 的新增在读更集中；新书题材上 {top_themes} "
        f"更高频，说明读者仍偏好强设定、强情绪钩子和明确爽点。"
    )


def build_market_summary_payload(output: dict, trends_dir: str) -> dict:
    """生成全站热点统计和规则兜底总结。"""
    category_keys = [cat_key(cat) for cat in output.get("categories", [])]
    trend_rows = load_trend_rows(trends_dir)
    periods = {}

    for key, days in MARKET_PERIODS:
        rows_window = trend_rows if days is None else trend_rows[-days:]
        period_label = "全部样本" if days is None else f"近 {days} 日"
        hot_types = collect_market_hot_types(category_keys, rows_window)
        hot_genres = collect_market_hot_genres(category_keys, hot_types)
        hot_themes = collect_market_hot_themes(output, rows_window, category_keys)
        fallback_summary = build_rule_market_summary(
            period_label, hot_genres, hot_types, hot_themes
        )
        periods[key] = {
            "period": period_label,
            "source": "rule",
            "summary": fallback_summary,
            "fallback_summary": fallback_summary,
            "hot_genres": hot_genres[:5],
            "hot_types": hot_types[:6],
            "hot_themes": hot_themes[:14],
        }

    return {
        "date": output.get("date", ""),
        "prev_date": output.get("prev_date", ""),
        "periods": periods,
    }


def build_market_ai_prompt(payload: dict) -> str:
    """构建全站热点 AI 总结 prompt。"""
    sections = []
    for key, data in payload.get("periods", {}).items():
        genres = "、".join(
            f"{item['name']}(新增在读{format_market_reads(item.get('read_growth_total', 0))}, "
            f"增长作品{item.get('read_count', 0)})"
            for item in data.get("hot_genres", [])[:5]
        )
        types = "、".join(
            f"{item['name']}(新增在读{format_market_reads(item.get('read_growth_total', 0))}, "
            f"增长作品{item.get('read_count', 0)})"
            for item in data.get("hot_types", [])[:6]
        )
        themes = "、".join(
            f"{item['name']}(新书{item['count']}本)"
            for item in data.get("hot_themes", [])[:10]
        )
        sections.append(
            f"周期 {key} / {data['period']}:\n"
            f"- 综合赛道（按阅读增长量排序）: {genres or '无'}\n"
            f"- 具体分类（按阅读增长量排序）: {types or '无'}\n"
            f"- 高频题材（只统计新上榜作品，按新书数量排序）: {themes or '无'}\n"
            f"- 规则兜底: {data['fallback_summary']}"
        )

    return f"""你是一位网文市场编辑，请根据番茄小说新书榜（男频+女频）的统计结果，为每个周期生成一段全站热点判断。

{chr(10).join(sections)}

要求：
1. 只基于给定统计，不要编造未出现的类型或题材。
2. 每个周期输出 1 段中文，80-140 字。
3. 综合赛道和具体分类必须按“新增在读/阅读增长”解读，不要写“榜单动能”或“排名动能”。
4. 高频题材必须按“新上榜作品数量”解读，不要混入存量榜单或摘要题材。
5. 点明综合赛道、具体分类、新书题材关键词，以及一句编辑判断。
6. 输出严格 JSON，不要 Markdown，不要解释，格式如下：
{{
  "7": "总结文本",
  "14": "总结文本",
  "30": "总结文本",
  "all": "总结文本"
}}"""


def parse_json_object(text: str) -> dict:
    """尽量从模型响应中提取 JSON 对象。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def enrich_market_summary_with_ai(payload: dict, api_key: str,
                                  base_url: str, model: str) -> dict:
    """使用 AI 改写全站热点总结；失败时保留规则兜底。"""
    try:
        from openai import OpenAI
    except ImportError:
        print("⚠️  openai 库未安装，跳过全站热点 AI 总结。")
        return payload

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_market_ai_prompt(payload)}],
            max_tokens=900,
            temperature=0.5,
        )
        parsed = parse_json_object(response.choices[0].message.content)
        for key, summary in parsed.items():
            if key in payload["periods"] and isinstance(summary, str) and summary.strip():
                payload["periods"][key]["summary"] = summary.strip()
                payload["periods"][key]["source"] = "ai"
        print("✅ 全站热点 AI 总结已生成")
    except Exception as e:
        print(f"⚠️  全站热点 AI 总结失败，使用规则兜底: {e}")

    return payload



def is_rule_summary(summary: str) -> bool:
    """判断一个总结是否为规则模板生成的（非 AI）。
    规则摘要特征：短小、分号分隔、以句号结尾、无换行。
    """
    if not summary:
        return True
    if summary == "首日数据，暂无趋势对比。":
        return True
    # 规则摘要一般 < 150 字，用分号分隔，无换行
    if len(summary) < 150 and "；" in summary and "\n" not in summary:
        return True
    return False


def generate_ai_summaries(categories: list, trends: dict,
                          api_key: str, base_url: str,
                          model: str, force: bool = False,
                          existing_trends: dict = None,
                          trend_path: str = None,
                          trend_date: str = "",
                          prev_date: str = "") -> dict:
    """通过 OpenAI 兼容 API 为每个分类生成 AI 总结。

    采用批量合并策略（每 BATCH_SIZE 个分类一次调用）减少 API 调用次数，
    并在每批成功后增量保存，避免中途失败丢失已完成的结果。
    批量失败的分类会自动降级为逐个重试。
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("⚠️  openai 库未安装，跳过 AI 总结。pip install openai")
        return trends

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
    existing_trends = existing_trends or {}

    # 1. 筛选需要生成总结的分类
    pending = []  # (cat_name, cat_data, trend_data)
    skipped = 0

    for cat in categories:
        cat_name = cat["name"]
        ck = cat_key(cat)
        if ck not in trends:
            continue

        if not force:
            existing_summary = existing_trends.get(ck, {}).get("summary", "")
            if existing_summary and not is_rule_summary(existing_summary):
                trends[ck]["summary"] = existing_summary
                skipped += 1
                continue

        pending.append((cat_name, cat, trends[ck]))

    if skipped > 0:
        print(f"  ⏭️  跳过 {skipped} 个已有 AI 总结的分类")

    if not pending:
        print("  ✅ 所有分类已有 AI 总结，无需生成")
        return trends

    # 2. 分批处理
    batches = [
        pending[i:i + BATCH_SIZE]
        for i in range(0, len(pending), BATCH_SIZE)
    ]
    failed_cats = []  # 批量失败后需单独重试的分类

    print(f"  📦 共 {len(pending)} 个分类，分 {len(batches)} 批处理"
          f"（每批最多 {BATCH_SIZE} 个）")

    for batch_idx, batch in enumerate(batches):
        batch_names = [b[0] for b in batch]
        print(f"\n  📦 第 {batch_idx + 1}/{len(batches)} 批: "
              f"{', '.join(batch_names)}")

        prompt = build_batch_ai_prompt(batch)

        max_retries = 3
        batch_success = False
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500 * len(batch),
                    temperature=0.7,
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("API 返回空内容")

                # 解析批量响应
                parsed = parse_batch_response(content, batch_names)

                if parsed:
                    for name, summary in parsed.items():
                        # name is the cat display name; find the matching cat_key
                        matched_ck = None
                        for b_name, b_cat, b_trend in batch:
                            if b_name == name:
                                matched_ck = cat_key(b_cat)
                                break
                        if matched_ck:
                            trends[matched_ck]["summary"] = summary
                            print(f"    ✅ {name}")

                    # 未解析出的分类加入失败队列
                    for name in batch_names:
                        if name not in parsed:
                            print(f"    ⚠️  未解析到: {name}（将单独重试）")
                            failed_cats.append(
                                next(b for b in batch if b[0] == name)
                            )

                    # 增量保存
                    _save_trends_incremental(
                        trend_path, trend_date, prev_date, trends
                    )
                    batch_success = True
                    break
                else:
                    raise ValueError("批量响应解析失败，未匹配到任何分类")

            except Exception as e:
                print(f"    ⚠️  第 {attempt} 次失败: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(5 * attempt)

        if not batch_success:
            print(f"    ❌ 批量生成失败（已重试 {max_retries} 次），"
                  f"将逐个重试")
            failed_cats.extend(batch)

    # 3. 对失败的分类逐个重试（降级为单分类 prompt）
    if failed_cats:
        print(f"\n  🔄 逐个重试 {len(failed_cats)} 个失败分类...")
        for cat_name, cat, trend in failed_cats:
            prompt = build_ai_prompt(cat_name, cat, trend)
            ck = cat_key(cat)
            max_retries = 3
            success = False
            for attempt in range(1, max_retries + 1):
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=500,
                        temperature=0.7,
                    )
                    content = response.choices[0].message.content
                    if not content or not content.strip():
                        raise ValueError("API 返回空内容")
                    trends[ck]["summary"] = content.strip()
                    print(f"    ✅ {cat_name}")
                    _save_trends_incremental(
                        trend_path, trend_date, prev_date, trends
                    )
                    success = True
                    break
                except Exception as e:
                    print(f"    ⚠️  {cat_name} 第 {attempt} 次失败: {e}")
                    if attempt < max_retries:
                        import time
                        time.sleep(5 * attempt)

            if not success:
                print(f"    ❌ {cat_name} 最终失败")
                old = existing_trends.get(ck, {}).get("summary", "")
                if old and not is_rule_summary(old):
                    trends[ck]["summary"] = old
                    print(f"    ↩️  保留旧 AI 总结: {cat_name}")
                else:
                    trends[ck]["summary"] = generate_trend_summary_text(
                        cat_name, trend
                    )

    return trends


def main():
    parser = argparse.ArgumentParser(description="构建 latest_ranks.json")
    parser.add_argument("--force", action="store_true",
                        help="强制重新生成所有 AI 总结，忽略已有总结")
    parser.add_argument("--date", type=str, default="",
                        help="指定目标日期 (YYYY-MM-DD)，默认使用最新快照")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    trends_dir = os.path.join(data_dir, "trends")
    os.makedirs(trends_dir, exist_ok=True)

    # 查找 JSON 快照文件（同时匹配新格式 fanqie_new_ranks_ 和老格式 fanqie_female_new_ranks_）
    snapshots = sorted(
        glob.glob(os.path.join(data_dir, "fanqie_new_ranks_*.json"))
        + glob.glob(os.path.join(data_dir, "fanqie_female_new_ranks_*.json"))
    )
    # 去重（同一日期可能有新旧两个文件，优先新格式）
    seen_dates = {}
    for s in snapshots:
        fname = os.path.basename(s)
        m = re.search(r"(\d{8})", fname)
        if m:
            d = m.group(1)
            if d not in seen_dates:
                seen_dates[d] = s
            elif "fanqie_female_" in os.path.basename(seen_dates[d]):
                # 新格式优先于老格式
                seen_dates[d] = s
    snapshots = sorted(seen_dates.values())

    if not snapshots:
        print("未找到任何 JSON 快照文件。请先运行迁移脚本或爬虫。")
        sys.exit(1)

    # 根据 --date 参数选择目标快照
    if args.date:
        target_date_compact = args.date.replace("-", "")
        # 先试新格式，再试老格式
        target_path = os.path.join(data_dir, f"fanqie_new_ranks_{target_date_compact}.json")
        if not os.path.exists(target_path):
            target_path = os.path.join(data_dir, f"fanqie_female_new_ranks_{target_date_compact}.json")
        if not os.path.exists(target_path):
            print(f"❌ 未找到 {args.date} 的快照文件")
            sys.exit(1)
        latest_path = target_path
        target_idx = snapshots.index(target_path) if target_path in snapshots else -1
    else:
        latest_path = snapshots[-1]
        target_idx = len(snapshots) - 1

    latest_data = load_snapshot(latest_path)
    print(f"目标快照: {os.path.basename(latest_path)} ({latest_data['date']})")

    # 标准化分类：给老数据（无 channel 字段）补上 channel="female"
    for cat in latest_data.get("categories", []):
        if "channel" not in cat:
            cat["channel"] = "female"

    # 加载前一天的快照（如果有）
    prev_data = None
    prev_date = ""
    if target_idx > 0:
        prev_path = snapshots[target_idx - 1]
        prev_data = load_snapshot(prev_path)
        # 同样标准化 prev_data
        for cat in prev_data.get("categories", []):
            if "channel" not in cat:
                cat["channel"] = "female"
        prev_date = prev_data.get("date", "")
        print(f"对比快照: {os.path.basename(prev_path)} ({prev_date})")

    # 加载已有的趋势数据（用于保留已有 AI 总结）
    existing_trends = {}
    trend_path = os.path.join(trends_dir, f"{latest_data['date']}.json")
    if os.path.exists(trend_path) and not args.force:
        try:
            with open(trend_path, "r", encoding="utf-8") as f:
                existing_trend_data = json.load(f)
                raw_trends = existing_trend_data.get("trends", {})
                # 标准化键名
                existing_trends = {normalize_trend_key(k): v for k, v in raw_trends.items()}
            ai_count = sum(1 for t in existing_trends.values()
                          if not is_rule_summary(t.get("summary", "")))
            rule_count = len(existing_trends) - ai_count
            print(f"已有趋势数据: {ai_count} 个 AI 总结, {rule_count} 个待补充")
        except Exception:
            pass

    if args.force:
        print("\n🔄 强制模式：将重新生成所有 AI 总结")

    # 对比趋势
    if prev_data:
        trends = compare_categories(
            latest_data["categories"], prev_data["categories"]
        )
    else:
        print("仅有一天数据，无法生成趋势对比。")
        trends = {
            cat_key(cat): {
                "new_count": 0,
                "dropped_count": 0,
                "new_books": [],
                "dropped_books": [],
                "top_risers": [],
                "top_fallers": [],
                "reads_growth": [],
                "summary": "首日数据，暂无趋势对比。",
            }
            for cat in latest_data["categories"]
        }

    # ========== AI 总结：通过 API_BASE_URL / API_KEY / API_MODEL 配置 ==========
    api_base_url = os.environ.get("API_BASE_URL", "")
    api_key = os.environ.get("API_KEY", "")
    api_model = os.environ.get("API_MODEL", "")

    if api_base_url and api_key and api_model:
        print(f"\n正在使用 {api_model} 生成 AI 总结...")
        print(f"  API: {api_base_url}")
        trends = generate_ai_summaries(
            latest_data["categories"], trends,
            api_key, api_base_url, api_model,
            force=args.force,
            existing_trends=existing_trends,
            trend_path=trend_path,
            trend_date=latest_data["date"],
            prev_date=prev_date
        )
    else:
        missing = [k for k, v in {"API_BASE_URL": api_base_url, "API_KEY": api_key, "API_MODEL": api_model}.items() if not v]
        print(f"\n未配置 AI 服务（缺少: {', '.join(missing)}），使用规则摘要替代。")
        for ck, trend in trends.items():
            # 保留已有 AI 总结
            old = existing_trends.get(ck, {}).get("summary", "")
            if old and not is_rule_summary(old):
                trend["summary"] = old
            elif not trend.get("summary"):
                # 从 cat_key 提取 display name
                display_name = ck.split(":", 1)[-1] if ":" in ck else ck
                trend["summary"] = generate_trend_summary_text(display_name, trend)

    # 组装输出
    output = {
        "date": latest_data["date"],
        "prev_date": prev_date,
        "categories": [],
    }

    for cat in latest_data["categories"]:
        ck = cat_key(cat)
        cat_output = {
            "name": cat["name"],
            "channel": cat.get("channel", "female"),
            "trend": trends.get(ck, {}),
            "books": cat.get("books", []),
        }
        output["categories"].append(cat_output)

    # 写入 latest_ranks.json
    out_path = os.path.join(data_dir, "latest_ranks.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已生成: {out_path}")

    # 生成静态 API 文件：api/lastest/all.json + api/lastest/<type>.json
    api_dir = build_lastest_api(output, base_dir)
    print(f"✅ Lastest API: {api_dir}")

    # 写入 trends/YYYY-MM-DD.json
    trend_output = {
        "date": latest_data["date"],
        "prev_date": prev_date,
        "trends": trends,
    }
    with open(trend_path, "w", encoding="utf-8") as f:
        json.dump(trend_output, f, ensure_ascii=False, indent=2)
    print(f"✅ 趋势存档: {trend_path}")

    # 生成全站热点总结：AI 优先，规则文案兜底
    market_payload = build_market_summary_payload(output, trends_dir)
    if api_base_url and api_key and api_model:
        market_payload = enrich_market_summary_with_ai(
            market_payload, api_key, api_base_url, api_model
        )
    market_path = os.path.join(data_dir, "market_summary.json")
    write_json(market_path, market_payload)
    print(f"✅ 全站热点总结: {market_path}")

    # 生成 dates.json 索引（供前端历史日期选择器使用）
    date_list = []
    for s in snapshots:
        fname = os.path.basename(s)
        # fanqie_female_new_ranks_YYYYMMDD.json -> YYYY-MM-DD
        m = re.search(r"(\d{4})(\d{2})(\d{2})", fname)
        if m:
            date_list.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    dates_path = os.path.join(data_dir, "dates.json")
    with open(dates_path, "w", encoding="utf-8") as f:
        json.dump({"dates": sorted(date_list)}, f, ensure_ascii=False, indent=2)
    print(f"✅ 日期索引: {dates_path} ({len(date_list)} 个日期)")

    # 生成书名关键词分析
    keyword_payload = build_title_keyword_analysis(output)
    keyword_path = os.path.join(data_dir, "title_keywords.json")
    write_json(keyword_path, keyword_payload)
    print(f"✅ 书名关键词分析: {keyword_path}")

    # 生成蓝海探测器分析
    blueocean_payload = build_blueocean_analysis(output)
    blueocean_path = os.path.join(data_dir, "blueocean.json")
    write_json(blueocean_path, blueocean_payload)
    print(f"✅ 蓝海探测分析: {blueocean_path}")

    # 生成新上榜开局分析（AI 优先，规则兜底）
    opening_payload = build_opening_analysis(output)
    if api_base_url and api_key and api_model:
        opening_payload = enrich_opening_analysis_with_ai(
            opening_payload, api_key, api_base_url, api_model
        )
    opening_path = os.path.join(data_dir, "opening_analysis.json")
    write_json(opening_path, opening_payload)
    print(f"✅ 新上榜开局分析: {opening_path}")

    # 生成 AI 友好资产：llms.txt / daily report / schema / overview
    ai_result = build_ai_assets(
        output=output,
        market_payload=market_payload,
        opening_payload=opening_payload,
        keyword_payload=keyword_payload,
        blueocean_payload=blueocean_payload,
        trends_dir=trends_dir,
        data_dir=data_dir,
        api_dir=api_dir,
        base_dir=base_dir,
        trends=trends,
        prev_date=prev_date,
    )
    print(f"✅ AI 友好资产: {ai_result}")


# ============================================================
# 书名关键词分析
# ============================================================

# 无意义的高频停用词（标点、语气词、量词等），提取时排除
STOP_CHARS = set("，。！？：；、·…—~～()（）【】[]「」\"' \t\n0123456789")

def extract_ngrams(title: str, min_len: int = 2, max_len: int = 6) -> list:
    """
    从书名中自动提取所有 2-6 字的连续子串（n-gram），
    过滤掉含标点/数字的片段和纯停用词。
    """
    title = title or ""
    if len(title) < 2:
        return []

    # 去掉标点和特殊字符，按标点分段
    import re
    segments = re.split(r'[，。！？：；、·…—~～()（）【】\[\]「」""\'\s\d]+', title)

    grams = []
    for seg in segments:
        seg = seg.strip()
        if len(seg) < min_len:
            continue
        for length in range(min_len, min(max_len, len(seg)) + 1):
            for i in range(len(seg) - length + 1):
                gram = seg[i:i + length]
                # 跳过含数字或英文字母的（只保留中文字符片段）
                if not all('\u4e00' <= ch <= '\u9fff' for ch in gram):
                    continue
                grams.append(gram)

    return grams


# 额外补充的网文专用词（确保不会被 n-gram 漏掉或被短词覆盖）
EXTRA_KEYWORDS = [
    "开局", "重生", "穿越", "系统", "无敌", "修仙", "模拟器", "签到",
    "赘婿", "战神", "兵王", "神医", "团宠", "甜宠", "病娇", "腹黑",
    "快穿", "无限流", "种田", "末世", "废土", "星际", "诸天",
    "宫斗", "宅斗", "追妻", "先婚后爱", "真假千金",
    "全民", "四合院", "大唐", "诡异", "规则怪谈",
]


def extract_title_keywords(title: str) -> list:
    """
    从书名中自动提取关键词。
    策略：先用 n-gram 提取所有中文连续片段，再补充专用词表。
    去重后返回。
    """
    grams = extract_ngrams(title, min_len=2, max_len=6)
    # 补充专用词
    for kw in EXTRA_KEYWORDS:
        if kw in (title or ""):
            grams.append(kw)
    # 去重
    seen = set()
    result = []
    for g in grams:
        if g not in seen:
            seen.add(g)
            result.append(g)
    return result


def parse_reads_value(reads_str: str) -> float:
    """将 '15.2万' 转为数值。"""
    if not reads_str or reads_str == "未知":
        return 0
    s = reads_str.strip().replace(",", "")
    try:
        if "万" in s:
            return float(s.replace("万", "")) * 10000
        if "亿" in s:
            return float(s.replace("亿", "")) * 100000000
        return float(s)
    except ValueError:
        return 0


def build_title_keyword_analysis(output: dict) -> dict:
    """
    分析所有上榜书名中的关键词，统计：
    - 出现频次（多少本上榜书名含此词）
    - 平均阅读量（含此词的书的平均在读）
    - 涉及分类
    - 频道分布

    使用自动 n-gram 提取，不依赖固定词表。
    过滤掉过于宽泛的词（出现在 >50% 书名中的词无意义）。
    """
    total_books = sum(len(c.get("books", [])) for c in output.get("categories", []))
    keyword_map = {}  # kw -> {count, total_reads, categories, channels, books}

    for cat in output.get("categories", []):
        cat_name = cat.get("name", "")
        channel = cat.get("channel", "female")
        for book in cat.get("books", []):
            title = book.get("title", "")
            reads = parse_reads_value(book.get("reads", ""))
            hits = extract_title_keywords(title)
            # 用集合去重（同一书名中多次出现只算一次）
            for kw in set(hits):
                if kw not in keyword_map:
                    keyword_map[kw] = {
                        "keyword": kw,
                        "count": 0,
                        "total_reads": 0,
                        "max_reads": 0,
                        "categories": set(),
                        "channels": set(),
                        "sample_books": [],
                    }
                entry = keyword_map[kw]
                entry["count"] += 1
                entry["total_reads"] += reads
                if reads > entry["max_reads"]:
                    entry["max_reads"] = reads
                entry["categories"].add(cat_name)
                entry["channels"].add(channel)
                if len(entry["sample_books"]) < 5:
                    entry["sample_books"].append({
                        "title": title,
                        "reads": book.get("reads", "未知"),
                        "category": cat_name,
                        "channel": channel,
                    })

    # 转成列表，过滤掉过于宽泛的词（出现在 >50% 书名中）
    # 和只出现1次的词（统计意义不大）
    threshold = total_books * 0.5
    result = []
    for kw, entry in keyword_map.items():
        if entry["count"] < 2:
            continue
        if entry["count"] > threshold and len(kw) <= 2:
            continue  # 2字词出现在超过一半的书名里，太宽泛
        avg_reads = entry["total_reads"] / entry["count"] if entry["count"] else 0
        result.append({
            "keyword": kw,
            "count": entry["count"],
            "avg_reads": round(avg_reads),
            "max_reads": entry["max_reads"],
            "category_count": len(entry["categories"]),
            "channels": sorted(entry["channels"]),
            "categories": sorted(entry["categories"]),
            "sample_books": entry["sample_books"],
        })

    # 去重子串：如果一个短词和一个长词出现频次完全相同，
    # 说明短词只是长词的子串，删除短词
    kw_by_count = {}
    for r in result:
        kw_by_count.setdefault(r["count"], []).append(r)

    to_remove = set()
    for r in result:
        for longer in result:
            if longer["keyword"] == r["keyword"]:
                continue
            if longer["count"] == r["count"] and r["keyword"] in longer["keyword"] and len(r["keyword"]) < len(longer["keyword"]):
                # r 是 longer 的子串，且频次相同 → r 只是 longer 的一部分
                to_remove.add(r["keyword"])
                break

    result = [r for r in result if r["keyword"] not in to_remove]

    # 按出现频次排序
    result.sort(key=lambda x: (x["count"], x["avg_reads"]), reverse=True)

    # 按频道分组
    female_kws = [r for r in result if "female" in r["channels"]]
    male_kws = [r for r in result if "male" in r["channels"]]

    return {
        "date": output.get("date", ""),
        "total_books": total_books,
        "total_keywords": len(result),
        "all_keywords": result,
        "female_keywords": sorted(female_kws, key=lambda x: (x["count"], x["avg_reads"]), reverse=True),
        "male_keywords": sorted(male_kws, key=lambda x: (x["count"], x["avg_reads"]), reverse=True),
    }


# ============================================================
# 蓝海探测器
# ============================================================

# 题材标签池（从简介中提取）
BLUEOCEAN_TAGS = [
    # 男频
    "系统流", "无敌流", "升级流", "签到流", "模拟器", "诸天", "洪荒",
    "修仙", "炼丹", "炼器", "御兽", "武道", "剑修", "体修", "血脉",
    "赘婿", "战神", "兵王", "神医", "特种兵", "鉴宝", "盗墓",
    "都市异能", "灵气复苏", "诡异", "规则怪谈",
    "扮猪吃虎", "杀伐果断", "苟道", "横推", "无敌", "签到",
    "领主", "种田", "基建", "经营", "公会", "副本",
    "末日", "废土", "天灾", "囤货", "求生",
    "抗战", "谍战", "历史", "架空历史", "争霸",
    "动漫", "同人", "衍生",
    # 女频
    "重生", "穿越", "快穿", "穿书", "空间", "团宠", "萌宝",
    "女配", "炮灰", "反派", "权臣", "宅斗", "宫斗", "和离",
    "替嫁", "逃荒", "种田", "美食", "经商",
    "年代", "七零", "八零", "军婚", "豪门", "总裁",
    "真假千金", "先婚后爱", "追妻", "追夫",
    "甜宠", "双洁", "强制爱", "无CP",
    "星际", "玄学", "无限流", "悬疑",
    "直播", "综艺", "娱乐圈", "校园", "暗恋", "青梅竹马",
    "民国", "兽世", "远古", "基建",
    "病娇", "偏执", "腹黑", "傲娇", "清冷",
    "万人迷", "大佬", "全息", "大女主", "群像",
]

def build_blueocean_analysis(output: dict) -> dict:
    """
    蓝海探测器：对每个分类，统计题材词密度。
    - 红海：该词在该分类出现频率 >= 40%（扎堆）
    - 蓝海：该词在该分类出现频率 <= 15% 但 > 0（有空间）
    - 未出现：该分类完全没有
    """
    categories_analysis = []

    for cat in output.get("categories", []):
        cat_name = cat.get("name", "")
        channel = cat.get("channel", "female")
        books = cat.get("books", [])
        total_books = len(books)
        if total_books == 0:
            continue

        # 统计每个标签在这个分类中的出现次数
        tag_stats = []
        for tag in BLUEOCEAN_TAGS:
            count = 0
            total_reads = 0
            sample_titles = []
            for book in books:
                # 在书名+简介中搜索
                text = f"{book.get('title', '')} {book.get('intro', '')}"
                if tag in text:
                    count += 1
                    total_reads += parse_reads_value(book.get("reads", ""))
                    if len(sample_titles) < 3:
                        sample_titles.append(book.get("title", ""))

            if count == 0:
                continue

            density = count / total_books
            avg_reads = total_reads / count if count else 0

            if density >= 0.4:
                level = "red"  # 红海：扎堆
            elif density <= 0.15:
                level = "blue"  # 蓝海：有空间
            else:
                level = "normal"  # 正常竞争

            tag_stats.append({
                "tag": tag,
                "count": count,
                "density": round(density, 2),
                "level": level,
                "avg_reads": round(avg_reads),
                "sample_titles": sample_titles,
            })

        # 排序：蓝海优先，然后按阅读量
        tag_stats.sort(key=lambda x: (
            0 if x["level"] == "blue" else (1 if x["level"] == "normal" else 2),
            -x["avg_reads"],
        ))

        blue_tags = [t for t in tag_stats if t["level"] == "blue"]
        red_tags = [t for t in tag_stats if t["level"] == "red"]

        categories_analysis.append({
            "name": cat_name,
            "channel": channel,
            "total_books": total_books,
            "blue_count": len(blue_tags),
            "red_count": len(red_tags),
            "tags": tag_stats,
        })

    return {
        "date": output.get("date", ""),
        "categories": categories_analysis,
    }


# ============================================================
# 新上榜开局分析
# ============================================================

def build_opening_analysis(output: dict) -> dict:
    """
    收集所有新上榜书籍的开局信息，供 AI 分析。
    规则兜底：按书名+简介提取关键词。
    """
    openings = []
    for cat in output.get("categories", []):
        cat_name = cat.get("name", "")
        channel = cat.get("channel", "female")
        trend = cat.get("trend", {})
        new_books = trend.get("new_books", [])

        # 建立书名->书的索引
        book_map = {}
        for book in cat.get("books", []):
            book_map[book.get("title", "")] = book

        for title in new_books:
            book = book_map.get(title, {})
            openings.append({
                "title": title,
                "category": cat_name,
                "channel": channel,
                "author": book.get("author", "未知"),
                "reads": book.get("reads", "未知"),
                "intro": (book.get("intro", "") or "")[:300],
                "url": book.get("url", ""),
            })

    # 按频道分组
    female_openings = [o for o in openings if o["channel"] == "female"]
    male_openings = [o for o in openings if o["channel"] == "male"]

    return {
        "date": output.get("date", ""),
        "total_new": len(openings),
        "female_count": len(female_openings),
        "male_count": len(male_openings),
        "female_openings": female_openings,
        "male_openings": male_openings,
        "all_openings": openings,
        "ai_analysis": "",  # 由 AI 填充
    }


def build_opening_ai_prompt(payload: dict) -> str:
    """构建新上榜开局分析的 AI prompt（仅男频）。"""
    sections = []
    items = payload.get("male_openings", [])
    if not items:
        return "今日无男频新上榜作品。"
    # 取前 15 本，简介截断到 120 字
    for item in items[:15]:
        intro = (item.get("intro", "") or "")[:120]
        sections.append(
            f"《{item['title']}》（{item['category']}）在读{item['reads']}\n{intro}"
        )

    all_text = "\n\n".join(sections)

    return f"""你是一位网文开书顾问，专注于男频小说。请根据以下男频新上榜作品的书名和简介，分析当前什么样的开局模式更容易上分。

## 今日男频新上榜作品（节选）

{all_text}

## 输出要求（Markdown 格式）

**🎯 爆款开局模式**
总结男频新上榜书的开局共性：什么金手指类型、什么人设、什么开局场景。点明 2-3 个高频模式。

**💰 书名关键词红利**
分析书名中哪些关键词反复出现在上榜书中，哪些可能对搜索和点击有加成。

**🌊 蓝海方向建议**
指出 2-3 个当前竞争较小但已有上榜书验证的题材方向，适合新作者切入。

**⚠️ 过热预警**
指出哪些开局模式已经过度扎堆，新人入局风险较高。

每个板块 2-3 句话，总字数 400 字以内。语言简洁专业，像行业快报。"""


def enrich_opening_analysis_with_ai(payload: dict, api_key: str,
                                   base_url: str, model: str) -> dict:
    """用 AI 生成新上榜开局分析。"""
    if not payload.get("all_openings"):
        payload["ai_analysis"] = "今日无新上榜作品。"
        return payload

    try:
        from openai import OpenAI
    except ImportError:
        print("⚠️  openai 库未安装，跳过开局分析 AI。")
        payload["ai_analysis"] = ""
        return payload

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_opening_ai_prompt(payload)}],
            max_tokens=1000,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if content and content.strip():
            payload["ai_analysis"] = content.strip()
            print("✅ 新上榜开局 AI 分析已生成")
        else:
            payload["ai_analysis"] = ""
    except Exception as e:
        print(f"⚠️  新上榜开局 AI 分析失败: {e}")
        payload["ai_analysis"] = ""

    return payload


# ============================================================
# AI 友好资产：llms.txt / daily report / schema / overview
# ============================================================

def format_reads_str(value) -> str:
    """把数字阅读量格式化成 AI 易读的字符串（12345 -> 1.2万）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v >= 10000:
        return f"{v/10000:.1f}万"
    return str(int(v)) if v == int(v) else str(v)


def build_ai_assets(output: dict, market_payload: dict, opening_payload: dict,
                    keyword_payload: dict, blueocean_payload: dict,
                    trends_dir: str, data_dir: str, api_dir: str,
                    base_dir: str, trends: dict, prev_date: str) -> str:
    """生成一组面向 LLM/其他 AI 的高可读资产：
    - data/ai/daily-report.md   今日 Markdown 日报（全文本，AI 直接读）
    - data/ai/daily-report.json 今日结构化日报
    - data/ai/schema.md         数据字段字典（教 AI 读懂所有 JSON）
    - llms.txt                  站点根目录的 LLM 发现入口（llmstxt.org 标准）
    - llms-full.txt             完整内容快照
    - api/ai/overview.json      数据资源索引（端点 + 更新时间 + 用途）
    """
    date_str = output.get("date", "")
    ai_dir = os.path.join(data_dir, "ai")
    os.makedirs(ai_dir, exist_ok=True)

    # ---------- 1. Markdown 日报 ----------
    md_lines = []
    md_lines.append(f"# 番茄新书榜日报 · {date_str}")
    md_lines.append(f"对比 {prev_date}，数据源：番茄小说男频+女频新书榜\n")

    # 全站热点摘要
    md_lines.append("## 一、全站热点（AI 总结/规则统计）")
    if market_payload and market_payload.get("periods"):
        for period_key, period in market_payload["periods"].items():
            if isinstance(period, dict) and period.get("summary"):
                md_lines.append(f"### 周期 {period_key}")
                md_lines.append(period["summary"])
                md_lines.append("")
    md_lines.append("")

    # 各分类趋势
    md_lines.append("## 二、分类趋势对比")
    for cat in output.get("categories", []):
        name = cat.get("name", "")
        channel = cat.get("channel", "")
        trend = cat.get("trend", {}) or {}
        summary = trend.get("summary", "")
        new_count = trend.get("new_count", 0)
        dropped_count = trend.get("dropped_count", 0)
        new_books = trend.get("new_books", []) or []
        risers = trend.get("top_risers", []) or []
        reads = trend.get("reads_growth", []) or []

        md_lines.append(f"### {channel}·{name}")
        if summary:
            md_lines.append(f"**摘要：** {summary}")
        md_lines.append(f"- 新上榜 {new_count} 本，掉榜 {dropped_count} 本")
        if new_books:
            md_lines.append(f"- 新上榜作品：{'；'.join(new_books[:8])}")
        if risers:
            riser_text = "；".join(f"{r.get('title','')}（{r.get('change','')}）" for r in risers[:5])
            md_lines.append(f"- 排名上升：{riser_text}")
        if reads:
            reads_top = sorted(reads, key=lambda r: parse_reads_value(r.get('growth', '0')), reverse=True)[:5]
            reads_text = "；".join(f"{r.get('title','')}（+{r.get('growth','')}）" for r in reads_top)
            md_lines.append(f"- 阅读增长：{reads_text}")
        md_lines.append("")

    # 关键词红利
    md_lines.append("## 三、书名关键词红利（男频）")
    male_kws = (keyword_payload or {}).get("male_keywords", []) or []
    if male_kws:
        for kw in male_kws[:20]:
            samples = kw.get("sample_books", []) or []
            sample_text = "、".join(
                (s.get("title", "") if isinstance(s, dict) else str(s)) for s in samples
            )[:100]
            md_lines.append(f"- **{kw.get('keyword','')}**：{kw.get('count',0)} 本，均读 {format_reads_str(kw.get('avg_reads', 0))}（示例：{sample_text}）")
    else:
        md_lines.append("- 暂无数据")
    md_lines.append("")

    # 蓝海探测
    md_lines.append("## 四、蓝海方向（题材密度分析）")
    if blueocean_payload and blueocean_payload.get("categories"):
        male_bo = [c for c in blueocean_payload["categories"] if c.get("channel") == "male"]
        for cat in male_bo[:10]:
            blue_tags = [t for t in (cat.get("tags") or []) if t.get("level") == "blue"]
            if blue_tags:
                tags_text = "、".join(t.get("tag", "") for t in blue_tags[:6])
                md_lines.append(f"- {cat.get('name','')}：蓝海题材 {tags_text}")
    md_lines.append("")

    # 开局分析（AI）
    md_lines.append("## 五、新上榜开局分析")
    ai_text = (opening_payload or {}).get("ai_analysis", "") or ""
    if ai_text:
        md_lines.append(ai_text)
    else:
        md_lines.append("- 暂无 AI 分析")
    md_lines.append("")

    # 男频新上榜 Top 30
    md_lines.append("## 六、男频新上榜 Top 30")
    male_cats = [c for c in output.get("categories", []) if c.get("channel") == "male"]
    seen_urls = set()
    top_books = []
    for cat in male_cats:
        for b in (cat.get("books") or []):
            if b.get("url") in seen_urls:
                continue
            seen_urls.add(b.get("url"))
            top_books.append({"title": b.get("title", ""), "reads": b.get("reads", ""), "cat": cat.get("name", "")})
    top_books.sort(key=lambda b: parse_reads_value(b.get("reads", "0")), reverse=True)
    for i, b in enumerate(top_books[:30], 1):
        md_lines.append(f"{i}. 《{b['title']}》[{b['cat']}] 在读 {b['reads']}")

    daily_md = "\n".join(md_lines)
    daily_md_path = os.path.join(ai_dir, "daily-report.md")
    with open(daily_md_path, "w", encoding="utf-8") as f:
        f.write(daily_md)

    # ---------- 2. 结构化日报 JSON ----------
    male_bo = []
    if blueocean_payload and blueocean_payload.get("categories"):
        male_bo = [c for c in blueocean_payload["categories"] if c.get("channel") == "male"]
    daily_json = {
        "date": date_str,
        "prev_date": prev_date,
        "market": market_payload,
        "categories": output.get("categories", []),
        "title_keywords": (keyword_payload or {}).get("male_keywords", []),
        "blueocean": male_bo,
        "opening_ai": ai_text,
    }
    daily_json_path = os.path.join(ai_dir, "daily-report.json")
    with open(daily_json_path, "w", encoding="utf-8") as f:
        json.dump(daily_json, f, ensure_ascii=False, indent=2)

    # ---------- 3. Schema 数据字典 ----------
    schema_lines = [
        "# 番茄新书榜 · 数据字段字典（Schema）",
        "",
        "这是本站所有数据文件的字段说明，供 AI 解析数据时参考。",
        "",
        "## data/latest_ranks.json（主数据）",
        "```",
        "{",
        '  "date": "2026-08-24",            # 榜单日期 YYYY-MM-DD',
        '  "prev_date": "2026-08-23",       # 对比日期',
        '  "categories": [                  # 全部分类（男频+女频）',
        "    {",
        '      "name": "西方奇幻",           # 分类名',
        '      "channel": "male",           # 频道: male=男频, female=女频',
        '      "trend": {                   # 与对比日期相比的趋势',
        '        "new_count": 3,            # 新上榜数量',
        '        "dropped_count": 2,        # 掉榜数量',
        '        "new_books": ["书名1", ...], # 新上榜书名',
        '        "top_risers": [{"title": "...", "change": "+5"}],  # 排名上升',
        '        "top_fallers": [...],      # 排名下降',
        '        "reads_growth": [{"title": "...", "growth": "+3.2万"}],  # 阅读量增长',
        '        "summary": "AI 生成的趋势摘要文本"',
        "      },",
        '      "books": [                   # 该分类 Top 30 书籍',
        "        {",
        '          "title": "书名",',
        '          "author": "作者",',
        '          "reads": "17.9万",       # 在读人数（字符串，万=万）',
        '          "intro": "简介文本",',
        '          "cover": "封面 URL",',
        '          "url": "https://fanqienovel.com/page/xxx"  # 番茄书页链接',
        "        }",
        "      ]",
        "    }",
        "  ]",
        "}",
        "```",
        "",
        "## data/trends/YYYY-MM-DD.json（历史趋势归档）",
        "键为 `channel:分类名`（如 `male:西方奇幻`），值是上述 trend 结构。",
        "",
        "## data/market_summary.json（全站热点）",
        "```",
        "{",
        '  "periods": {',
        '    "7":  { "summary": "近7日热点文本", "source": "ai"|"rule", "period": "7" },',
        '    "14": {...}, "30": {...}, "all": {...}',
        "  }",
        "}",
        "```",
        "",
        "## data/title_keywords.json（书名关键词红利）",
        "```",
        "{",
        '  "date": "...",',
        '  "male_keywords": [',
        "    {",
        '      "keyword": "系统",           # 关键词（自动 n-gram 提取）',
        '      "count": 35,                 # 命中本数',
        '      "avg_reads": 120000,         # 命中书籍平均在读',
        '      "max_reads": 800000,         # 最高在读',
        '      "sample_books": ["书名1", ...]',
        "    }",
        "  ]",
        "}",
        "```",
        "",
        "## data/blueocean.json（蓝海探测）",
        "```",
        "{",
        '  "date": "...",',
        '  "categories": [',
        "    {",
        '      "name": "分类名", "channel": "male", "total_books": 20,',
        '      "tags": [',
        "        {",
        '          "tag": "题材词", "count": 3,',
        '          "density": 0.15,          # 占比 15%',
        '          "level": "blue"|"red"|"normal",  # blue=蓝海(稀疏) red=红海(扎堆)',
        '          "avg_reads": 0, "sample_titles": [...]',
        "        }",
        "      ]",
        "    }",
        "  ]",
        "}",
        "```",
        "",
        "## data/opening_analysis.json（开局分析）",
        "```",
        "{",
        '  "date": "...",',
        '  "male_openings": [ {"title": "...", "category": "...", "author": "...", "reads": "...", "intro": "...", "url": "..."} ],',
        '  "ai_analysis": "AI 生成的开局模式分析 Markdown"',
        "}",
        "```",
        "",
        "## 阅读量字段说明",
        "`reads` 是字符串，可能为 `17.9万`、`7962`、`未知`。解析：包含 `万` 时乘以 10000，`未知` 视为 0。",
        "",
        "## 频道标识",
        "- `male` = 男频，`female` = 女频",
        "- 男频与女频可能存在同名分类（如 科幻末世），必须用 `channel` 字段区分。",
    ]
    schema_path = os.path.join(ai_dir, "schema.md")
    with open(schema_path, "w", encoding="utf-8") as f:
        f.write("\n".join(schema_lines))

    # ---------- 4. llms.txt（根目录，llmstxt.org 标准） ----------
    llms_lines = [
        "# 番茄新书榜（Fanqie Rank Tracker）",
        "",
        "> 每日自动追踪番茄小说男频/女频新书榜，AI 生成趋势分析。数据每天北京时间 08:15 自动更新。",
        "",
        "## 给 AI 的建议",
        "如需最新数据和完整字段说明，按顺序读取：",
        "1. `data/ai/daily-report.md` — 今日完整日报（Markdown，含趋势摘要、蓝海、关键词、开局分析、Top30）",
        "2. `data/ai/schema.md` — 数据字段字典（教 AI 解析 JSON）",
        "3. `data/ai/daily-report.json` — 今日结构化数据",
        "4. `data/latest_ranks.json` — 全量分类+书籍+趋势数据",
        "5. 历史趋势：`data/trends/YYYY-MM-DD.json`",
        "",
        "## 数据端点",
        f"- 资源索引: `api/ai/overview.json`（{date_str}）",
        f"- 日报(Markdown): `data/ai/daily-report.md`（{date_str}）",
        f"- 日报(JSON): `data/ai/daily-report.json`（{date_str}）",
        f"- 字段字典: `data/ai/schema.md`",
        f"- 全量数据: `api/lastest/all.json`（{date_str}）",
        f"- 分类索引: `api/lastest.json`",
        f"- 单分类: `api/lastest/<分类名>.json`",
        f"- 主数据: `data/latest_ranks.json`（{date_str}）",
        "- 历史日期: `data/dates.json`",
        "",
        "## 页面",
        "- 首页: `/`（书单看板）",
        "- 风向标: `/trend.html`",
        "- 关键词红利: `/keyword.html`",
        "- 蓝海探测: `/blueocean.html`",
        "- 开局分析: `/opening.html`",
    ]
    llms_path = os.path.join(base_dir, "llms.txt")
    with open(llms_path, "w", encoding="utf-8") as f:
        f.write("\n".join(llms_lines))

    # ---------- 5. llms-full.txt（完整快照） ----------
    llms_full = "\n".join([
        "# 番茄新书榜 · 完整数据快照",
        "",
        f"> 更新时间：{date_str}。完整日报、分类趋势、关键词、蓝海、开局分析、Top30。",
        "",
        daily_md,
        "",
        "---",
        "",
        "## 数据字典（完整版）",
        "",
        "\n".join(schema_lines),
    ])
    llms_full_path = os.path.join(base_dir, "llms-full.txt")
    with open(llms_full_path, "w", encoding="utf-8") as f:
        f.write(llms_full)

    # ---------- 6. api/ai/overview.json（资源索引） ----------
    overview = {
        "site": "番茄新书榜 Fanqie Rank Tracker",
        "description": "每日自动追踪番茄小说男频/女频新书榜，AI 趋势分析。",
        "updated": date_str,
        "recommended_reading_order": [
            "data/ai/daily-report.md",
            "data/ai/schema.md",
            "data/ai/daily-report.json",
            "data/latest_ranks.json",
        ],
        "endpoints": [
            {"path": "data/ai/daily-report.md", "format": "markdown", "description": "今日完整日报", "date": date_str},
            {"path": "data/ai/daily-report.json", "format": "json", "description": "今日结构化日报", "date": date_str},
            {"path": "data/ai/schema.md", "format": "markdown", "description": "数据字段字典"},
            {"path": "data/latest_ranks.json", "format": "json", "description": "全量分类+书籍+趋势", "date": date_str},
            {"path": "api/lastest/all.json", "format": "json", "description": "全量接口", "date": date_str},
            {"path": "api/lastest.json", "format": "json", "description": "分类索引"},
            {"path": "data/trends/YYYY-MM-DD.json", "format": "json", "description": "历史趋势归档，键=channel:分类名"},
            {"path": "data/market_summary.json", "format": "json", "description": "全站热点周期总结"},
            {"path": "data/title_keywords.json", "format": "json", "description": "书名关键词红利分析"},
            {"path": "data/blueocean.json", "format": "json", "description": "蓝海题材探测"},
            {"path": "data/opening_analysis.json", "format": "json", "description": "新上榜开局分析"},
            {"path": "data/dates.json", "format": "json", "description": "历史日期列表"},
        ],
        "notes": [
            "reads 是字符串，含'万'时*10000，'未知'为0",
            "同名分类跨频道（如科幻末世），必须用 channel 字段区分 male/female",
        ],
    }
    overview_dir = os.path.join(data_dir, "..", "api", "ai")
    overview_dir = os.path.normpath(overview_dir)
    os.makedirs(overview_dir, exist_ok=True)
    overview_path = os.path.join(overview_dir, "overview.json")
    with open(overview_path, "w", encoding="utf-8") as f:
        json.dump(overview, f, ensure_ascii=False, indent=2)

    return f"llms.txt, llms-full.txt, data/ai/ (3 files), api/ai/overview.json"


if __name__ == "__main__":
    main()
