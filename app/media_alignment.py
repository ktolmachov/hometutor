"""Выравнивание разделов конспекта по таймкодам ASR-сегментов (anchor + weighted LIS).

Вход: разделы из :func:`app.section_index.parse_sections` и сегменты транскрипта
``[{start, end, text}]`` (см. ``scripts/transcribe_media.py``). Выход — таймкоды
``t_start/t_end`` и ``confidence`` на раздел, детерминированно и без LLM.

Алгоритм ``anchor-lis-v1`` (устойчив к видео 4–5 часов):

1. Сегменты группируются в блоки ~фиксированного лексического объёма.
2. Slide-aware якорение: явное «слайд N» в речи или дословное чтение заголовка
   слайда → сильное свидетельство (confidence 0.75–0.90); при отсутствии номеров
   в транскрипте — order-rank по хронологии cue-моментов и порядку слайдов.
3. Каждый содержательный раздел без slide-якоря получает блок-кандидат (argmax
   лексического перекрытия ``tokenize_filtered`` по токенам заголовка И тела).
4. Взвешенный LIS по (порядок раздела, индекс блока) отбрасывает якоря,
   ломающие хронологию лекции.
5. Разделы без якоря интерполируются между соседними якорями по их
   уточнённым временам и помечаются низким confidence (< 0.70).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.knowledge_text import tokenize_filtered
from app.section_index import ParsedSection

ALIGNMENT_VERSION = "anchor-lis-v1"
SEGMENTS_SCHEMA_VERSION = 1

_BLOCK_TOKEN_TARGET = 120  # лексический объём блока (≈30–60 сек речи)
_MIN_SECTION_TOKENS = 8  # разделы короче не якорим — только интерполяция
_MIN_ANCHOR_SCORE = 0.18  # ниже — совпадение считается шумом
_INTERPOLATED_CONFIDENCE = 0.40  # < low_confidence-порога сайдкара (0.70)
_MAX_ANCHOR_CONFIDENCE = 0.99

# Slide-aware anchoring
_SLIDE_HEADING_NUM_RE = re.compile(
    r"сла[йдею][де]?\s*№?\s*(\d+)|"
    r"slide\s*(\d+)|"
    r"слайды?\s*(\d+)\s*[-–—]\s*(\d+)",
    re.IGNORECASE,
)
_SLIDE_CUE_NUM_RE = re.compile(
    r"сла[йдею][де]?\s*№?\s*(\d+)|slide\s*(\d+)|(\d+)[-\s]*(?:й|ый|ой|ая|ое)\s*слайд",
    re.IGNORECASE,
)
_SLIDE_TITLE_PREFIX_RE = re.compile(
    r"^(?:сла[йдею][де]?\s*№?\s*\d+(?:\s*[-–—]\s*\d+)?|slide\s*\d+)\s*:?\s*",
    re.IGNORECASE,
)
_SLIDE_DIRECT_CONFIDENCE = 0.90
_SLIDE_ORDER_CONFIDENCE = 0.75
_SLIDE_TITLE_STRONG_SCORE = 0.70
_SLIDE_TITLE_MIN_SCORE = 0.55
_SLIDE_TITLE_ORDER_MIN_SCORE = 0.40
_SLIDE_CUE_LIS_WEIGHT = 100.0
_GENERIC_HEADING_TITLES = frozenset(
    {
        "суть",
        "почему это важно",
        "как применять",
        "оглавление",
        "главная мысль",
        "карта лекции",
        "прямо сейчас",
        "на этой неделе",
        "мини-проект",
        "мини-шпаргалка",
        "контрольные вопросы",
        "что нужно сделать",
        "для команды продукта",
        "примеры из лекции",
        "схемы и модели",
    }
)


def _anchor_confidence(score: float) -> float:
    """Калибровка сырого перекрытия в confidence сайдкара.

    Полного перекрытия (1.0) не бывает даже у идеального якоря: раздел —
    конспект речи, а не её копия. Реальные переработанные конспекты дают
    overlap ~0.20–0.30. Формула 0.55 + 0.75·score: score=0.20 → 0.70 (порог
    UI «confident»), score=0.40 → 0.85, score=0.60 → 1.0 (cap 0.99).
    """
    return round(min(0.55 + 0.75 * score, _MAX_ANCHOR_CONFIDENCE), 3)


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SegmentsFile:
    media_sha256: str | None
    asr_model: str | None
    language: str | None
    asr_params: dict | None
    segments: tuple[TranscriptSegment, ...]


@dataclass(frozen=True)
class AlignedSection:
    section: ParsedSection
    t_start: float | None
    t_end: float | None
    confidence: float
    anchored: bool


def compute_section_id(section: ParsedSection) -> str:
    """Стабильный id раздела: sha256 от нормализованного заголовка + own_text."""
    material = "\n".join(
        [
            section.heading_text.strip().lower(),
            " ".join(sorted(tokenize_filtered(section.own_text or section.text))),
        ]
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def load_segments_file(path: Path) -> SegmentsFile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SEGMENTS_SCHEMA_VERSION:
        raise ValueError(f"unsupported segments schema_version: {payload.get('schema_version')!r}")
    asr = payload.get("asr") or {}
    segments: list[TranscriptSegment] = []
    for i, raw in enumerate(payload.get("segments") or []):
        start, end = float(raw["start"]), float(raw["end"])
        if end < start:
            raise ValueError(f"segments[{i}]: end < start")
        segments.append(TranscriptSegment(start=start, end=end, text=str(raw.get("text") or "")))
    if any(b.start < a.start for a, b in zip(segments, segments[1:])):
        raise ValueError("segments must be sorted by start time")
    params = asr.get("params")
    return SegmentsFile(
        media_sha256=payload.get("media_sha256"),
        asr_model=asr.get("model"),
        language=asr.get("language"),
        asr_params=params if isinstance(params, dict) else None,
        segments=tuple(segments),
    )


# ── Блоки ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Block:
    t_start: float
    t_end: float
    tokens: frozenset[str]
    seg_lo: int  # индексы сегментов блока — для уточнения t_start внутри блока
    seg_hi: int


def _build_blocks(segments: tuple[TranscriptSegment, ...]) -> list[_Block]:
    blocks: list[_Block] = []
    tokens: set[str] = set()
    t_start: float | None = None
    t_end = 0.0
    seg_lo = 0
    for idx, seg in enumerate(segments):
        if t_start is None:
            t_start, seg_lo = seg.start, idx
        tokens |= tokenize_filtered(seg.text)
        t_end = seg.end
        if len(tokens) >= _BLOCK_TOKEN_TARGET:
            blocks.append(_Block(t_start=t_start, t_end=t_end, tokens=frozenset(tokens), seg_lo=seg_lo, seg_hi=idx))
            tokens, t_start = set(), None
    if t_start is not None and tokens:
        blocks.append(
            _Block(t_start=t_start, t_end=t_end, tokens=frozenset(tokens), seg_lo=seg_lo, seg_hi=len(segments) - 1)
        )
    return blocks


def _background_tokens(blocks: list[_Block]) -> frozenset[str]:
    """Токены-фон: звучат в большинстве блоков лекции (общие термины, слова-связки).

    Они не различают темы, но пересекаются с любым разделом — без фильтра якорь
    «прилипает» к чужому блоку, а уточнение t_start — к первому попавшемуся сегменту.
    """
    if len(blocks) < 4:
        return frozenset()
    counts: dict[str, int] = {}
    for block in blocks:
        for token in block.tokens:
            counts[token] = counts.get(token, 0) + 1
    threshold = len(blocks) / 2
    return frozenset(t for t, n in counts.items() if n > threshold)


def _refine_t_start(
    tokens: frozenset[str], block: _Block, segments: tuple[TranscriptSegment, ...]
) -> float:
    """Начало — не блок целиком, а первый его сегмент с различительной лексикой раздела."""
    for idx in range(block.seg_lo, block.seg_hi + 1):
        if tokens & tokenize_filtered(segments[idx].text):
            return segments[idx].start
    return block.t_start


def _overlap_score(section_tokens: frozenset[str], block: _Block) -> float:
    if not section_tokens or not block.tokens:
        return 0.0
    hit = len(section_tokens & block.tokens)
    return hit / min(len(section_tokens), len(block.tokens))


# ── Slide-aware anchoring ────────────────────────────────────────────────


def _slide_number_from_heading(heading_text: str) -> int | None:
    match = _SLIDE_HEADING_NUM_RE.search(heading_text)
    if not match:
        return None
    return int(match.group(1) or match.group(2) or match.group(3))


def _slide_title_from_heading(heading_text: str) -> str:
    title = _SLIDE_TITLE_PREFIX_RE.sub("", heading_text).strip(' "«»')
    return title


def _normalize_heading_for_title_read(heading_text: str) -> str:
    text = re.sub(r"^[^\w#]+", "", heading_text.strip())
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^[\d.]+\s*", "", text)
    return text.strip()


def _heading_title_tokens(heading_text: str) -> tuple[str, ...]:
    """Токены заголовка для title-reading; пусто для общеупотребимых H4."""
    normalized = " ".join(_normalize_heading_for_title_read(heading_text).lower().split())
    if normalized in _GENERIC_HEADING_TITLES:
        return ()
    tokens = tuple(t for t in tokenize_filtered(_normalize_heading_for_title_read(heading_text)) if len(t) > 3)
    return tokens


def _title_read_score(title_tokens: tuple[str, ...], segment_text: str) -> float:
    if not title_tokens:
        return 0.0
    seg_tokens = tokenize_filtered(segment_text)
    hit = len(set(title_tokens) & set(seg_tokens))
    return hit / len(title_tokens)


def _block_idx_for_seg(blocks: list[_Block], seg_idx: int) -> int:
    for i, block in enumerate(blocks):
        if block.seg_lo <= seg_idx <= block.seg_hi:
            return i
    return max(0, len(blocks) - 1)


def _detect_spoken_slide_numbers(
    segments: tuple[TranscriptSegment, ...],
) -> dict[int, tuple[int, float]]:
    """Первое упоминание каждого номера слайда в транскрипте."""
    cues: dict[int, tuple[int, float]] = {}
    for idx, seg in enumerate(segments):
        for match in _SLIDE_CUE_NUM_RE.finditer(seg.text):
            num = int(match.group(1) or match.group(2) or match.group(3))
            if num not in cues:
                cues[num] = (idx, seg.start)
    return cues


@dataclass(frozen=True)
class _SlideCue:
    slide_num: int | None
    seg_idx: int
    t_start: float
    title_score: float


def _detect_slide_title_cues(
    segments: tuple[TranscriptSegment, ...],
    slide_sections: list[tuple[int, int, str]],
) -> list[_SlideCue]:
    """Title-reading: слайды по номеру, сегменты только вперёд по хронологии."""
    cues: list[_SlideCue] = []
    seg_cursor = 0
    for pos, slide_num, heading in sorted(slide_sections, key=lambda item: item[1]):
        title_tokens = _heading_title_tokens(_slide_title_from_heading(heading))
        if not title_tokens:
            continue
        best_idx = -1
        best_score = 0.0
        for idx in range(seg_cursor, len(segments)):
            score = _title_read_score(title_tokens, segments[idx].text)
            if score > best_score:
                best_score = score
                best_idx = idx
            if score >= _SLIDE_TITLE_STRONG_SCORE:
                break
        if best_idx < 0 or best_score < _SLIDE_TITLE_MIN_SCORE:
            continue
        seg_cursor = best_idx + 1
        cues.append(
            _SlideCue(
                slide_num=slide_num,
                seg_idx=best_idx,
                t_start=segments[best_idx].start,
                title_score=best_score,
            )
        )
    return cues


def _slide_confidence(*, direct_number: bool, title_score: float, order_rank: bool) -> float:
    if direct_number or title_score >= _SLIDE_TITLE_STRONG_SCORE:
        return _SLIDE_DIRECT_CONFIDENCE
    if order_rank:
        return _SLIDE_ORDER_CONFIDENCE
    return _SLIDE_ORDER_CONFIDENCE if title_score >= _SLIDE_TITLE_MIN_SCORE else _INTERPOLATED_CONFIDENCE


def _slide_time_windows(
    slide_sections: list[tuple[int, int, str]],
    anchors: dict[int, tuple[int, float, float]],
    media_end: float,
) -> dict[int, tuple[float, float]]:
    nums = sorted(slide_num for pos, slide_num, _ in slide_sections if pos in anchors)
    windows: dict[int, tuple[float, float]] = {}
    for i, num in enumerate(nums):
        pos = next(p for p, sn, _ in slide_sections if sn == num and p in anchors)
        t_lo = anchors[pos][2]
        if i + 1 < len(nums):
            next_pos = next(p for p, sn, _ in slide_sections if sn == nums[i + 1] and p in anchors)
            t_hi = anchors[next_pos][2]
        else:
            t_hi = media_end
        windows[num] = (t_lo, t_hi)
    return windows


def _best_slide_for_heading(
    heading_text: str,
    slide_sections: list[tuple[int, int, str]],
) -> tuple[int, float] | None:
    tokens = _heading_title_tokens(heading_text)
    if not tokens:
        return None
    best_num: int | None = None
    best_overlap = 0.0
    for _pos, slide_num, slide_heading in slide_sections:
        slide_tokens = _heading_title_tokens(_slide_title_from_heading(slide_heading))
        if not slide_tokens:
            continue
        overlap = len(set(tokens) & set(slide_tokens)) / min(len(tokens), len(slide_tokens))
        if overlap > best_overlap:
            best_overlap = overlap
            best_num = slide_num
    if best_num is None or best_overlap < 0.15:
        return None
    return best_num, best_overlap


def _detect_windowed_heading_cues(
    segments: tuple[TranscriptSegment, ...],
    sections: list[ParsedSection],
    blocks: list[_Block],
    *,
    slide_sections: list[tuple[int, int, str]],
    anchors: dict[int, tuple[int, float, float]],
) -> dict[int, tuple[int, float, float]]:
    """Title-reading в окне слайда, к которому тематически привязан раздел."""
    if len(anchors) < 2:
        return {}
    media_end = segments[-1].end if segments else float("inf")
    windows = _slide_time_windows(slide_sections, anchors, media_end)
    heading_anchors: dict[int, tuple[int, float, float]] = {}
    for pos, section in enumerate(sections):
        if pos in anchors or _slide_number_from_heading(section.heading_text):
            continue
        if section.level >= 5:
            continue
        title_tokens = _heading_title_tokens(section.heading_text)
        if len(title_tokens) < 2:
            continue
        mapped = _best_slide_for_heading(section.heading_text, slide_sections)
        if mapped is None:
            t_lo, t_hi = 0.0, media_end
            min_score = 0.50
        else:
            slide_num, _overlap = mapped
            t_lo, t_hi = windows.get(slide_num, (0.0, media_end))
            min_score = 0.35
        best_idx = -1
        best_score = 0.0
        for idx, seg in enumerate(segments):
            if not (t_lo <= seg.start <= t_hi):
                continue
            score = _title_read_score(title_tokens, seg.text)
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx < 0 or best_score < min_score:
            continue
        heading_anchors[pos] = (
            _block_idx_for_seg(blocks, best_idx),
            _slide_confidence(direct_number=False, title_score=best_score, order_rank=best_score < _SLIDE_TITLE_STRONG_SCORE),
            segments[best_idx].start,
        )
    return heading_anchors


def _windowed_slide_match(
    unmatched: list[tuple[int, int, str]],
    segments: tuple[TranscriptSegment, ...],
    blocks: list[_Block],
    *,
    anchors_by_num: dict[int, tuple[int, float, float]],
) -> dict[int, tuple[int, float, float]]:
    """Поиск title-cue в временном окне между соседними якоренными слайдами."""
    if not unmatched or len(anchors_by_num) < 2:
        return {}
    media_end = segments[-1].end if segments else float("inf")
    anchored_nums = sorted(anchors_by_num)
    anchors: dict[int, tuple[int, float, float]] = {}
    for pos, slide_num, heading in unmatched:
        prev_nums = [num for num in anchored_nums if num < slide_num]
        next_nums = [num for num in anchored_nums if num > slide_num]
        t_lo = anchors_by_num[prev_nums[-1]][2] if prev_nums else 0.0
        t_hi = anchors_by_num[next_nums[0]][2] if next_nums else media_end
        title_tokens = _heading_title_tokens(_slide_title_from_heading(heading))
        if not title_tokens:
            continue
        best_idx = -1
        best_score = 0.0
        for idx, seg in enumerate(segments):
            if not (t_lo <= seg.start <= t_hi):
                continue
            score = _title_read_score(title_tokens, seg.text)
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx < 0 or best_score < _SLIDE_TITLE_ORDER_MIN_SCORE:
            continue
        anchors[pos] = (
            _block_idx_for_seg(blocks, best_idx),
            _slide_confidence(direct_number=False, title_score=best_score, order_rank=True),
            segments[best_idx].start,
        )
    return anchors


def _build_slide_anchors(
    sections: list[ParsedSection],
    segments: tuple[TranscriptSegment, ...],
    blocks: list[_Block],
) -> dict[int, tuple[int, float, float]]:
    """pos -> (block_idx, confidence, t_start) для slide-aware якорей."""
    slide_sections = [
        (pos, num, section.heading_text)
        for pos, section in enumerate(sections)
        if (num := _slide_number_from_heading(section.heading_text)) is not None
    ]
    if not slide_sections:
        return {}

    spoken_nums = _detect_spoken_slide_numbers(segments)
    title_cues = _detect_slide_title_cues(segments, slide_sections)
    anchors: dict[int, tuple[int, float, float]] = {}

    for pos, slide_num, _heading in slide_sections:
        if slide_num in spoken_nums:
            seg_idx, t_start = spoken_nums[slide_num]
            anchors[pos] = (
                _block_idx_for_seg(blocks, seg_idx),
                _SLIDE_DIRECT_CONFIDENCE,
                t_start,
            )

    title_by_num = {cue.slide_num: cue for cue in title_cues if cue.slide_num is not None}
    for pos, slide_num, _heading in slide_sections:
        if pos in anchors:
            continue
        cue = title_by_num.get(slide_num)
        if cue is None:
            continue
        anchors[pos] = (
            _block_idx_for_seg(blocks, cue.seg_idx),
            _slide_confidence(direct_number=False, title_score=cue.title_score, order_rank=False),
            cue.t_start,
        )

    unmatched = [
        (pos, slide_num, heading)
        for pos, slide_num, heading in slide_sections
        if pos not in anchors
    ]
    anchors_by_num = {
        slide_num: anchors[pos]
        for pos, slide_num, _ in slide_sections
        if pos in anchors
    }
    anchors.update(_windowed_slide_match(unmatched, segments, blocks, anchors_by_num=anchors_by_num))

    anchors.update(
        _detect_windowed_heading_cues(
            segments,
            sections,
            blocks,
            slide_sections=slide_sections,
            anchors=anchors,
        )
    )
    return anchors


# ── Взвешенный LIS по индексам блоков ───────────────────────────────────


def _weighted_lis(
    anchors: list[tuple[int, int, float]],
    *,
    prefer_later_section_on_tie: bool = False,
) -> set[int]:
    """anchors: (section_pos, block_idx, score) в порядке section_pos.

    Возвращает section_pos-ы максимального по суммарному score подмножества
    с неубывающими block_idx (хронология лекции).
    """
    n = len(anchors)
    if n == 0:
        return set()
    best = [a[2] for a in anchors]
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if anchors[j][1] <= anchors[i][1] and best[j] + anchors[i][2] > best[i]:
                best[i] = best[j] + anchors[i][2]
                prev[i] = j
    if prefer_later_section_on_tie:
        tail = max(range(n), key=lambda i: (best[i], anchors[i][0]))
    else:
        tail = max(range(n), key=lambda i: best[i])
    keep: set[int] = set()
    while tail != -1:
        keep.add(anchors[tail][0])
        tail = prev[tail]
    return keep


def _seg_idx_at_time(segments: tuple[TranscriptSegment, ...], t_start: float) -> int:
    for idx, seg in enumerate(segments):
        if abs(seg.start - t_start) < 0.01:
            return idx
    return max(range(len(segments)), key=lambda i: segments[i].start if segments[i].start <= t_start else -1)


def _filter_slide_anchors_by_lis(
    slide_anchor_by_pos: dict[int, tuple[int, float, float]],
    segments: tuple[TranscriptSegment, ...],
) -> dict[int, tuple[int, float, float]]:
    """LIS по seg_idx: отбрасывает slide-cue, ломающие хронологию (recap, ASR-шум)."""
    if not slide_anchor_by_pos:
        return {}
    lis_input = [
        (pos, _seg_idx_at_time(segments, slide_anchor_by_pos[pos][2]), _SLIDE_CUE_LIS_WEIGHT)
        for pos in sorted(slide_anchor_by_pos)
    ]
    kept = _weighted_lis(lis_input, prefer_later_section_on_tie=True)
    return {pos: slide_anchor_by_pos[pos] for pos in kept}


# ── Публичное выравнивание ──────────────────────────────────────────────


def align_sections(
    sections: list[ParsedSection], segments: tuple[TranscriptSegment, ...]
) -> list[AlignedSection]:
    """Детерминированное выравнивание разделов по сегментам транскрипта."""
    blocks = _build_blocks(segments)
    if not blocks:
        return [
            AlignedSection(section=s, t_start=None, t_end=None, confidence=0.0, anchored=False)
            for s in sections
        ]

    slide_anchor_by_pos = _filter_slide_anchors_by_lis(
        _build_slide_anchors(sections, segments, blocks),
        segments,
    )

    background = _background_tokens(blocks)
    scoring_blocks = [
        _Block(
            t_start=b.t_start, t_end=b.t_end, tokens=frozenset(b.tokens - background),
            seg_lo=b.seg_lo, seg_hi=b.seg_hi,
        )
        for b in blocks
    ]
    spoken_tokens = frozenset().union(*[b.tokens for b in blocks]) if blocks else frozenset()

    block_floor_by_pos: dict[int, int] = {}
    floor = 0
    for pos, _section in enumerate(sections):
        block_floor_by_pos[pos] = floor
        if pos in slide_anchor_by_pos:
            floor = slide_anchor_by_pos[pos][0]

    section_tokens: dict[int, frozenset[str]] = {}
    candidates: list[tuple[int, int, float]] = []
    for pos, section in enumerate(sections):
        if pos in slide_anchor_by_pos:
            block_idx, _conf, _t = slide_anchor_by_pos[pos]
            candidates.append((pos, block_idx, _SLIDE_CUE_LIS_WEIGHT))
            continue
        body_tokens = tokenize_filtered(section.own_text or section.text)
        heading_tokens = tokenize_filtered(section.heading_text) & spoken_tokens
        tokens = frozenset((body_tokens | heading_tokens) - background)
        if len(tokens) < _MIN_SECTION_TOKENS:
            continue
        section_tokens[pos] = tokens
        scores = [_overlap_score(tokens, block) for block in scoring_blocks]
        min_block = block_floor_by_pos[pos] if slide_anchor_by_pos else 0
        eligible = range(min_block, len(blocks))
        block_idx = max(eligible, key=lambda i: scores[i])
        if scores[block_idx] >= _MIN_ANCHOR_SCORE:
            candidates.append((pos, block_idx, scores[block_idx]))

    kept = _weighted_lis(candidates)
    anchor_by_pos: dict[int, tuple[int, float]] = {}
    anchor_t_start: dict[int, float] = {}
    for pos, blk, score in candidates:
        if pos not in kept:
            continue
        if pos in slide_anchor_by_pos:
            block_idx, confidence, t_start = slide_anchor_by_pos[pos]
            anchor_by_pos[pos] = (block_idx, confidence)
            anchor_t_start[pos] = round(t_start, 2)
        else:
            anchor_by_pos[pos] = (blk, score)
    anchored_positions = sorted(anchor_by_pos)

    for pos in anchored_positions:
        if pos in anchor_t_start:
            continue
        block_idx, _score = anchor_by_pos[pos]
        anchor_t_start[pos] = round(_refine_t_start(section_tokens[pos], blocks[block_idx], segments), 2)

    aligned: list[AlignedSection] = []
    for pos, section in enumerate(sections):
        if pos in anchor_by_pos:
            block_idx, score_or_conf = anchor_by_pos[pos]
            block = blocks[block_idx]
            if pos in slide_anchor_by_pos:
                confidence = slide_anchor_by_pos[pos][1]
            else:
                confidence = _anchor_confidence(score_or_conf)
            aligned.append(
                AlignedSection(
                    section=section,
                    t_start=anchor_t_start[pos],
                    t_end=round(block.t_end, 2),
                    confidence=confidence,
                    anchored=True,
                )
            )
            continue
        t_interp = _interpolate(pos, anchored_positions, anchor_t_start)
        aligned.append(
            AlignedSection(
                section=section,
                t_start=t_interp,
                t_end=None,
                confidence=_INTERPOLATED_CONFIDENCE if t_interp is not None else 0.0,
                anchored=False,
            )
        )

    aligned = _clamp_monotonic(aligned)
    return _stretch_ends(aligned, segments)


def _interpolate(
    pos: int,
    anchored_positions: list[int],
    anchor_t_start: dict[int, float],
) -> float | None:
    prev_pos = max((p for p in anchored_positions if p < pos), default=None)
    next_pos = min((p for p in anchored_positions if p > pos), default=None)
    if prev_pos is None or next_pos is None:
        return None  # край без обеих опор — честнее не выдумывать таймкод
    t_prev = anchor_t_start[prev_pos]
    t_next = anchor_t_start[next_pos]
    frac = (pos - prev_pos) / (next_pos - prev_pos)
    return round(t_prev + (t_next - t_prev) * frac, 2)


def _clamp_monotonic(aligned: list[AlignedSection]) -> list[AlignedSection]:
    out: list[AlignedSection] = []
    floor: float | None = None
    for item in aligned:
        if item.t_start is None:
            out.append(item)
            continue
        t_start = item.t_start if floor is None else max(item.t_start, floor)
        floor = t_start
        if t_start == item.t_start:
            out.append(item)
        else:
            out.append(
                AlignedSection(
                    section=item.section,
                    t_start=t_start,
                    t_end=item.t_end,
                    confidence=item.confidence,
                    anchored=item.anchored,
                )
            )
    return out


def _stretch_ends(
    aligned: list[AlignedSection], segments: tuple[TranscriptSegment, ...]
) -> list[AlignedSection]:
    media_end = segments[-1].end if segments else None
    out: list[AlignedSection] = []
    for i, item in enumerate(aligned):
        if item.t_start is None:
            out.append(item)
            continue
        next_start = next(
            (a.t_start for a in aligned[i + 1 :] if a.t_start is not None and a.t_start > item.t_start),
            None,
        )
        t_end = next_start if next_start is not None else (media_end or item.t_end)
        out.append(
            AlignedSection(
                section=item.section,
                t_start=item.t_start,
                t_end=round(t_end, 2) if t_end is not None else None,
                confidence=item.confidence,
                anchored=item.anchored,
            )
        )
    return out
