"""기록 집계, 시간대 흐름, Obsidian 일지용 markdown. UI 의존 없음."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .rules import CODE, EXCLUDED, UNKNOWN, ActivityKey, Rule, load_default_rules, resolve

EMPTY_TEXT = "기록된 활동이 없습니다."
OTHER_BUCKET = "기타"


def fmt_duration(seconds: float) -> str:
    minutes = int((seconds + 30) // 60)
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m:02d}분" if h else f"{m}분"


def _parse(v) -> datetime | None:
    try:
        return datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def activity_of(rec: dict, rules: list[Rule]) -> ActivityKey | None:
    """기록 한 줄 -> 활동 키. idle(자리 비움, 잠금, 절전, 일시 정지)이면 None."""
    if rec.get("idle"):
        return None
    if rec.get("excluded"):
        return ActivityKey(EXCLUDED, EXCLUDED)
    return resolve(str(rec.get("proc") or UNKNOWN), str(rec.get("title") or ""), rules)


def _spans(records, rules, now):
    """(start, end, key) 활동 구간. 시간순, 겹침은 뒤 기록이 앞을 자른다."""
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        s, e = _parse(rec.get("start")), _parse(rec.get("end"))
        if s is None or e is None:
            continue
        if now is not None and e > now:
            e = now
        if e <= s:
            continue
        key = activity_of(rec, rules)
        if key is not None:
            out.append((s, e, key))
    out.sort(key=lambda x: x[0])
    fixed = []
    for s, e, k in out:
        if fixed and s < fixed[-1][1]:
            ps, pe, pk = fixed[-1]
            fixed[-1] = (ps, s, pk)
            if s <= ps:
                fixed.pop()
        fixed.append((s, e, k))
    return fixed


def _group_key(k: ActivityKey) -> tuple[str, str]:
    return (k.category, k.target)


def build_summary(records, config: dict, now: datetime | None = None,
                  rules: list[Rule] | None = None) -> str:
    """기록만 넣으면 요약 markdown을 돌려준다. now 이후 시각은 잘라낸다."""
    if rules is None:
        rules = load_default_rules()
    min_item = float(config.get("min_minutes_for_item", 5)) * 60
    block_min = max(1, int(config.get("timeline_block_minutes", 15)))
    top_files = int(config.get("code_top_files", 3))

    spans = _spans(records, rules, now)
    if not spans:
        return EMPTY_TEXT

    # ---- 활동별 누적 ---------------------------------------------------
    totals: dict[tuple[str, str], float] = defaultdict(float)
    files: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for s, e, k in spans:
        sec = (e - s).total_seconds()
        g = _group_key(k)
        totals[g] += sec
        if k.category == CODE and k.file:
            files[g][k.file] += sec

    total = sum(totals.values())
    first, last = spans[0][0], max(e for _, e, _ in spans)

    items, other = [], 0.0
    for g, sec in totals.items():
        if sec < min_item:
            other += sec
        else:
            items.append((g, sec))
    items.sort(key=lambda x: (-x[1], x[0]))

    lines = [f"### 오늘의 브이로그 ({first:%H:%M} ~ {last:%H:%M}, 활동 {fmt_duration(total)})"]
    for g, sec in items:
        cat, target = g
        label = EXCLUDED if cat == EXCLUDED else f"{cat}: {target}"
        if cat == CODE and files.get(g) and top_files > 0:
            ranked = sorted(files[g].items(), key=lambda x: (-x[1], x[0]))[:top_files]
            label += " (" + ", ".join(f for f, _ in ranked) + ")"
        lines.append(f"- {label} : {fmt_duration(sec)}")
    if other > 0:
        lines.append(f"- {OTHER_BUCKET} : {fmt_duration(other)}")

    # ---- 흐름 ----------------------------------------------------------
    flow = build_flow(spans, block_min)
    if flow:
        lines += ["", "#### 흐름"]
        lines += [f"- {s:%H:%M} ~ {e:%H:%M} : {', '.join(labels)}" for s, e, labels in flow]
    return "\n".join(lines) + "\n"


def _flow_label(g: tuple[str, str]) -> str:
    cat, target = g
    return EXCLUDED if cat == EXCLUDED else f"{cat} {target}"


def build_flow(spans, block_minutes: int):
    """15분(설정값) 블록별 주 활동. 같은 내용이 이어지는 블록은 합친다. idle만 있는 블록은 생략."""
    step = timedelta(minutes=block_minutes)
    blocks: dict[datetime, dict[tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
    for s, e, k in spans:
        g = _group_key(k)
        midnight = s.replace(hour=0, minute=0, second=0, microsecond=0)
        b = midnight + step * ((s - midnight) // step)
        cur = s
        while cur < e:
            b_end = b + step
            seg_end = min(e, b_end)
            blocks[b][g] += (seg_end - cur).total_seconds()
            cur, b = seg_end, b_end

    merged: list[list] = []  # [start, end, frozenset(groups), {group: sec}]
    for b in sorted(blocks):
        usage = blocks[b]
        ranked = sorted(usage.items(), key=lambda x: (-x[1], x[0]))
        main = [ranked[0]]
        if len(ranked) > 1 and ranked[1][1] * 3 >= ranked[0][1]:
            main.append(ranked[1])
        keyset = frozenset(g for g, _ in main)
        if merged and merged[-1][1] == b and merged[-1][2] == keyset:
            merged[-1][1] = b + step
            for g, sec in main:
                merged[-1][3][g] += sec
        else:
            merged.append([b, b + step, keyset, defaultdict(float, main)])

    out = []
    for s, e, _, secs in merged:
        ordered = sorted(secs.items(), key=lambda x: (-x[1], x[0]))
        out.append((s, e, [_flow_label(g) for g, _ in ordered]))
    return out
