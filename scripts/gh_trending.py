#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Trending 每日抓取 + 与上一份快照对比, 输出 Markdown 简报.
用法: python gh_trending.py [--lang python] [--since daily]
产物: snapshots/YYYY-MM-DD[-lang].json, reports/YYYY-MM-DD[-lang].md
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from lxml import html as LH

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(BASE, "snapshots")
REPORTS = os.path.join(BASE, "reports")
CACHE = os.path.join(BASE, "repos_cache.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TZ = dt.timezone(dt.timedelta(hours=8))

try:   # Windows 控制台默认 GBK，统一输出 UTF-8 免得日志乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def fetch(url, headers=None, timeout=60, retries=3):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError:      # 4xx/5xx 不重试（403 就是限额，重试只会更慢）
            raise
        except Exception as e:              # 网络抖动才重试
            last = e
            if i < retries - 1:
                time.sleep(2 + 3 * i)
    raise last


def load_token():
    """token 来源优先级：环境变量 > 项目内 .github_token > 用户目录 .github_token。"""
    tok = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if tok:
        return tok, "env"
    for p in (os.path.join(BASE, ".github_token"),
              os.path.join(os.path.expanduser("~"), ".github_token")):
        try:
            with open(p, encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t, p
        except OSError:
            continue
    return "", ""


def gh_headers():
    h = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    tok, _ = load_token()
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def check_auth():
    """验证 token 是否生效并打印限额。"""
    tok, src = load_token()
    if not tok:
        print("未配置 token：core 限额 60/h、search 10/min（当前走匿名）")
    else:
        print(f"已找到 token（来源：{src}，前缀 {tok[:4]}…，长度 {len(tok)}）")
    try:
        d = json.loads(fetch("https://api.github.com/rate_limit", gh_headers(), timeout=20))
        core = d["resources"]["core"]
        search = d["resources"]["search"]
        print(f"core:   {core['remaining']}/{core['limit']}  "
              f"reset {dt.datetime.fromtimestamp(core['reset'], TZ).strftime('%H:%M')} (UTC+8)")
        print(f"search: {search['remaining']}/{search['limit']}")
        if core["limit"] >= 5000:
            print("[OK] token 生效（5000/h 档）")
        elif tok:
            print("[WARN] 有 token 但限额仍是 60/h：token 可能无效/过期/被撤销")
        else:
            print("[INFO] 匿名档，够日常但首次跑或换榜日会吃紧")
    except Exception as e:
        print("查限额失败：", e)
    if tok:
        try:
            u = json.loads(fetch("https://api.github.com/user", gh_headers(), timeout=20))
            print("token 身份：", u.get("login"), "|", u.get("type"))
        except Exception as e:
            print("读取身份失败（token 可能无效）：", e)


def num(txt):
    if not txt:
        return None
    d = re.sub(r"[^\d]", "", txt)
    return int(d) if d else None


def parse(doc):
    out = []
    for art in doc.xpath('//article[contains(concat(" ",normalize-space(@class)," ")," Box-row ")]'):
        name = (art.xpath('.//h2//a/@href') or [""])[0].strip("/")
        if not name or name.count("/") != 1:
            continue
        desc = " ".join((art.xpath('.//p[contains(@class,"color-fg-muted")]//text()') or [""])).strip()
        lang = (art.xpath('.//span[@itemprop="programmingLanguage"]//text()') or [None])[0]
        stars = num(" ".join(art.xpath('.//a[contains(@href,"/stargazers")]//text()')))
        forks = num(" ".join(art.xpath('.//a[contains(@href,"/forks")]//text()')))
        today_raw = " ".join(art.xpath('.//span[contains(@class,"float-sm-right")]//text()')).strip()
        today = num(today_raw)
        out.append({
            "repo": name,
            "url": "https://github.com/" + name,
            "desc": desc,
            "lang": lang,
            "stars": stars,
            "forks": forks,
            "today": today,
        })
    return out


def load_json(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


FOCUS_PATTERNS = {
    "vibecoding": [
        "vibe coding", "vibecoding", "vibe-code", "vibe code", "prompt to app",
        "prompt-to-app", "text to app", "text-to-app", "no-code", "low-code",
        "app builder", "describe your app", "generate an app", "generate full-stack",
        "from a prompt", "turn your idea into",
    ],
    "agent-plugin": [
        "skill", "skills", "plugin", "plugins", "mcp", "subagent", "sub-agent",
        "claude code", "claude-code", "cursor", "codex", "copilot", "gemini cli",
        "windsurf", "agent extension", "tool use", "context protocol",
    ],
}

# README 里预示「坑」的线索行（只留强信号，避免把目录/路线图当成坑）
PITFALL_VERSION = "3"
PITFALL_RE = re.compile(
    r"(limitation|caveat|known issue|workaround|not supported|no support|"
    r"experimental|alpha|beta|wip|deprecated|broken|only works|currently only|"
    r"prerequisite|require[sd] (node|python|docker|api key|token|claude|cursor|access)|"
    r"does not work|doesn't work|not recommended|breaking change)",
    re.I,
)


def fetch_readme(repo, branch="main"):
    """抓 README。走 api.github.com/repos/{repo}/readme（raw.githubusercontent 在本机被墙）。
    返回 (text, source_url)；失败返回 ("", "")。"""
    try:
        d = json.loads(fetch("https://api.github.com/repos/" + repo + "/readme",
                             gh_headers(), timeout=25))
        content = d.get("content") or ""
        if d.get("encoding") == "base64" and content:
            return base64.b64decode(content).decode("utf-8", "replace"), (d.get("html_url") or "")
    except Exception as e:
        print("readme fail", repo, e, file=sys.stderr)
    return "", ""


def readme_digest(text, limit=2600):
    """压成：开头摘要 + 命中的坑信号行。"""
    if not text:
        return "", []
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)      # 去图片
    body = re.sub(r"<[^>]+>", " ", body)                    # 去 HTML
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    notes = []
    for ln in body.splitlines():
        s = ln.strip(" -#*>|\t")
        if 3 < len(s) < 180 and PITFALL_RE.search(s):
            notes.append(s)
        if len(notes) >= 4:
            break
    return body[:limit], notes


def enrich(items, want_readme=True):
    """补齐创建时间/许可证/issue 数/README 摘要, 带本地缓存避免重复调用 API."""
    cache = load_json(CACHE, {})
    changed = False
    now_ts = dt.datetime.now(TZ).timestamp()
    api_dead = False        # 限额耗尽后就别再调了
    for it in items:
        repo = it["repo"]
        c = cache.get(repo)
        if (not c or not c.get("created_at") or "open_issues" not in c) and not api_dead:
            try:
                d = json.loads(fetch("https://api.github.com/repos/" + repo,
                                     {"Accept": "application/vnd.github+json"}))
                c = {
                    "created_at": d.get("created_at"),
                    "pushed_at": d.get("pushed_at"),
                    "topics": (d.get("topics") or [])[:8],
                    "archived": d.get("archived", False),
                    "license": ((d.get("license") or {}).get("spdx_id") or ""),
                    "open_issues": d.get("open_issues_count"),
                    "default_branch": d.get("default_branch") or "main",
                    "homepage": d.get("homepage") or "",
                    "full_desc": d.get("description") or "",
                    "size_kb": d.get("size"),
                }
                cache[repo] = c
                changed = True
                print("api ok", repo, file=sys.stderr)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    api_dead = True
                    print(f"api 限额耗尽（HTTP {e.code}），剩下的仓库只保留页面数据", file=sys.stderr)
                else:
                    print("api fail", repo, e, file=sys.stderr)
            except Exception as e:
                print("api fail", repo, e, file=sys.stderr)
        if c is None:
            c = cache.setdefault(repo, {"created_at": None})
            changed = True

        for k in ("created_at", "topics", "license", "archived", "open_issues",
                  "pushed_at", "default_branch", "homepage", "full_desc", "size_kb"):
            it[k] = c.get(k)
        it["topics"] = it["topics"] or []

        hay = " ".join([str(it.get("full_desc") or ""), it.get("desc") or "",
                        " ".join(it["topics"]), repo]).lower()
        it["tags"] = [k for k, pats in FOCUS_PATTERNS.items() if any(p in hay for p in pats)]
        it["is_focus"] = bool(it["tags"])

        # README 摘要: 只看需要深评的（新项目 / vibecoding / agent 插件）
        need = want_readme and not api_dead and (it["is_focus"] or (age_days(it.get("created_at"), dt.datetime.now(TZ)) or 9999) <= 60)
        if need:
            stale = ((now_ts - (c.get("readme_ts") or 0)) > 3 * 86400
                     or c.get("readme_v") != PITFALL_VERSION)
            if stale:
                txt, src = fetch_readme(repo, it.get("default_branch") or "main")
                body, notes = readme_digest(txt)
                c["readme"] = body
                c["readme_notes"] = notes
                c["readme_src"] = src
                c["readme_ts"] = now_ts
                c["readme_v"] = PITFALL_VERSION
                cache[repo] = c
                changed = True
            it["readme"] = (c.get("readme") or "")[:2600]
            it["readme_notes"] = (c.get("readme_notes") or [])[:4]
            it["readme_src"] = c.get("readme_src") or ""
    if changed:
        save_json(CACHE, cache)
    return items


def age_days(created_at, now):
    if not created_at:
        return None
    try:
        c = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        return None
    return (now - c).days


def trending_via_search(now):
    """github.com 打不开时的降级方案：用 GitHub Search API 拼一个近似榜单。
    只覆盖 api.github.com（本机可用）。无「今日新增星」，today 记为 None。"""
    import urllib.parse as up
    d7 = (now - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (now - dt.timedelta(days=30)).strftime("%Y-%m-%d")
    d3 = (now - dt.timedelta(days=3)).strftime("%Y-%m-%d")
    queries = [
        f"created:>={d7} stars:>=30",
        f"created:>={d30} stars:>=200",
        f"pushed:>={d3} stars:>=3000",
    ]
    seen, out = set(), []
    for q in queries:
        u = ("https://api.github.com/search/repositories?q=" + up.quote(q)
             + "&sort=stars&order=desc&per_page=25")
        try:
            d = json.loads(fetch(u, gh_headers(), timeout=30))
        except Exception as e:
            print("search fallback fail:", q, e, file=sys.stderr)
            continue
        for r in d.get("items") or []:
            full = r.get("full_name")
            if not full or full in seen:
                continue
            seen.add(full)
            out.append({
                "repo": full,
                "url": r.get("html_url") or ("https://github.com/" + full),
                "desc": r.get("description") or "",
                "lang": r.get("language"),
                "stars": r.get("stargazers_count"),
                "forks": r.get("forks_count"),
                "today": None,
            })
        time.sleep(1.5)   # search API 10 次/分钟
    return out[:25]


RADAR_QUERIES = [
    ("vibecoding", '"vibe coding" created:>={d60} stars:>=20'),
    ("agent-plugin", '"agent skill" created:>={d90} stars:>=40'),
    ("agent-plugin", '"claude code" plugin created:>={d60} stars:>=30'),
]


def radar(now, exclude):
    """赛道雷达：Trending 之外的 vibecoding / agent 插件新项目（GitHub Search API）。"""
    import urllib.parse as up
    d60 = (now - dt.timedelta(days=60)).strftime("%Y-%m-%d")
    d90 = (now - dt.timedelta(days=90)).strftime("%Y-%m-%d")
    seen, out = set(exclude), []
    for tag, q in RADAR_QUERIES:
        u = ("https://api.github.com/search/repositories?q="
             + up.quote(q.format(d60=d60, d90=d90))
             + "&sort=stars&order=desc&per_page=8")
        try:
            d = json.loads(fetch(u, gh_headers(), timeout=30))
        except Exception as e:
            print("radar fail:", q, e, file=sys.stderr)
            continue
        for r in d.get("items") or []:
            full = r.get("full_name")
            if not full or full in seen:
                continue
            seen.add(full)
            out.append({
                "repo": full,
                "url": r.get("html_url") or ("https://github.com/" + full),
                "desc": r.get("description") or "",
                "lang": r.get("language"),
                "stars": r.get("stargazers_count"),
                "created_at": r.get("created_at"),
                "pushed_at": r.get("pushed_at"),
                "open_issues": r.get("open_issues_count"),
                "license": ((r.get("license") or {}).get("spdx_id") or ""),
                "tags": [tag],
            })
        time.sleep(1.5)
    return out[:10]


def previous_snapshot(today, tag, since):
    if not os.path.isdir(SNAP):
        return None
    cands = []
    for fn in os.listdir(SNAP):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})" + re.escape(tag) + r"\." + re.escape(since) + r"\.json$", fn)
        if m and m.group(1) < today:
            cands.append((m.group(1), os.path.join(SNAP, fn)))
    if not cands:
        return None
    cands.sort()
    p = cands[-1][1]
    obj = load_json(p, None)
    if obj:
        obj["_path"] = p
    return obj


def fmt_stars(n):
    if not n:
        return "-"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="")
    ap.add_argument("--since", default="daily")
    ap.add_argument("--no-api", action="store_true")
    ap.add_argument("--no-weekly", action="store_true")
    ap.add_argument("--no-readme", action="store_true")
    ap.add_argument("--no-fallback", action="store_true")
    ap.add_argument("--no-radar", action="store_true")
    ap.add_argument("--force-fallback", action="store_true")
    ap.add_argument("--from-snapshot", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--check-auth", action="store_true")
    args = ap.parse_args()

    if args.check_auth:
        check_auth()
        return 0

    tok, tok_src = load_token()
    if tok:
        print(f"token: 已加载（来源 {tok_src}）", file=sys.stderr)
    else:
        print("token: 未配置，走匿名限额（60/h）", file=sys.stderr)

    now = dt.datetime.now(TZ)
    today = args.date or now.strftime("%Y-%m-%d")
    url = "https://github.com/trending"
    if args.lang:
        url += "/" + args.lang
    url += f"?since={args.since}"

    usage = None
    if args.from_snapshot:
        snap = load_json(args.from_snapshot, {})
        items = snap.get("items") or []
        if not items:
            print("ERROR: --from-snapshot 里没有 items", file=sys.stderr)
            return 1
        today = snap.get("date") or today
        print(f"重建模式：从 {args.from_snapshot} 读 {len(items)} 个仓库", file=sys.stderr)
    else:
        try:
            if args.force_fallback:
                raise RuntimeError("--force-fallback")
            doc = LH.fromstring(fetch(url, timeout=30, retries=6))
            items = parse(doc)
        except Exception as e:
            print(f"WARN: 抓不到 trending 页面（{url}）：{e}", file=sys.stderr)
            if args.no_fallback:
                return 2
            print("降级：改用 GitHub Search API 近似榜单（无「今日⭐」）", file=sys.stderr)
            items = trending_via_search(now)
            usage = "search-fallback"
        if not items:
            print("ERROR: parsed 0 repos", file=sys.stderr)
            return 1
    if not args.no_api:
        enrich(items, want_readme=not args.no_readme)

    tag = f"-{args.lang}" if args.lang else ""
    snap_path = os.path.join(SNAP, f"{today}{tag}.{args.since}.json")
    if not args.from_snapshot:
        save_json(snap_path, {"date": today, "since": args.since, "source": usage or "trending",
                              "fetched_at": now.isoformat(), "items": items})
    else:
        save_json(snap_path, {"date": today, "since": args.since,
                              "source": (load_json(args.from_snapshot, {}) or {}).get("source") or "trending",
                              "fetched_at": now.isoformat(), "items": items})

    prev = previous_snapshot(today, tag, args.since)
    prev_rank = {}
    if prev:
        for i, it in enumerate(prev["items"], 1):
            prev_rank[it["repo"]] = i

    cur = {it["repo"] for it in items}
    new_repos = [it for it in items if prev and it["repo"] not in prev_rank]
    gone = [r for r in prev_rank if r not in cur] if prev else []

    # 与月榜交叉: 月榜里也有的 = 持续热; 月榜里没有 = 近期才起量(仅参考)
    month_repos = set()
    if args.since == "daily" and not args.no_weekly:
        murl = url.replace("since=daily", "since=monthly")
        try:
            month_repos = {it["repo"] for it in parse(LH.fromstring(fetch(murl)))}
        except Exception as e:
            print("monthly fetch fail:", e, file=sys.stderr)
    steady = [it for it in items if it["repo"] in month_repos]
    fresh = [it for it in items if month_repos and it["repo"] not in month_repos]

    radar_items = []
    if args.since == "daily" and not args.no_radar:
        radar_items = radar(now, {it["repo"] for it in items})

    # Markdown
    L = []
    title = "GitHub Trending 每日简报"
    L.append(f"# {title} · {today}（{args.since}{'/' + args.lang if args.lang else '，全站'}）")
    L.append("")
    L.append(f"抓取时间：{now.strftime('%Y-%m-%d %H:%M')} (UTC+8) ｜ 来源：<{url}>")
    L.append("")
    if usage == "search-fallback":
        L.append("> ⚠️ **降级数据**：github.com 今天连不上，本表由 GitHub Search API 近似生成（近期新项目 + 高星活跃项目），"
                 "不是官方 Trending，也**没有「今日新增星」**。网络恢复后会自动回到官方榜。")
        L.append("")
    if prev:
        L.append(f"对比基准：`{os.path.basename(prev['_path'])}`")
    else:
        L.append("对比基准：无历史快照（今天是基线，明日开始可标出「新上榜」）")
    L.append("")

    L.append("## 前十")
    L.append("")
    if len(items) < 10:
        L.append(f"> 今日榜单页面只返回 {len(items)} 个仓库，所以「前十」= 当前全部上榜。")
        L.append("")
    L.append("| # | 仓库 | 今日⭐ | 总⭐ | 语言 | 标签 | 简介 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, it in enumerate(items[:10], 1):
        moved = ""
        if prev:
            if it["repo"] not in prev_rank:
                moved = " 🆕"
            else:
                d = prev_rank[it["repo"]] - i
                if d > 0:
                    moved = f" ↑{d}"
                elif d < 0:
                    moved = f" ↓{-d}"
        desc = (it["desc"] or "").replace("|", "/")
        if len(desc) > 90:
            desc = desc[:88] + "…"
        tags = " ".join(f"`{t}`" for t in (it.get("tags") or [])) or "-"
        L.append(f"| {i} | [{it['repo']}]({it['url']}){moved} | +{it['today'] or '?'} | {fmt_stars(it['stars'])} | {it['lang'] or '-'} | {tags} | {desc} |")
    L.append("")

    # 重点盯: vibecoding / agent 插件技能
    focus = [it for it in items if it.get("is_focus")]
    if focus:
        L.append(f"## 重点盯（vibecoding / agent 插件技能，{len(focus)} 个）")
        L.append("")
        for it in focus:
            rank = items.index(it) + 1
            ad = age_days(it.get("created_at"), now)
            pd = age_days(it.get("pushed_at"), now) if it.get("pushed_at") else None
            meta = [f"#{rank}", " ".join(it.get("tags") or []),
                    f"+{it['today'] or '?'}/日", f"{fmt_stars(it['stars'])}⭐"]
            if it.get("open_issues") is not None:
                meta.append(f"open issues {it['open_issues']}")
            if pd is not None:
                meta.append(f"最后提交 {pd} 天前")
            if ad is not None:
                meta.append(f"仓库 {ad} 天")
            if it.get("archived"):
                meta.append("⚠️ 已归档")
            L.append(f"### [{it['repo']}]({it['url']})")
            L.append("")
            L.append(" · ".join(meta))
            L.append("")
            body = (it.get("readme") or "").replace("```", "'''")
            if body:
                L.append("```text")
                L.append(body[:1600])
                L.append("```")
                L.append("")
            if it.get("readme_notes"):
                L.append("**坑信号（README 原文）**：" + " ／ ".join(it["readme_notes"]))
                L.append("")

    if prev and new_repos:
        L.append(f"## 新上榜（对比 {os.path.basename(prev['_path'])}，{len(new_repos)} 个）")
        L.append("")
        for it in new_repos:
            rank = items.index(it) + 1
            desc = (it["desc"] or "").replace("\n", " ")
            if len(desc) > 110:
                desc = desc[:108] + "…"
            L.append(f"- **#{rank} [{it['repo']}]({it['url']})** +{it['today'] or '?'}/日 · {it['lang'] or '-'} · {desc}")
        L.append("")
    elif not prev:
        young = [(i + 1, it) for i, it in enumerate(items) if (age_days(it.get("created_at"), now) or 9999) <= 30]
        if young:
            L.append("## 值得注意的新项目（创建 ≤30 天，作为「新出现」的近似）")
            L.append("")
            for rank, it in young:
                ad = age_days(it.get("created_at"), now)
                L.append(f"- **#{rank} [{it['repo']}]({it['url']})** {ad} 天 · +{it['today'] or '?'}/日 · {it['lang'] or '-'} · {(it['desc'] or '')[:100]}")
            L.append("")

    if fresh:
        L.append(f"## 近期起量候选（日榜有 / 月榜无，{len(fresh)} 个）")
        L.append("")
        L.append("> 月榜只放 20 个，未出现只是「很可能」近期才冲上来，不是确定结论；从明天起用每日快照 diff 给出真正的 🆕。")
        L.append("")
        for it in fresh:
            rank = items.index(it) + 1
            ad = age_days(it.get("created_at"), now)
            agetxt = f"{ad} 天前创建" if ad is not None else "创建时间未知"
            L.append(f"- **#{rank} [{it['repo']}]({it['url']})** +{it['today'] or '?'}/日 · {it['lang'] or '-'} · {agetxt} · {(it['desc'] or '')[:110]}")
        L.append("")

    if steady:
        L.append(f"## 持续热（同时在月榜，{len(steady)} 个）")
        L.append("")
        for it in steady:
            rank = items.index(it) + 1
            L.append(f"- **#{rank} [{it['repo']}]({it['url']})** +{it['today'] or '?'}/日 · {it['lang'] or '-'} · {(it['desc'] or '')[:100]}")
        L.append("")

    if gone:
        L.append("## 跌出榜单")
        L.append("")
        for r in gone:
            L.append(f"- [{r}](https://github.com/{r})")
        L.append("")

    if radar_items:
        L.append(f"## 赛道雷达（Trending 之外的 vibecoding / agent 插件新项目，{len(radar_items)} 个）")
        L.append("")
        L.append("> 来自 GitHub Search API：近 60-90 天新建、按星排序，用来补 Trending 漏掉的赛道新品。")
        L.append("")
        for it in radar_items:
            ad = age_days(it.get("created_at"), now)
            pd = age_days(it.get("pushed_at"), now) if it.get("pushed_at") else None
            bits = [f"**[{it['repo']}]({it['url']})**", " ".join(it.get("tags") or [])]
            bits.append(f"{fmt_stars(it['stars'])}⭐")
            if ad is not None:
                bits.append(f"{ad} 天")
            if pd is not None:
                bits.append(f"最后提交 {pd} 天前")
            if it.get("open_issues") is not None:
                bits.append(f"issues {it['open_issues']}")
            L.append("- " + " · ".join(bits) + f" · {(it['desc'] or '')[:110]}")
        L.append("")

    L.append(f"## 完整榜（{len(items)} 个）")
    L.append("")
    for i, it in enumerate(items, 1):
        L.append(f"{i}. [{it['repo']}]({it['url']}) +{it['today'] or '?'} · {it['lang'] or '-'}")

    os.makedirs(REPORTS, exist_ok=True)
    rep = os.path.join(REPORTS, f"{today}{tag}.{args.since}.md")
    with open(rep, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
