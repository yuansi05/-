#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Trending 周报: 聚合最近 7 天快照.
用法: python weekly_report.py [--days 7]
产物: reports/week-YYYY-MM-DD.md
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(BASE, "snapshots")
REPORTS = os.path.join(BASE, "reports")
TZ = dt.timezone(dt.timedelta(hours=8))


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def fmt(n):
    if not n:
        return "-"
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    now = dt.datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    files = sorted(glob.glob(os.path.join(SNAP, "*.daily.json")))
    data = []
    for p in files:
        d = load(p)
        if d and d.get("items"):
            data.append(d)
    if not data:
        print("ERROR: 没有快照，先跑 gh_trending.py", file=sys.stderr)
        return 1

    cutoff = (now - dt.timedelta(days=args.days)).strftime("%Y-%m-%d")
    data = [d for d in data if d["date"] >= cutoff]
    data.sort(key=lambda d: d["date"])
    dates = [d["date"] for d in data]

    agg = {}
    for d in data:
        for rank, it in enumerate(d["items"], 1):
            r = agg.setdefault(it["repo"], {
                "repo": it["repo"], "url": it["url"], "desc": it.get("desc") or "",
                "lang": it.get("lang"), "tags": it.get("tags") or [],
                "days": [], "ranks": [], "today_sum": 0,
                "stars_first": None, "stars_last": None,
                "created_at": it.get("created_at"), "open_issues": it.get("open_issues"),
                "pushed_at": it.get("pushed_at"),
            })
            r["days"].append(d["date"])
            r["ranks"].append(rank)
            r["today_sum"] += it.get("today") or 0
            if r["stars_first"] is None:
                r["stars_first"] = it.get("stars")
            r["stars_last"] = it.get("stars")
            if it.get("tags"):
                r["tags"] = it["tags"]

    rows = list(agg.values())
    for r in rows:
        r["n"] = len(r["days"])
        r["best"] = min(r["ranks"])
        r["first"] = r["days"][0]
        r["last"] = r["days"][-1]
        r["delta"] = (r["stars_last"] - r["stars_first"]) if (r["stars_first"] and r["stars_last"]) else None
        r["focus"] = bool(r["tags"])

    L = []
    L.append(f"# GitHub Trending 周报 · {dates[0]} ~ {dates[-1]}")
    L.append("")
    L.append(f"生成时间：{now.strftime('%Y-%m-%d %H:%M')} (UTC+8) ｜ 样本：{len(dates)} 天（{', '.join(dates)}）")
    L.append("")
    if len(dates) < 5:
        L.append(f"> ⚠️ 本周只有 {len(dates)} 份快照，统计偏稀疏，看趋势即可。")
        L.append("")

    if len(dates) > 1:
        L.append("## 本周累计涨幅 Top 10（首末快照的总⭐差）")
        L.append("")
        ranked = sorted([r for r in rows if r["delta"]], key=lambda r: -r["delta"])[:10]
        L.append("| 仓库 | 本周+⭐ | 上榜 | 最高名次 | 语言 |")
        L.append("|---|---|---|---|---|")
        for r in ranked:
            L.append(f"| [{r['repo']}]({r['url']}) | +{r['delta']} | {r['n']}/{len(dates)} 天 | #{r['best']} | {r['lang'] or '-'} |")
        L.append("")

    L.append("## 榜单常客（上榜 ≥2 天）")
    L.append("")
    regular = sorted([r for r in rows if r["n"] >= 2], key=lambda r: (-r["n"], r["best"]))
    if regular:
        L.append("| 仓库 | 上榜 | 最高名次 | 今日⭐合计 | 标签 |")
        L.append("|---|---|---|---|---|")
        for r in regular:
            L.append(f"| [{r['repo']}]({r['url']}) | {r['n']}/{len(dates)} 天 | #{r['best']} | {r['today_sum']} | {' '.join(r['tags']) or '-'} |")
    else:
        L.append("本周暂时没有连续上榜的仓库。")
    L.append("")

    L.append("## 本周新面孔（本周首次出现）")
    L.append("")
    firsts = [r for r in rows if r["first"] > dates[0]]
    if firsts:
        for r in sorted(firsts, key=lambda r: r["first"]):
            L.append(f"- {r['first']} · [{r['repo']}]({r['url']}) · 最高 #{r['best']} · {r['lang'] or '-'} · {(r['desc'] or '')[:90]}")
    else:
        L.append("本周没有新的首次上榜仓库。")
    L.append("")

    focus = [r for r in rows if r["focus"]]
    if focus:
        L.append(f"## 重点：vibecoding / agent 插件技能（本周上榜 {len(focus)} 个）")
        L.append("")
        for r in sorted(focus, key=lambda r: r["today_sum"], reverse=True):
            pd = "-"
            L.append(f"- **[{r['repo']}]({r['url']})** {' '.join(r['tags'])} · 上榜 {r['n']} 天 · 最高 #{r['best']} · 今日⭐合计 {r['today_sum']} · {(r['desc'] or '')[:100]}")
        L.append("")

    os.makedirs(REPORTS, exist_ok=True)
    out = os.path.join(REPORTS, f"week-{today}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
