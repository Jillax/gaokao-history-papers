#!/usr/bin/env python3
"""
HistoryLTiV 新高考历史卷评测雷达图卡片工程化生成器。

数据源（单一事实来源）：
- .work/build-rank.py (corpus, calendars, status, label)
- .work/rubric.py (AXES, TIERS, TIER_VALUES, parse_grades, composite_score, sort_key)
- .work/picks.json (Top 20 人工审定顺位与 14 档评分)
- .work/*.txt (原卷文本自动识别题目真实题型：选择题 / 材料题 / 评析题 / 短文题 / 论述题)

用法示例：
  python scripts/generate_radar_cards.py --top 3
  python scripts/generate_radar_cards.py --ranks 1 2 3 --out-dir 雷达图_14档Top3
  python scripts/generate_radar_cards.py --papers "2024 山东" "2025 山东" --out-dir 雷达图_测试
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".work"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DESK_BASE_PATH = ASSETS_DIR / "desk_base.png"
ART_CACHE_DIR = ASSETS_DIR / "art_cache"
DEFAULT_CREDENTIALS = Path(
    r"c:\Users\25382\Downloads\project-93a32a31-7a8a-4601-9fd-f6822d6f360c.json"
)
GCP_PROJECT = "project-93a32a31-7a8a-4601-9fd"
GCP_LOCATION = "global"

sys.path.insert(0, str(WORK))
from rubric import AXES, TIERS, TIER_VALUES, composite_score, parse_grades, sort_key  # noqa: E402

_br_spec = importlib.util.spec_from_file_location("build_rank", WORK / "build-rank.py")
build_rank = importlib.util.module_from_spec(_br_spec)
assert _br_spec and _br_spec.loader
_br_spec.loader.exec_module(build_rank)


@dataclass
class QuestionHighlight:
    q_num: int | None
    tag: str       # e.g. "第02题" or "总评"
    q_type: str    # e.g. "选择题", "材料题", "评析题", "短文题", "论述题", "综述"
    summary: str   # concise 1-2 line summary


@dataclass
class SessionSeat:
    paper_key: str
    short_label: str  # e.g. "2023" or "2022.1"
    rank: int | None
    badge_text: str   # e.g. "(#1)" or "(待评)" or "(部分)" or "(待补)"


@dataclass
class PaperRecord:
    rank: int
    total_available: int
    scored_count: int
    year_span: str
    paper_key: str
    year: str
    region: str
    title: str
    grades: list[str]
    axis_scores: list[float]
    score: float
    note: str
    version: str
    highlights: list[QuestionHighlight]
    strength: str
    region_seats: list[SessionSeat]


def load_serif_font(size: int) -> ImageFont.FreeTypeFont:
    for p in (
        r"C:\Windows\Fonts\STZHONGS.TTF",
        r"C:\Windows\Fonts\NotoSerifSC-VF.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load_sans_bold(size: int) -> ImageFont.FreeTypeFont:
    for p in (
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\arialbd.ttf",
    ):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def find_paper_text(paper_key: str) -> str:
    """Locate extracted .txt content for a paper key like '2023 北京' or '2022 浙江1月'."""
    parts = paper_key.split(" ", 1)
    if len(parts) != 2:
        return ""
    year, region = parts
    candidates: list[Path] = []
    for prefix in ("east-", "north-", ""):
        candidates.append(WORK / f"{prefix}{year}-{region}.txt")
        candidates.append(WORK / "southwest-text" / f"{prefix}{year}-{region}.txt")
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8", errors="ignore")

    # Fallback glob search for Zhejiang/Shanghai variants
    m = re.fullmatch(r"浙江(\d+)月", region)
    for txt_path in list(WORK.glob("*.txt")) + list((WORK / "southwest-text").glob("*.txt")):
        name = txt_path.name
        if year not in name:
            continue
        if m:
            month = m.group(1)
            if "浙江" in name and re.search(rf"(?<!\d){month}月|-{month}-", name):
                return txt_path.read_text(encoding="utf-8", errors="ignore")
        elif region in name:
            return txt_path.read_text(encoding="utf-8", errors="ignore")
    return ""


def detect_question_type(txt_content: str, q_num: int | None, clause: str) -> str:
    """Classify real exam question type from paper text, falling back to note keywords."""
    if q_num is None:
        return "综述"

    if txt_content:
        # Locate start of non-multiple-choice section (must be a standalone heading line!)
        non_mc_match = re.search(r"(?m)^\s*(?:二、\s*非选择题|第[二三]部分)\s*$", txt_content)
        if not non_mc_match:
            non_mc_match = re.search(r"(?m)^\s*二、\s*非选择题", txt_content)
        non_mc_pos = non_mc_match.start() if non_mc_match else len(txt_content)

        # Find question block for q_num
        q_pattern = re.compile(rf"(?m)^\s*{q_num}\s*[\.．、]")
        m = q_pattern.search(txt_content)
        if not m:
            q_pattern = re.compile(rf"(?m)^\s*第?\s*{q_num}\s*题")
            m = q_pattern.search(txt_content)

        if m:
            pos = m.start()
            next_q = re.search(rf"(?m)^\s*{q_num + 1}\s*[\.．、]", txt_content[pos + 3 :])
            end_pos = pos + 3 + next_q.start() if next_q else min(len(txt_content), pos + 1800)
            snippet = txt_content[pos:end_pos]

            if pos < non_mc_pos and re.search(r"(?m)^\s*A\s*[\.．、]", snippet):
                return "选择题"
            if pos < non_mc_pos and non_mc_match is not None and q_num <= 16:
                return "选择题"
            if re.search(r"短文|小论文", snippet):
                return "短文题"
            if re.search(r"自拟论题|拟定论题|提炼.*论题|写.*目录|研究提纲|构建.*段落|阐述", snippet):
                return "论述题"
            # Only classify as 评析题 if it is a unified essay prompt rather than a multi-part (1)(2) material question
            has_subparts = bool(re.search(r"[（(]1[）)]", snippet) and re.search(r"[（(]2[）)]", snippet))
            if not has_subparts and re.search(r"评析|评价.*观点|点评", snippet):
                return "评析题"
            return "材料题"

    # Fallback from note text if .txt missing
    if re.search(r"选项|选择题", clause) or (q_num <= 15 and not re.search(r"材料|评析|论述|短文|提纲", clause)):
        return "选择题"
    if re.search(r"短文", clause):
        return "短文题"
    if re.search(r"论题|论证|阐述|提纲|目录|构建", clause):
        return "论述题"
    if re.search(r"评析|评价|点评", clause):
        return "评析题"
    return "材料题"


def _condense_clause(text: str, max_chars: int = 38) -> str:
    text = text.strip().strip("，,、。；;")
    # Strip trailing holistic paper remarks attached to a single question clause
    text = re.sub(r"[，,]\s*(?:全卷|整体)[^，,]{2,10}$", "", text).strip()
    if len(text) > max_chars:
        text = re.sub(r"（[^）]{4,}）", "", text).strip()
    if len(text) <= max_chars:
        return text
    for sep in ("，", ","):
        if sep in text:
            head = text.split(sep, 1)[0].strip()
            if 10 <= len(head) <= max_chars:
                return head
    return text[: max_chars - 1] + "…"


def extract_highlights(paper_key: str, note: str) -> list[QuestionHighlight]:
    """Extract up to 3 question highlights from note, sorted strictly by question number ascending."""
    txt_content = find_paper_text(paper_key)
    raw_clauses = [c.strip() for c in re.split(r"[。；;]", note) if c.strip()]

    # Also split clauses like "...，第18题..." into separate items
    expanded: list[str] = []
    for cl in raw_clauses:
        parts = re.split(r"[，,]\s*(?=第\d+题)", cl)
        expanded.extend(p.strip() for p in parts if p.strip())

    by_q: dict[int, tuple[str, str]] = {}
    general_notes: list[str] = []

    for cl in expanded:
        m = re.match(r"^第(\d+)题\s*(.*)$", cl)
        if not m:
            # Check if a single clause mentions 第X题 in the middle (e.g. "第17、18题...")
            m_mid = re.search(r"第(\d+)题", cl)
            if m_mid:
                q_num = int(m_mid.group(1))
                desc = re.sub(r"^.*?第\d+题\s*", "", cl).strip()
                if q_num not in by_q or len(desc) > len(by_q[q_num][1]):
                    by_q[q_num] = (cl, desc)
            else:
                general_notes.append(cl)
            continue
        q_num = int(m.group(1))
        desc = m.group(2).strip()
        if q_num not in by_q or len(desc) > len(by_q[q_num][1]):
            by_q[q_num] = (cl, desc)

    items: list[QuestionHighlight] = []
    for q_num in sorted(by_q.keys()):
        raw_cl, desc = by_q[q_num]
        q_type = detect_question_type(txt_content, q_num, raw_cl)
        items.append(
            QuestionHighlight(
                q_num=q_num,
                tag=f"第{q_num:02d}题",
                q_type=q_type,
                summary=_condense_clause(desc, max_chars=38),
            )
        )
        if len(items) == 3:
            break

    while len(items) < 3 and general_notes:
        gn = general_notes.pop(0)
        items.append(
            QuestionHighlight(
                q_num=None,
                tag="卷面综述",
                q_type="综述",
                summary=_condense_clause(gn, max_chars=38),
            )
        )

    return items


def z_to_t(val: float, mu: float, sd: float, anchor: float = 70.0, step: float = 12.0) -> float:
    """Convert raw value to corpus-normed Z-score T-scale centered at 70 (sigma=12, clamped to [20, 100])."""
    if sd <= 1e-9:
        return anchor
    t = anchor + step * (val - mu) / sd
    return round(max(20.0, min(100.0, t)), 1)


def build_strength_text(axis_scores: list[float], score: float) -> str:
    top_sc = max(axis_scores)
    full_axes = [AXES[i] for i, sc in enumerate(axis_scores) if abs(sc - top_sc) < 0.05]
    if len(full_axes) <= 2:
        axes_str = " · ".join(full_axes)
    else:
        axes_str = "·".join(a[:2] for a in full_axes[:3])
    return f"核心强项：{axes_str} {top_sc:.1f} 分 · 常模赋分 {score:.1f}"


def _short_session_label(paper_key: str) -> str:
    year, region = paper_key.split(" ", 1)
    m = re.fullmatch(r"浙江(\d+)月", region)
    if m:
        return f"{year}\n{m.group(1)}月"
    return year


def load_full_dataset() -> tuple[list[PaperRecord], dict[str, PaperRecord], list[float]]:
    """Load all catalog sessions, compute 1..N ranks, and assemble complete per-paper records."""
    collection = build_rank.corpus()
    by_region = build_rank.calendars()
    expected = [p for group in by_region.values() for p in group]
    years = sorted({int(p.split(" ", 1)[0]) for p in expected})
    year_span = f"{years[0]}-{years[-1]}"
    available = [p for p in expected if build_rank.status(collection.get(p)) == "题面可用"]
    total_avail = len(available)

    picks_list = build_rank.read("picks")
    picks_map = {pk["paper"]: pk for pk in picks_list}

    # Build authoritative ordered ranking: 1..20 from picks.json, 21..N sorted by rubric.sort_key
    ordered_keys: list[str] = [pk["paper"] for pk in picks_list]
    outside = []
    for p in available:
        if p in picks_map:
            continue
        row = collection.get(p, {})
        if row.get("grades"):
            outside.append((p, sort_key(row["grades"], p)))
    outside.sort(key=lambda x: x[1], reverse=True)
    ordered_keys.extend(p for p, _ in outside)

    rank_lookup = {p: idx for idx, p in enumerate(ordered_keys, 1)}

    # Build complete chronological history per region (never skipping any year!)
    region_seats_map: dict[str, list[SessionSeat]] = {}
    for region, sessions in by_region.items():
        seats: list[SessionSeat] = []
        for p in sessions:
            r = rank_lookup.get(p)
            st = build_rank.status(collection.get(p))
            if r is not None:
                badge = f"(#{r})"
            elif st == "题面可用":
                badge = "(待评)"
            elif st == "部分题面":
                badge = "(部分)"
            else:
                badge = "(待补)"
            seats.append(
                SessionSeat(
                    paper_key=p,
                    short_label=_short_session_label(p),
                    rank=r,
                    badge_text=badge,
                )
            )
        region_seats_map[region] = seats

    # Reverse lookup from paper_key -> region
    paper_to_region = {p: reg for reg, sessions in by_region.items() for p in sessions}

    # Compute corpus mean & std for Z-score T-scale normalization (mu=70, sigma=12)
    raw_axis_matrix: list[list[float]] = []
    raw_comp_scores: list[float] = []
    parsed_cache: dict[str, tuple[list[str], float, dict]] = {}
    for p in ordered_keys:
        merged = {**collection.get(p, {}), **picks_map.get(p, {})}
        gs = parse_grades(merged["grades"], p)
        raw_sc = composite_score(gs, p)
        parsed_cache[p] = (gs, raw_sc, merged)
        raw_axis_matrix.append([float(TIER_VALUES[g]) for g in gs])
        raw_comp_scores.append(raw_sc)

    scored_count = len(ordered_keys)
    n_ax = len(AXES)
    axis_mu = [sum(row[i] for row in raw_axis_matrix) / scored_count for i in range(n_ax)]
    axis_sd = [
        math.sqrt(sum((row[i] - axis_mu[i]) ** 2 for row in raw_axis_matrix) / scored_count)
        for i in range(n_ax)
    ]
    comp_mu = sum(raw_comp_scores) / scored_count
    comp_sd = math.sqrt(sum((x - comp_mu) ** 2 for x in raw_comp_scores) / scored_count)

    # Full-corpus baseline average in T-score space (~70.0 per axis)
    all_t_matrix = [
        [z_to_t(row[i], axis_mu[i], axis_sd[i]) for i in range(n_ax)]
        for row in raw_axis_matrix
    ]
    corpus_avgs = [
        round(sum(row[i] for row in all_t_matrix) / scored_count, 1)
        for i in range(n_ax)
    ]

    records: list[PaperRecord] = []
    by_key: dict[str, PaperRecord] = {}
    for rank, p in enumerate(ordered_keys, 1):
        grades, raw_sc, merged = parsed_cache[p]
        ax_t_scores = [z_to_t(TIER_VALUES[g], axis_mu[i], axis_sd[i]) for i, g in enumerate(grades)]
        t_score = z_to_t(raw_sc, comp_mu, comp_sd)
        note = build_rank.clean(merged.get("note", ""))
        year, _ = p.split(" ", 1)
        region = paper_to_region[p]
        rec = PaperRecord(
            rank=rank,
            total_available=total_avail,
            scored_count=scored_count,
            year_span=year_span,
            paper_key=p,
            year=year,
            region=region,
            title=build_rank.label(p),
            grades=grades,
            axis_scores=ax_t_scores,
            score=t_score,
            note=note,
            version=merged.get("version", ""),
            highlights=extract_highlights(p, note),
            strength=build_strength_text(ax_t_scores, t_score),
            region_seats=region_seats_map[region],
        )
        records.append(rec)
        by_key[p] = rec

    return records, by_key, corpus_avgs


def get_or_generate_art(rec: PaperRecord, credentials_path: Path | None, use_ai: bool = True) -> Image.Image:
    """Return cached 1:1 warm-parchment copperplate engraving or generate via Google GenAI."""
    ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = rec.paper_key.replace("/", "-")
    cache_path = ART_CACHE_DIR / f"{safe_name}.png"
    if cache_path.is_file():
        return Image.open(cache_path).convert("RGB")

    if use_ai and credentials_path and credentials_path.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)
        from google import genai
        from google.genai import types

        client = genai.Client(enterprise=True, project=GCP_PROJECT, location=GCP_LOCATION)
        prompt = (
            f"一幅中国博物馆典藏铜版画/木刻细线历史插画，画在泛黄复古宣纸方形画心上（暖米白纸底，深褐古墨与淡金细线）。"
            f"画面主题严格依据高考历史试卷《{rec.title}》的核心史料意象创作：{rec.note}。"
            f"要求：只画精致古朴的器物、文献卷轴、建筑、航线地图、统计图表或历史场景剖面线描，"
            f"画面中绝对不要出现现代文字、题号、评分数字、人物大头特写或花哨边框，构图饱满典雅。"
        )
        for model_name in ("gemini-nano-banana-2.1", "gemini-3-pro-image"):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(aspect_ratio="1:1", image_size="1K"),
                    ),
                )
                for part in resp.parts:
                    if part.inline_data:
                        cache_path.write_bytes(part.inline_data.data)
                        print(f"[art] Generated {cache_path.name} via {model_name}", flush=True)
                        return Image.open(cache_path).convert("RGB")
            except Exception as e:
                print(f"[art] {model_name} err for {rec.paper_key}: {e}", flush=True)
                time.sleep(3)

    # Graceful offline fallback emblem if --no-ai or credentials unavailable
    fallback = Image.new("RGB", (540, 540), (228, 214, 186))
    d = ImageDraw.Draw(fallback)
    d.rectangle((24, 24, 516, 516), outline=(120, 92, 62), width=3)
    f_big = load_serif_font(64)
    tb = d.textbbox((0, 0), rec.region, font=f_big)
    d.text((270 - (tb[2] - tb[0]) / 2, 200), rec.region, font=f_big, fill=(76, 54, 34))
    f_yr = load_serif_font(42)
    yb = d.textbbox((0, 0), rec.year, font=f_yr)
    d.text((270 - (yb[2] - yb[0]) / 2, 290), rec.year, font=f_yr, fill=(142, 54, 38))
    return fallback


def _draw_dashed_polygon(draw: ImageDraw.ImageDraw, pts: list[tuple[float, float]], fill, width: int, dash: int, gap: int) -> None:
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        dist = math.hypot(x2 - x1, y2 - y1)
        if dist == 0:
            continue
        dx, dy = (x2 - x1) / dist, (y2 - y1) / dist
        pos = 0.0
        while pos < dist:
            end = min(pos + dash, dist)
            draw.line(
                [(x1 + dx * pos, y1 + dy * pos), (x1 + dx * end, y1 + dy * end)],
                fill=fill,
                width=width,
            )
            pos += dash + gap


def _wrap_cjk_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int, max_lines: int = 2) -> list[str]:
    lines: list[str] = []
    cur = ""
    for ch in text:
        test = cur + ch
        bw = draw.textbbox((0, 0), test, font=font)[2]
        if bw <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
                if len(lines) >= max_lines:
                    lines[-1] = lines[-1][:-1] + "…"
                    return lines
            cur = ch
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def render_card(
    rec: PaperRecord,
    corpus_avgs: list[float],
    desk_base: Image.Image,
    art_img: Image.Image,
    out_path: Path,
) -> None:
    """Render a complete 2752x1536 HistoryLTiV card deterministically with 4x supersampled radar."""
    canvas = desk_base.convert("RGBA")
    w, h = canvas.size

    # Sync top-left header year span (patch baked-in '(2015-2026)' with dynamic year_span)
    hdr_x1, hdr_y1, hdr_x2, hdr_y2 = 1430, 62, 1925, 175
    strip = canvas.crop((1935, hdr_y1, 2025, hdr_y2))
    strip_flip = strip.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    patch = Image.new("RGBA", (hdr_x2 - hdr_x1, hdr_y2 - hdr_y1))
    sw = strip.width
    for px in range(0, patch.width, sw):
        patch.paste(strip if (px // sw) % 2 == 0 else strip_flip, (px, 0))
    canvas.paste(patch, (hdr_x1, hdr_y1))

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")

    f_hdr_span = load_serif_font(82)
    span_txt = f"（{rec.year_span}）"
    span_x, span_y = 1408, 74
    d.text((span_x + 3, span_y + 3), span_txt, font=f_hdr_span, fill=(10, 7, 5, 195))
    d.text((span_x, span_y), span_txt, font=f_hdr_span, fill=(236, 198, 158, 255))

    # Fonts
    f_rank_big = load_serif_font(124)
    f_rank_total = load_serif_font(46)
    f_title = load_serif_font(48 if len(rec.title) <= 8 else 40)
    f_score = load_serif_font(30)
    f_sec = load_serif_font(35)
    f_qtag = load_serif_font(25)
    f_qdesc = load_serif_font(28)
    f_qtype = load_serif_font(38)
    f_strength = load_serif_font(26)
    f_top_badge = load_serif_font(86)

    # 1. Left Hero Rank + Title + Score Pill
    x_left = 122
    rank_str = f"#{rec.rank}"
    total_str = f"/{rec.total_available}"
    d.text((x_left, 205), rank_str, font=f_rank_big, fill=(246, 224, 184, 255))
    rb = d.textbbox((x_left, 205), rank_str, font=f_rank_big)
    d.text((rb[2] + 4, 276), total_str, font=f_rank_total, fill=(214, 194, 162, 235))
    tb_total = d.textbbox((rb[2] + 4, 276), total_str, font=f_rank_total)

    x_title = max(368, tb_total[2] + 24)
    d.text((x_title, 222), rec.title, font=f_title, fill=(248, 238, 218, 255))

    # Bronze score pill
    score_txt = f"常模赋分 {rec.score:.1f}"
    sb = d.textbbox((0, 0), score_txt, font=f_score)
    pw = (sb[2] - sb[0]) + 44
    ph = 50
    px1, py1 = x_title, 294
    d.rounded_rectangle(
        [px1, py1, px1 + pw, py1 + ph],
        radius=25,
        fill=(186, 146, 86, 235),
        outline=(244, 214, 156, 255),
        width=2,
    )
    d.text(
        (px1 + (pw - (sb[2] - sb[0])) / 2 - sb[0], py1 + (ph - (sb[3] - sb[1])) / 2 - sb[1]),
        score_txt,
        font=f_score,
        fill=(32, 22, 14, 255),
    )

    # 2. Left Core Highlights (3 cards sorted ascending by question number)
    d.text((x_left, 444), "核心亮题拆解", font=f_sec, fill=(236, 198, 132, 255))

    card_x1, card_x2 = x_left, 845
    card_y = 510
    card_h = 228
    card_gap = 26

    for hl in rec.highlights[:3]:
        cy1, cy2 = card_y, card_y + card_h
        # Translucent dark inkstone card + antique double border
        d.rounded_rectangle(
            [card_x1, cy1, card_x2, cy2],
            radius=12,
            fill=(34, 25, 20, 228),
            outline=(182, 146, 94, 215),
            width=2,
        )
        d.rounded_rectangle(
            [card_x1 + 6, cy1 + 6, card_x2 - 6, cy2 - 6],
            radius=8,
            outline=(116, 90, 58, 140),
            width=1,
        )

        # Vertical question-type watermark on the right edge of the card
        wm_chars = list(hl.q_type)
        wm_x = card_x2 - 58
        wm_total_h = len(wm_chars) * 44
        wm_y0 = cy1 + (card_h - wm_total_h) / 2 - 4
        for ci, ch in enumerate(wm_chars):
            cb = d.textbbox((0, 0), ch, font=f_qtype)
            cw = cb[2] - cb[0]
            d.text(
                (wm_x + (38 - cw) / 2 - cb[0], wm_y0 + ci * 44),
                ch,
                font=f_qtype,
                fill=(188, 86, 66, 145),
            )
        # Subtle vertical divider before watermark
        d.line([(card_x2 - 74, cy1 + 24), (card_x2 - 74, cy2 - 24)], fill=(140, 108, 72, 95), width=1)

        # Question tag pill [第02题]
        tag_str = f"[{hl.tag}]"
        tb = d.textbbox((0, 0), tag_str, font=f_qtag)
        tx, ty = card_x1 + 24, cy1 + 26
        d.text((tx, ty), tag_str, font=f_qtag, fill=(238, 198, 134, 255))

        # Summary lines (max width up to card_x2 - 96)
        max_desc_w = (card_x2 - 92) - (card_x1 + 24)
        lines = _wrap_cjk_lines(d, hl.summary, f_qdesc, max_desc_w, max_lines=2)
        ly = ty + (tb[3] - tb[1]) + 22
        for ln in lines:
            d.text((card_x1 + 24, ly), ln, font=f_qdesc, fill=(242, 232, 212, 248))
            ly += 44

        card_y += card_h + card_gap

    # Bottom-left strength seal + text
    seal_x, seal_y = x_left, 1378
    d.rounded_rectangle([seal_x, seal_y, seal_x + 42, seal_y + 42], radius=6, fill=(162, 48, 36, 235), outline=(230, 186, 120, 210), width=2)
    f_seal = load_serif_font(26)
    sb_s = d.textbbox((0, 0), "评", font=f_seal)
    d.text((seal_x + 21 - (sb_s[2] - sb_s[0]) / 2 - sb_s[0], seal_y + 21 - (sb_s[3] - sb_s[1]) / 2 - sb_s[1]), "评", font=f_seal, fill=(248, 228, 196, 255))
    d.text((seal_x + 56, seal_y + 6), rec.strength, font=f_strength, fill=(236, 214, 174, 248))

    # 3. Center Monumental Standalone Numeric Polygon Radar Chart (0-100 scale, N-axis, 4x supersampled)
    n_axes = len(AXES)
    cx, cy = 1480, 838
    max_r = 370
    ss = 4
    half_box = 650
    bw = half_box * 2
    lcx, lcy = half_box * ss, half_box * ss
    lmax_r = max_r * ss

    rings = [
        ("100", 1.00, (236, 196, 126, 200)),
        ("80",  0.80, (220, 180, 115, 165)),
        ("60",  0.60, (186, 162, 128, 135)),
        ("40",  0.40, (166, 146, 116, 115)),
        ("20",  0.20, (146, 130, 106, 95)),
    ]

    grid_layer = Image.new("RGBA", (bw * ss, bw * ss), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid_layer, "RGBA")
    angles = [math.radians(-90 + 360 / n_axes * i) for i in range(n_axes)]

    outer_pts = [(lcx + lmax_r * math.cos(a), lcy + lmax_r * math.sin(a)) for a in angles]
    gd.polygon(outer_pts, fill=(18, 14, 11, 100))

    for a in angles:
        gd.line([(lcx, lcy), (lcx + lmax_r * math.cos(a), lcy + lmax_r * math.sin(a))], fill=(206, 178, 134, 125), width=2 * ss)

    for _, ratio, col in rings:
        r = lmax_r * ratio
        pts = [(lcx + r * math.cos(a), lcy + r * math.sin(a)) for a in angles]
        gd.polygon(pts, outline=col, width=2 * ss)

    # Corpus average baseline dashed polygon
    avg_pts = [
        (lcx + lmax_r * (avg_sc / 100.0) * math.cos(a), lcy + lmax_r * (avg_sc / 100.0) * math.sin(a))
        for a, avg_sc in zip(angles, corpus_avgs)
    ]
    _draw_dashed_polygon(gd, avg_pts, fill=(176, 198, 214, 185), width=3 * ss, dash=12 * ss, gap=9 * ss)

    axis_scores = rec.axis_scores
    poly_pts = [
        (
            lcx + lmax_r * (sc / 100.0) * math.cos(a),
            lcy + lmax_r * (sc / 100.0) * math.sin(a),
        )
        for a, sc in zip(angles, axis_scores)
    ]

    glow_layer = Image.new("RGBA", (bw * ss, bw * ss), (0, 0, 0, 0))
    glw = ImageDraw.Draw(glow_layer, "RGBA")
    glw.polygon(poly_pts, outline=(235, 162, 74, 200), width=16 * ss)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=11 * ss))

    poly_layer = Image.new("RGBA", (bw * ss, bw * ss), (0, 0, 0, 0))
    pd = ImageDraw.Draw(poly_layer, "RGBA")
    pd.polygon(poly_pts, fill=(218, 152, 70, 122))
    for i in range(n_axes):
        pd.line([poly_pts[i], poly_pts[(i + 1) % n_axes]], fill=(252, 214, 142, 250), width=5 * ss)

    for x, y in poly_pts:
        pd.ellipse((x - 16 * ss, y - 16 * ss, x + 16 * ss, y + 16 * ss), fill=(201, 74, 56, 175))
        pd.ellipse((x - 9 * ss, y - 9 * ss, x + 9 * ss, y + 9 * ss), fill=(255, 248, 234, 255))

    scale_font = load_sans_bold(19 * ss)
    bisect = math.radians(-90 + 180 / n_axes)
    cos_half = math.cos(math.pi / n_axes)
    for name, ratio, _ in rings:
        edge_r = lmax_r * ratio * cos_half
        lx = lcx + edge_r * math.cos(bisect)
        ly = lcy + edge_r * math.sin(bisect)
        bb = pd.textbbox((0, 0), name, font=scale_font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        tx, ty = lx - tw / 2 - bb[0], ly - th / 2 - bb[1]
        pd.text((tx + 2 * ss, ty + 2 * ss), name, font=scale_font, fill=(16, 11, 8, 235))
        pd.text((tx, ty), name, font=scale_font, fill=(244, 228, 196, 245))

    title_font = load_serif_font(33 * ss)
    score_font = load_sans_bold(26 * ss)
    pill_h = 44 * ss
    gap_tp = 12 * ss
    pad_r = 42 * ss
    for a, dim, sc in zip(angles, AXES, axis_scores):
        ux, uy = math.cos(a), math.sin(a)
        vx = lcx + lmax_r * ux
        vy = lcy + lmax_r * uy

        tb = pd.textbbox((0, 0), dim, font=title_font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        sc_txt = f"{sc:.1f}"
        gb = pd.textbbox((0, 0), sc_txt, font=score_font)
        gw, gh = gb[2] - gb[0], gb[3] - gb[1]
        pill_w = max(92 * ss, gw + 32 * ss)

        block_w = max(tw, pill_w)
        block_h = th + gap_tp + pill_h
        lbl_cx = vx + ux * (block_w / 2 + pad_r)
        lbl_cy = vy + uy * (block_h / 2 + pad_r)

        title_top = lbl_cy - block_h / 2
        pd.text((lbl_cx - tw / 2 - tb[0] + 2 * ss, title_top - tb[1] + 2 * ss), dim, font=title_font, fill=(14, 10, 7, 220))
        pd.text((lbl_cx - tw / 2 - tb[0], title_top - tb[1]), dim, font=title_font, fill=(244, 236, 216, 255))

        px1 = lbl_cx - pill_w / 2
        py1 = title_top + th + gap_tp
        if sc >= 92.0:
            fill_col, border_col, txt_col = (158, 52, 38, 228), (242, 198, 122, 245), (255, 242, 214, 255)
        elif sc >= 82.0:
            fill_col, border_col, txt_col = (58, 42, 28, 225), (232, 186, 110, 240), (248, 216, 152, 255)
        elif sc >= 68.0:
            fill_col, border_col, txt_col = (38, 30, 24, 218), (196, 168, 124, 215), (232, 214, 182, 255)
        else:
            fill_col, border_col, txt_col = (34, 38, 44, 222), (132, 154, 172, 205), (196, 214, 228, 248)

        pd.rounded_rectangle([px1, py1, px1 + pill_w, py1 + pill_h], radius=10 * ss, fill=fill_col, outline=border_col, width=2 * ss)
        pd.text((lbl_cx - gw / 2 - gb[0], py1 + (pill_h - gh) / 2 - gb[1]), sc_txt, font=score_font, fill=txt_col)

    radar_combined = Image.alpha_composite(grid_layer, glow_layer)
    radar_combined = Image.alpha_composite(radar_combined, poly_layer).resize((bw, bw), Image.Resampling.LANCZOS)
    overlay.alpha_composite(radar_combined, (cx - half_box, cy - half_box))

    # Subtle legend at bottom-right of radar chart for dashed corpus average line
    f_leg = load_serif_font(20)
    leg_x, leg_y = 1660, 1388
    d.line([(leg_x, leg_y + 12), (leg_x + 16, leg_y + 12)], fill=(176, 198, 214, 190), width=3)
    d.line([(leg_x + 24, leg_y + 12), (leg_x + 40, leg_y + 12)], fill=(176, 198, 214, 190), width=3)
    d.text((leg_x + 50, leg_y), f"全库 {rec.scored_count} 套常模线 (70.0)", font=f_leg, fill=(176, 198, 214, 200))

    # 4. Right Archival Engraving Frame (centered at x=2395, y=225..755)
    art_size = 530
    art_x1, art_y1 = 2130, 220
    # Drop shadow
    d.rounded_rectangle([art_x1 + 6, art_y1 + 8, art_x1 + art_size + 6, art_y1 + art_size + 8], radius=12, fill=(10, 7, 5, 160))
    # Mat & inner art
    resized_art = art_img.resize((art_size - 24, art_size - 24), Image.Resampling.LANCZOS)
    d.rounded_rectangle([art_x1, art_y1, art_x1 + art_size, art_y1 + art_size], radius=10, fill=(224, 206, 174, 255), outline=(172, 138, 92, 245), width=3)
    overlay.paste(resized_art.convert("RGBA"), (art_x1 + 12, art_y1 + 12))
    d.rectangle([art_x1 + 12, art_y1 + 12, art_x1 + art_size - 13, art_y1 + art_size - 13], outline=(108, 82, 54, 210), width=2)

    # 5. Right Province Chronological History (ALL sessions in region, sorted by year ascending!)
    strip_title = f"{rec.region}卷历年"
    st_b = d.textbbox((0, 0), strip_title, font=f_sec)
    d.text((2395 - (st_b[2] - st_b[0]) / 2, 792), strip_title, font=f_sec, fill=(244, 232, 208, 255))

    seats = rec.region_seats
    n_seats = len(seats)
    area_x1, area_x2 = 2105, 2685
    area_w = area_x2 - area_x1
    area_y1 = 858

    if n_seats <= 5:
        cols, rows = n_seats, 1
    elif n_seats <= 7:
        cols, rows = n_seats, 1
    elif n_seats <= 12:
        cols = math.ceil(n_seats / 2)
        rows = 2
    else:
        cols = 8
        rows = math.ceil(n_seats / cols)

    gap_x = 10 if cols <= 5 else (7 if cols <= 7 else 6)
    gap_y = 10
    card_w = (area_w - gap_x * (cols - 1)) / cols
    row_h = 195 if rows == 1 else (130 if rows == 2 else 102)

    f_yr = load_serif_font(28 if cols <= 5 else (23 if cols <= 7 else 19))
    f_yr_sub = load_serif_font(22 if cols <= 5 else (19 if cols <= 7 else 16))
    f_rk = load_serif_font(26 if cols <= 5 else (20 if rows >= 2 else (22 if cols <= 7 else 18)))

    for i, seat in enumerate(seats):
        r_idx = i // cols
        c_idx = i % cols
        # Center incomplete last row
        items_in_row = cols if (r_idx < rows - 1 or n_seats % cols == 0) else (n_seats % cols)
        row_total_w = items_in_row * card_w + (items_in_row - 1) * gap_x
        row_start_x = 2395 - row_total_w / 2

        sx1 = row_start_x + c_idx * (card_w + gap_x)
        sy1 = area_y1 + r_idx * (row_h + gap_y)
        sx2 = sx1 + card_w
        sy2 = sy1 + row_h

        is_cur = seat.paper_key == rec.paper_key
        if is_cur:
            fill_c = (242, 230, 204, 255)
            out_c = (188, 52, 38, 255)
            yr_c = (176, 42, 30, 255)
            rk_c = (176, 42, 30, 255)
            bw_line = 4
        else:
            fill_c = (212, 198, 174, 240)
            out_c = (128, 102, 72, 220)
            yr_c = (44, 34, 24, 255)
            rk_c = (66, 52, 38, 245) if seat.rank is not None else (110, 96, 80, 220)
            bw_line = 2

        d.rounded_rectangle([sx1, sy1, sx2, sy2], radius=8, fill=fill_c, outline=out_c, width=bw_line)
        if is_cur:
            d.rounded_rectangle([sx1 + 5, sy1 + 5, sx2 - 5, sy2 - 5], radius=5, outline=(202, 160, 92, 235), width=2)

        rkb = d.textbbox((0, 0), seat.badge_text, font=f_rk)
        rk_h = rkb[3] - rkb[1]
        if "\n" in seat.short_label:
            yr_part, sub_part = seat.short_label.split("\n", 1)
            yb1 = d.textbbox((0, 0), yr_part, font=f_yr)
            yb2 = d.textbbox((0, 0), sub_part, font=f_yr_sub)
            h1, h2 = yb1[3] - yb1[1], yb2[3] - yb2[1]
            total_txt_h = h1 + 6 + h2 + 12 + rk_h
            ty_top = sy1 + (row_h - total_txt_h) / 2
            d.text(((sx1 + sx2) / 2 - (yb1[2] - yb1[0]) / 2 - yb1[0], ty_top - yb1[1]), yr_part, font=f_yr, fill=yr_c)
            d.text(((sx1 + sx2) / 2 - (yb2[2] - yb2[0]) / 2 - yb2[0], ty_top + h1 + 6 - yb2[1]), sub_part, font=f_yr_sub, fill=yr_c)
            d.text(((sx1 + sx2) / 2 - (rkb[2] - rkb[0]) / 2 - rkb[0], ty_top + h1 + 6 + h2 + 12 - rkb[1]), seat.badge_text, font=f_rk, fill=rk_c)
        else:
            yb = d.textbbox((0, 0), seat.short_label, font=f_yr)
            total_txt_h = (yb[3] - yb[1]) + rk_h + 14
            ty_top = sy1 + (row_h - total_txt_h) / 2
            d.text(((sx1 + sx2) / 2 - (yb[2] - yb[0]) / 2 - yb[0], ty_top - yb[1]), seat.short_label, font=f_yr, fill=yr_c)
            d.text(((sx1 + sx2) / 2 - (rkb[2] - rkb[0]) / 2 - rkb[0], ty_top + (yb[3] - yb[1]) + 14 - rkb[1]), seat.badge_text, font=f_rk, fill=rk_c)

    # 6. Bottom-Right Rank Badge (TOP #N for <=20, RANK #N for 21+)
    prefix = "TOP " if rec.rank <= 20 else "RANK "
    num_txt = f"#{rec.rank}"
    b1 = d.textbbox((0, 0), prefix, font=f_top_badge)
    b2 = d.textbbox((0, 0), num_txt, font=f_top_badge)
    tot_w = (b1[2] - b1[0]) + (b2[2] - b2[0])
    bx = 2665 - tot_w
    by = 1320
    # Subtle drop shadow
    d.text((bx + 3, by + 3), prefix, font=f_top_badge, fill=(12, 8, 6, 200))
    d.text((bx, by), prefix, font=f_top_badge, fill=(238, 198, 134, 255))
    nx = bx + (b1[2] - b1[0]) + 4
    d.text((nx + 3, by + 3), num_txt, font=f_top_badge, fill=(12, 8, 6, 200))
    d.text((nx, by), num_txt, font=f_top_badge, fill=(196, 62, 46, 255))

    out_img = Image.alpha_composite(canvas, overlay).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(out_path, quality=98)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HistoryLTiV radar cards from project corpus.")
    parser.add_argument("--top", type=int, default=3, help="Generate Top N papers (default: 3).")
    parser.add_argument("--ranks", type=int, nargs="+", help="Specific ranks to render (e.g. --ranks 1 2 3 22).")
    parser.add_argument("--papers", type=str, nargs="+", help="Specific paper keys (e.g. '2024 山东' '2025 山东').")
    parser.add_argument("--out-dir", type=str, default="雷达图_14档Top3", help="Output directory relative to project root.")
    parser.add_argument("--credentials", type=str, default=str(DEFAULT_CREDENTIALS), help="GCP service account JSON path.")
    parser.add_argument("--no-ai", action="store_true", help="Skip Vertex AI calls if art not cached.")
    args = parser.parse_args()

    if not DESK_BASE_PATH.is_file():
        raise FileNotFoundError(f"Missing desk template: {DESK_BASE_PATH}")
    desk_base = Image.open(DESK_BASE_PATH)

    records, by_key, corpus_avgs = load_full_dataset()
    targets: list[PaperRecord] = []
    if args.papers:
        for pk in args.papers:
            norm = build_rank.key(pk)
            if norm not in by_key:
                raise KeyError(f"Paper not found in ranked corpus: {pk!r} (normalized: {norm!r})")
            targets.append(by_key[norm])
    elif args.ranks:
        for r in args.ranks:
            if not (1 <= r <= len(records)):
                raise IndexError(f"Rank out of range: {r} (1..{len(records)})")
            targets.append(records[r - 1])
    else:
        targets = records[: args.top]

    out_dir = Path(args.out_dir) if Path(args.out_dir).is_absolute() else (ROOT / args.out_dir)
    cred = Path(args.credentials) if args.credentials else None

    for rec in targets:
        art = get_or_generate_art(rec, cred, use_ai=not args.no_ai)
        safe_title = rec.title.replace("/", "-")
        fname = f"TOP{rec.rank}_{safe_title}_{rec.score:.1f}.png"
        out_path = out_dir / fname
        render_card(rec, corpus_avgs, desk_base, art, out_path)
        print(f"Rendered #{rec.rank}/{rec.total_available} {rec.title} -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
