"""Выравнивание разделов конспекта по таймкодам ASR-сегментов (anchor + weighted LIS).

Вход: разделы из :func:`app.section_index.parse_sections` и сегменты транскрипта
``[{start, end, text}]`` (см. ``scripts/transcribe_media.py``). Выход — таймкоды
``t_start/t_end`` и ``confidence`` на раздел, детерминированно и без LLM.

Алгоритм ``anchor-lis-v1`` (устойчив к видео 4–5 часов):

1. Сегменты группируются в блоки ~фиксированного лексического объёма.
2. Каждый содержательный раздел получает блок-кандидат (argmax лексического
   перекрытия ``tokenize_filtered`` по токенам заголовка И тела — заголовок
   сильнейший сигнал, особенно для слайдовых конспектов).
3. Взвешенный LIS по (порядок раздела, индекс блока) отбрасывает якоря,
   ломающие хронологию лекции.
4. Разделы без якоря интерполируются между соседними якорями по их
   уточнённым временам (старт сегмента с различительной лексикой, не граница
   блока) и помечаются низким confidence (< 0.70 → UI показывает «неуверенно»).
"""

from __future__ import annotations

import hashlib
import json
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


def _anchor_confidence(score: float) -> float:
    """Калибровка сырого перекрытия в confidence сайдкара.

    Полного перекрытия (1.0) не бывает даже у идеального якоря: раздел —
    конспект речи, а не её копия. Якорь, переживший LIS-проверку хронологии, —
    сильное свидетельство, поэтому шкала 0.5 + 0.5·score: слабые якоря
    (score ~0.2) остаются под UI-порогом «неуверенно» (0.70), уверенные — над ним.
    """
    return round(min(0.5 + 0.5 * score, _MAX_ANCHOR_CONFIDENCE), 3)


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


# ── Взвешенный LIS по индексам блоков ───────────────────────────────────


def _weighted_lis(anchors: list[tuple[int, int, float]]) -> set[int]:
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
    tail = max(range(n), key=lambda i: best[i])
    keep: set[int] = set()
    while tail != -1:
        keep.add(anchors[tail][0])
        tail = prev[tail]
    return keep


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

    background = _background_tokens(blocks)
    scoring_blocks = [
        _Block(
            t_start=b.t_start, t_end=b.t_end, tokens=frozenset(b.tokens - background),
            seg_lo=b.seg_lo, seg_hi=b.seg_hi,
        )
        for b in blocks
    ]
    # Лексика, звучавшая хотя бы в одном блоке лекции. Заголовок в скоринг включается
    # только пересечением с ней: так слайдовые заголовки («Stop Controller», если лектор
    # это произнёс) добавляют попадания, а слова-связки из заголовка («тема», «слайд»),
    # которых нет в речи, не разбавляют знаменатель и не роняют пограничный якорь.
    spoken_tokens = frozenset().union(*[b.tokens for b in blocks]) if blocks else frozenset()

    section_tokens: dict[int, frozenset[str]] = {}
    candidates: list[tuple[int, int, float]] = []  # (section_pos, block_idx, score)
    for pos, section in enumerate(sections):
        body_tokens = tokenize_filtered(section.own_text or section.text)
        heading_tokens = tokenize_filtered(section.heading_text) & spoken_tokens
        tokens = frozenset((body_tokens | heading_tokens) - background)
        if len(tokens) < _MIN_SECTION_TOKENS:
            continue
        section_tokens[pos] = tokens
        scores = [_overlap_score(tokens, block) for block in scoring_blocks]
        block_idx = max(range(len(blocks)), key=lambda i: scores[i])
        if scores[block_idx] >= _MIN_ANCHOR_SCORE:
            candidates.append((pos, block_idx, scores[block_idx]))

    kept = _weighted_lis(candidates)
    anchor_by_pos = {pos: (blk, score) for pos, blk, score in candidates if pos in kept}
    anchored_positions = sorted(anchor_by_pos)

    # Уточнённые времена якорей (старт сегмента с различительной лексикой раздела,
    # а не граница блока). Интерполяция опирается именно на них: иначе значения сразу
    # после якоря выходят раньше его уточнённого времени и схлопываются клэмпом в одну
    # точку («стена одинаковых таймкодов» у десятков соседних разделов).
    anchor_t_start: dict[int, float] = {}
    for pos in anchored_positions:
        block_idx, _score = anchor_by_pos[pos]
        anchor_t_start[pos] = round(_refine_t_start(section_tokens[pos], blocks[block_idx], segments), 2)

    aligned: list[AlignedSection] = []
    for pos, section in enumerate(sections):
        if pos in anchor_by_pos:
            block_idx, score = anchor_by_pos[pos]
            block = blocks[block_idx]
            aligned.append(
                AlignedSection(
                    section=section,
                    t_start=anchor_t_start[pos],
                    t_end=round(block.t_end, 2),
                    confidence=_anchor_confidence(score),
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

    # Интерполяция считается по границам блоков, а якоря уточнены до сегмента —
    # финальный клэмп гарантирует неубывающие таймкоды.
    aligned = _clamp_monotonic(aligned)
    # t_end якоря растягиваем до следующего таймкода — «главы» без дыр.
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
