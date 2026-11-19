#!/usr/bin/env python3
"""
根据 .work/*.json 评分数据生成：
1. 新高考历史卷 Top 20.md（近六年 2021–2026 精选 Top 20）
2. 全库评分总榜.md（2015–2026 全部 124 套题面可用试卷完整八维评分与排名）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".work"
sys.path.insert(0, str(WORK))

from rubric import AXES, TIERS, composite_score, parse_grades, sort_key  # noqa: E402


def norm_key(paper: str) -> str:
    title = re.sub(r"\s+|年|卷|[（）()]", "", paper)
    m = re.search(r"(\d{4})(\d{1,2})月浙江", title)
    if m:
        return f"{m[1]} 浙江{m[2]}月"
    m = re.search(r"(\d{4})浙江(\d{1,2})月", title)
    if m:
        return f"{m[1]} 浙江{m[2]}月"
    m = re.fullmatch(r"(\d{4})(.+)", title)
    return f"{m[1]} {m[2]}" if m else paper


def label(paper_key: str) -> str:
    year, region = paper_key.split(" ", 1)
    m = re.fullmatch(r"浙江(\d+)月", region)
    return f"{year}年{m[1]}月浙江卷" if m else f"{year}年{region}卷"


def load_all_scores() -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for name in ("east", "north", "southwest", "root-papers", "upgrades"):
        p = WORK / f"{name}.json"
        if not p.exists():
            continue
        for rec in json.loads(p.read_text(encoding="utf-8-sig")):
            k = norm_key(rec.get("paper", ""))
            merged[k] = {**merged.get(k, {}), **rec, "paper": k}
    return merged


def main() -> None:
    catalog_papers = json.loads((ROOT / "site" / "data" / "catalog.json").read_text(encoding="utf-8"))["papers"]
    cat_by_key = {norm_key(p["title"]): p for p in catalog_papers}

    scores = load_all_scores()

    # 1. Update picks.json to include 2025 上海 right before 2024 上海 (if not present)
    picks_path = WORK / "picks.json"
    picks = json.loads(picks_path.read_text(encoding="utf-8-sig"))
    pick_keys = [norm_key(p["paper"]) for p in picks]
    if "2025 上海" not in pick_keys:
        idx = pick_keys.index("2024 上海") if "2024 上海" in pick_keys else 10
        picks.insert(idx, {"paper": "2025 上海"})
        picks = picks[:20]
        picks_path.write_text(json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8")

    # Apply picks.json overrides onto scores
    for pick in picks:
        k = norm_key(pick["paper"])
        scores[k] = {**scores.get(k, {}), **pick, "paper": k}

    # 2. Build full 124-paper ranking
    full_ranked = []
    for k, cat in cat_by_key.items():
        if cat["status"] != "题面可用":
            continue
        rec = scores.get(k)
        if not rec or not rec.get("grades"):
            raise ValueError(f"Usable paper missing grades: {k}")
        g = parse_grades(rec["grades"], k)
        sc = composite_score(g, k)
        sk = sort_key(g, k)
        file_path = cat["files"][0]["path"] if cat["files"] else rec.get("file", "")
        source_url = cat["sources"][0]["url"] if cat["sources"] else rec.get("source", "")
        full_ranked.append(
            {
                "key": k,
                "title": cat["title"],
                "year": cat["year"],
                "region": cat["region"],
                "grades": g,
                "score": sc,
                "sort_key": sk,
                "note": (rec.get("note") or "").strip(),
                "version": cat.get("note") or rec.get("version") or "",
                "file": file_path,
                "source": source_url,
            }
        )

    full_ranked.sort(key=lambda x: (x["sort_key"], x["year"] or 0, x["key"]), reverse=True)

    # Write 全库评分总榜.md
    lines = [
        "# 新高考历史全库八维评分总榜（2015–2026）",
        "",
        f"全库编目 **131 套** · 题面可用并已完成八维 14 档评分 **{len(full_ranked)} 套**（另有部分题面 2 套、待补 5 套未纳入评分）。",
        "",
        "**八轴顺序与权重**：考查布局（1.0）/ 史料运用（1.5）/ 历史推理（1.5）/ 情境建构（1.5）/ 设问质量（1.0）/ 任务梯度（1.0）/ 开放论证（1.5）/ 价值立意（1.0）。细则见 [八维评分细则](%E5%85%AD%E7%BB%B4%E8%AF%84%E5%88%86%E7%BB%86%E5%88%99.md)。",
        "",
        "| 排名 | 试卷 | 综合指数 | 考查布局 | 史料运用 | 历史推理 | 情境建构 | 设问质量 | 任务梯度 | 开放论证 | 价值立意 |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for rank, item in enumerate(full_ranked, 1):
        g = item["grades"]
        link = f"[{item['title']}]({quote(item['file'], safe='/')})" if item["file"] else item["title"]
        lines.append(
            f"| {rank} | {link} | **{item['score']:.1f}** | {g[0]} | {g[1]} | {g[2]} | {g[3]} | {g[4]} | {g[5]} | {g[6]} | {g[7]} |"
        )
    lines.append("")
    (ROOT / "全库评分总榜.md").write_text("\n".join(lines), encoding="utf-8")

    # 3. Rebuild 新高考历史卷 Top 20.md (2021–2026)
    recent = [p for p in catalog_papers if (p.get("year") or 0) >= 2021]
    recent_ready = sum(1 for p in recent if p["status"] == "题面可用")
    recent_part = sum(1 for p in recent if p["status"] == "部分题面")
    recent_known = recent_ready + recent_part
    scope = f"2021 年至 2026 年（近六年） · 编目 {len(recent)} 套 · 已归档 {recent_known} 套，其中 {recent_ready} 套题面可用于评选。榜单基于公开可核的题面。"

    top20_lines = [
        "# 各省新高考历史卷 Top 20（近六年 2021–2026）",
        "",
        scope,
        "",
        "**评价体例**：整卷采用**排名制**（第 1 名至第 20 名），不再对整卷作等第分档；雷达图八个具体维度采用 **14 档**评分，并据此加权计算综合指数辅助排序。",
        "",
        "**八轴顺序与权重**　考查布局（1.0） / 史料运用（1.5） / 历史推理（1.5） / 情境建构（1.5） / 设问质量（1.0） / 任务梯度（1.0） / 开放论证（1.5） / 价值立意（1.0）",
        "",
        "**分项 14 档（由高到低）**：`S+ · S · A+ · A · A- · B+ · B · B- · C+ · C · C- · D+ · D · D-`（对应 14–1 分，按总权重 10.0 加权折算百分制综合指数）。同分顺位优先看核心四轴（史料运用、历史推理、情境建构、开放论证），再看短板一致性及全卷创新性。细则与标准依据见[八维评分细则](%E5%85%AD%E7%BB%B4%E8%AF%84%E5%88%86%E7%BB%86%E5%88%99.md)及[标准与文献索引](%E6%A0%87%E5%87%86%E4%B8%8E%E6%96%87%E7%8C%AE/%E7%9B%AE%E5%BD%95%E4%B8%8E%E7%B4%A2%E5%BC%95.md)。全库 124 套完整排名见[全库评分总榜](%E5%85%A8%E5%BA%93%E8%AF%84%E5%88%86%E6%80%BB%E6%A6%9C.md)。",
        "",
        "题面版本、缺页和未下载场次见[试卷目录](%E8%AF%95%E5%8D%B7%E7%9B%AE%E5%BD%95.md)。整理版的参考答案按其来源使用。任务梯度基于试卷设计，实测难度与区分度需要考生作答数据。",
        "",
        "## 综合排名",
        "",
    ]

    for rank, pick in enumerate(picks, 1):
        k = norm_key(pick["paper"])
        cat = cat_by_key[k]
        rec = scores[k]
        g = parse_grades(rec["grades"], k)
        sc = composite_score(g, k)
        ratings = " · ".join(f"{a} {gr}" for a, gr in zip(AXES, g))
        note = (rec.get("note") or "").strip().replace("；", "。").replace(";", "。")
        file_path = cat["files"][0]["path"] if cat["files"] else rec.get("file", "")
        source_url = cat["sources"][0]["url"] if cat["sources"] else rec.get("source", "")
        ver = cat.get("note") or rec.get("version") or ""
        parts = []
        if ver:
            parts.append(ver)
        if file_path:
            parts.append(f"[本地试卷]({quote(file_path, safe='/')})")
        if source_url:
            parts.append(f"[来源]({source_url})")
        top20_lines += [
            f"{rank}. **{cat['title']}** · 综合指数 {sc:.1f}",
            "",
            f"   {ratings}",
            "",
            f"   {note}",
            "",
            f"   {' · '.join(parts)}",
            "",
        ]

    top20_lines += [
        "## 山东卷复核",
        "",
        "按提供的备课档案复核 2021–2025 年山东卷。2021 年图版补入本地档案并入榜。2022 年试卷与备课原卷的文件指纹一致，参考答案随卷存放。2023 年另找到保留图表的公开图版。2023 和 2025 年山东卷均已纳入全库复核，位于本次 Top 20 榜单之外。",
        "",
        "## 范围与口径来源",
        "",
        "- [教育部高考改革政策](https://www.moe.gov.cn/jyb_xwfb/xw_zt/moe_357/2025/2025_zt10/wd/gkwd_zlhz/202506/t20250604_1192960.html) · [浙江首场选考记录](https://www.zjzs.net/art/2024/11/29/art_30_10407.html)",
        "- [教育部关于高中历史课程标准的通知](https://www.moe.gov.cn/srcsite/A26/s8001/202006/t20200603_462199.html) · [中国高考评价体系](https://www.moe.gov.cn/jyb_xwfb/s271/202001/t20200107_414613.html)",
        "",
    ]
    (ROOT / "新高考历史卷 Top 20.md").write_text("\n".join(top20_lines), encoding="utf-8")

    print(f"Generated 全库评分总榜.md ({len(full_ranked)} papers) and updated 新高考历史卷 Top 20.md (scope: {recent_ready}/{len(recent)}).")


if __name__ == "__main__":
    main()
