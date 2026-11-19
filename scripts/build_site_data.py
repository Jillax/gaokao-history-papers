#!/usr/bin/env python3
"""
从 试卷目录.md 与 新高考历史卷 Top 20.md 生成静态网站所需的 site/data/catalog.json。
用法: python scripts/build_site_data.py
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
CATALOG_MD = ROOT / "试卷目录.md"
TOP20_MD = ROOT / "新高考历史卷 Top 20.md"
FULL_RANK_MD = ROOT / "全库评分总榜.md"
RADAR_DIR = ROOT / "雷达图"
OUTPUT_JSON = ROOT / "site" / "data" / "catalog.json"

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def classify_status(raw_status: str) -> str:
    if raw_status.startswith("题面可用"):
        return "题面可用"
    if raw_status.startswith("部分题面"):
        return "部分题面"
    if raw_status.startswith("待补"):
        return "待补"
    return raw_status


def extract_year(title: str) -> int | None:
    m = re.search(r"(20\d{2})年", title)
    return int(m.group(1)) if m else None


def parse_catalog() -> tuple[dict, list[dict]]:
    text = CATALOG_MD.read_text(encoding="utf-8")
    lines = text.splitlines()

    summary = ""
    current_region = ""
    papers: list[dict] = []

    for line in lines:
        stripped = line.strip()
        if not summary and stripped.startswith("2015 年"):
            summary = stripped
            continue

        if stripped.startswith("## 范围依据"):
            break

        if stripped.startswith("### "):
            current_region = stripped[4:].strip()
            # 去掉括号里的共用说明作为短标签，同时保留完整地区名
            continue

        if not current_region or not stripped.startswith("- "):
            continue

        body = stripped[2:].strip()
        parts = [p.strip() for p in body.split(" · ")]
        if len(parts) < 2:
            continue

        title = parts[0]
        raw_status = parts[1]
        status = classify_status(raw_status)
        year = extract_year(title)

        region_short = current_region.split("（")[0].strip()

        local_files: list[dict] = []
        source_links: list[dict] = []
        notes: list[str] = []

        for part in parts[2:]:
            links = LINK_RE.findall(part)
            if links:
                for label, url in links:
                    if url.startswith("http://") or url.startswith("https://"):
                        source_links.append({"label": label, "url": url})
                    else:
                        rel_path = unquote(url).replace("\\", "/")
                        abs_path = ROOT / rel_path
                        ext = Path(rel_path).suffix.lower().lstrip(".")
                        size_bytes = abs_path.stat().st_size if abs_path.is_file() else 0
                        local_files.append(
                            {
                                "label": label,
                                "path": rel_path,
                                "ext": ext,
                                "sizeBytes": size_bytes,
                                "sizeText": human_size(size_bytes) if size_bytes else "",
                                "exists": abs_path.is_file(),
                            }
                        )
            else:
                notes.append(part)

        papers.append(
            {
                "id": f"{region_short}-{title}",
                "region": region_short,
                "regionFull": current_region,
                "title": title,
                "year": year,
                "status": status,
                "statusDetail": raw_status,
                "note": " · ".join(notes),
                "files": local_files,
                "sources": source_links,
            }
        )

    meta = {
        "summary": summary,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return meta, papers


def parse_top20() -> list[dict]:
    if not TOP20_MD.is_file():
        return []

    text = TOP20_MD.read_text(encoding="utf-8")
    lines = text.splitlines()

    radar_map: dict[int, str] = {}
    if RADAR_DIR.is_dir():
        for f in RADAR_DIR.iterdir():
            if f.is_file():
                m = re.match(r"TOP(\d+)_", f.name)
                if m:
                    radar_map[int(m.group(1))] = f"雷达图/{f.name}"

    items: list[dict] = []
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        m = re.match(r"^(\d+)\.\s+\*\*(.+?)\*\*\s+·\s+综合指数\s+([\d.]+)", stripped)
        if m:
            if current:
                items.append(current)
            rank = int(m.group(1))
            current = {
                "rank": rank,
                "title": m.group(2).strip(),
                "score": float(m.group(3)),
                "dimensions": "",
                "comment": "",
                "files": [],
                "sources": [],
                "radarImage": radar_map.get(rank, ""),
            }
            continue

        if current is None:
            continue

        if stripped.startswith("## ") and not stripped.startswith("## 综合排名"):
            break

        if not stripped:
            continue

        if stripped.startswith("考查布局"):
            current["dimensions"] = stripped
        elif "[本地试卷]" in stripped or "[来源]" in stripped:
            for label, url in LINK_RE.findall(stripped):
                if url.startswith("http://") or url.startswith("https://"):
                    current["sources"].append({"label": label, "url": url})
                else:
                    rel_path = unquote(url).replace("\\", "/")
                    ext = Path(rel_path).suffix.lower().lstrip(".")
                    current["files"].append({"label": label, "path": rel_path, "ext": ext})
        else:
            if current["comment"]:
                current["comment"] += " " + stripped
            else:
                current["comment"] = stripped

    if current:
        items.append(current)

    return items


def parse_full_scores() -> dict[str, dict]:
    if not FULL_RANK_MD.is_file():
        return {}
    scores: dict[str, dict] = {}
    for line in FULL_RANK_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*\[?([^\]|]+?)(?:\]\([^)]+\))?\s*\|\s*\*\*([\d.]+)\*\*\s*\|(.+)\|$", line.strip())
        if not m:
            continue
        rank = int(m.group(1))
        title = m.group(2).strip()
        score = float(m.group(3))
        grades = [c.strip() for c in m.group(4).split("|") if c.strip()]
        scores[title] = {"rank": rank, "score": score, "grades": grades}
    return scores


def main() -> None:
    meta, papers = parse_catalog()
    top20 = parse_top20()
    full_scores = parse_full_scores()
    for p in papers:
        sc = full_scores.get(p["title"])
        if sc:
            p["rank"] = sc["rank"]
            p["score"] = sc["score"]
            p["grades"] = sc["grades"]

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "papers": papers,
        "top20": top20,
    }
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {OUTPUT_JSON} with {len(papers)} papers and {len(top20)} top20 items.")


if __name__ == "__main__":
    main()
