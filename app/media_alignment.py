"""Выравнивание разделов конспекта по таймкодам ASR-сегментов (anchor + weighted LIS).

Вход: разделы из :func:`app.section_index.parse_sections` и сегменты транскрипта
``[{start, end, text}]`` (см. ``scripts/transcribe_media.py``). Выход — таймкоды
``t_start/t_end`` и ``confidence`` на раздел, детерминированно и без LLM.

Алгоритм ``anchor-lis-v3.1`` (устойчив к видео 4–5 часов):

1. Транскрипт режется на **смысловые блоки** (:func:`build_semantic_blocks`) —
   TextTiling-подобная сегментация по провалам лексической связности между
   соседними окнами речи. У каждого блока настоящие границы темы
   (``t_start``/``t_end``) и ключевые слова (топ TF-IDF) — блоки пишутся в
   sidecar (``semantic_blocks``) и служат узлами смыслов видео для графа знаний.
   Токены скоринга (не ``compute_section_id``!) канонизируются: RU-стемминг
   словоформ («токенов»→«токен») + транслитерация латинских терминов
   конспекта в кириллицу ASR («skills»→«скиллс») — см. ``_tokenize_canon``.
   Поверх этого работает локальная детерминированная синонимия L1 для учебных
   речевых паттернов («практическое задание» ↔ «домашка/попробуйте сами»):
   без LLM, без provider-вызовов, только как расширение скоринговых токенов.
2. Slide-aware якорение: явное «слайд N» в речи или title-reading заголовка
   слайда/раздела по скользящему окну ~14 c транскрипта (``_build_windows`` —
   один ASR-сегмент, медианно 2 c/4 слова, для заголовка мал) → сильное
   свидетельство (confidence 0.75–0.90).
3. Конспект — несколько тематических «проходов» по одной лекции (слайды →
   ключевые темы → примеры → эксперт): хронология монотонна **внутри прохода**
   (H1/H2-группы, :func:`_split_passes`), между проходами независима. Каждый
   содержательный раздел получает блок-кандидат (argmax лексического
   перекрытия), взвешенный LIS и клампинг монотонности работают в пределах
   своего прохода — recap-проходы больше не конкурируют со слайдами за одну
   глобальную цепочку.
4. Разделы без якоря интерполируются между соседними якорями прохода
   пропорционально номерам строк и помечаются низким confidence (< 0.70).
5. ``t_end`` раздела — начало следующего раздела прохода, а у последнего в
   проходе — конец его смыслового блока (не конец медиа): «конец смысла» из
   сегментации, а не административная граница файла.

v2→v3: per-pass хронология вместо глобальной, смысловые блоки вместо блоков
фиксированного лексического объёма, честный ``t_end``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.knowledge_text import tokenize_filtered
from app.section_index import ParsedSection

ALIGNMENT_VERSION = "anchor-lis-v3.1"
SEGMENTS_SCHEMA_VERSION = 1

_MIN_SECTION_TOKENS = 8  # разделы короче не якорим — только интерполяция
_MIN_EXPANDED_SECTION_TOKENS = 3  # L1-семантика: мало слов, но они должны прозвучать
_MIN_ANCHOR_SCORE = 0.18  # ниже — совпадение считается шумом
_MIN_ANCHOR_SCORE_DEEP = 0.25  # H4+: мелкие разделы с generic-лексикой ложатся на случайные блоки
_MIN_EXPANDED_ANCHOR_SCORE = 0.45  # строгий порог для якоря без прямой лексики
_LONE_ANCHOR_MIN_SCORE = 0.30  # единственный body-якорь прохода без LIS-проверки
_INTERPOLATED_CONFIDENCE = 0.40  # < low_confidence-порога сайдкара (0.70)
_MAX_ANCHOR_CONFIDENCE = 0.99
_PASS_HEADING_LEVEL = 2  # H1/H2 начинают новый хронологический «проход» конспекта

# Семантическая сегментация транскрипта (TextTiling-подобная)
_TILE_WINDOW_SPAN = 45.0  # окно лексики слева/справа от границы-кандидата, сек
_TILE_MIN_BLOCK = 90.0  # смысловой блок короче не бывает — шум ASR, не смена темы
_TILE_MAX_BLOCK = 420.0  # длиннее — принудительное дробление по лучшему провалу
_TILE_DEPTH_SIGMA = 0.25  # порог границы: µ + 0.25σ по depth (выше µ−σ/2 TextTiling —
# разговорная речь с 2-секундными ASR-сегментами даёт рваную лексику и лишние провалы)
_TILE_KEYWORDS = 6  # ключевых слов на блок (топ TF-IDF) — «имя смысла» для графа

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
_SLIDE_TITLE_BODY_MIN_OVERLAP = 0.08  # дословная читка вне тематического блока = интро-упоминание
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

_SYNONYM_PHRASE_GROUPS = (
    (
        "практическое задание",
        "домашнее задание",
        "домашка",
        "упражнение",
        "самостоятельная работа",
        "попробуйте сами",
        "сделайте упражнение",
        "выполните задание",
        "повторите самостоятельно",
        "закрепление",
    ),
    (
        "итоги",
        "выводы",
        "резюме",
        "подведем итог",
        "подытожим",
        "главное",
        "что важно запомнить",
    ),
    (
        "пример",
        "кейс",
        "допустим",
        "рассмотрим ситуацию",
        "на практике",
        "практический пример",
    ),
    (
        "ошибки",
        "ловушки",
        "частые проблемы",
        "подводные камни",
        "pitfalls",
    ),
)

# ── Канонизация токенов: RU-стемминг + транслитерация ────────────────────
#
# Конспект и ASR-транскрипт лексически расходятся сильнее, чем различие в
# порядке слов: (1) словоформы — конспект пишет «токенов», лектор говорит
# «токен»/«токены»; (2) латинские термины конспекта («skills», «compacting»,
# «runtime») лектор произносит и ASR распознаёт кириллицей («скиллы»,
# «компактинг», «рантайм»). Без этого overlap занижен ~вдвое, из-за чего
# якоря либо не находятся вовсе, либо матчатся на случайные фоновые слова.
_RU_SUFFIXES = tuple(
    sorted(
        [
            "иями", "ями", "ами", "иях", "ием", "ии", "ия", "ий", "ый", "ой", "ей",
            "ов", "ев", "ах", "ях", "ом", "ем", "ам", "ям", "ую", "юю", "ая", "яя",
            "ое", "ее", "ые", "ие", "ого", "его", "ому", "ему", "ыми", "ими", "ым", "им",
            "ется", "ются", "ился", "ался", "ать", "ять", "еть", "ить", "ет",
            "ит", "ут", "ют", "ла", "ло", "ли", "ть",
            "а", "я", "о", "е", "ы", "и", "у", "ю", "ь",
        ],
        key=len,
        reverse=True,
    )
)
_RU_LETTER_RE = re.compile(r"[а-яё]")
_LATIN_TOKEN_RE = re.compile(r"[a-z]+")
_TRANSLIT_DIGRAPHS = (
    ("sch", "ш"), ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"), ("kh", "х"),
    ("oo", "у"), ("ee", "и"), ("ai", "ай"), ("ay", "ай"),
    ("qu", "кв"), ("ck", "к"), ("ju", "джу"), ("ja", "джа"),
)
_TRANSLIT_CHARS = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
    "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
    "y": "и", "z": "з",
}
# Оконное чтение заголовка (см. _build_windows): медианный ASR-сегмент —
# ~2 секунды / 4 слова, заголовок раздела туда не помещается целиком.
_TITLE_WINDOW_SPAN = 14.0


def _stem_ru(token: str) -> str:
    """Грубый суффиксный стеммер: «токенов»/«токена»/«токеном» → «токен»."""
    if len(token) <= 4 or not _RU_LETTER_RE.search(token):
        return token
    for suf in _RU_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 4:
            return token[: -len(suf)]
    return token


def _transliterate(token: str) -> str | None:
    """Латинский токен → фонетическое кириллическое приближение; иначе None."""
    if not _LATIN_TOKEN_RE.fullmatch(token):
        return None
    out = token
    for src, dst in _TRANSLIT_DIGRAPHS:
        out = out.replace(src, dst)
    return "".join(_TRANSLIT_CHARS.get(ch, ch) for ch in out)


def _canon_token(token: str) -> str:
    transliterated = _transliterate(token)
    return _stem_ru(transliterated) if transliterated is not None else _stem_ru(token)


def _tokenize_canon(text: str | None) -> frozenset[str]:
    """``tokenize_filtered`` + стемминг/транслитерация — токены для скоринга.

    Не используется в :func:`compute_section_id`: id обязан оставаться
    стабильным между запусками независимо от эволюции скоринговой канонизации.
    """
    return frozenset(_canon_token(t) for t in tokenize_filtered(text))


def _expand_learning_synonyms(
    text: str | None,
    tokens: frozenset[str],
    spoken_tokens: frozenset[str],
) -> tuple[frozenset[str], bool]:
    """Локальная L1-синонимия для учебных речевых паттернов.

    Это намеренно не общий тезаурус. Расширяем только маленький набор
    проверяемых фраз («практическое задание» ↔ «домашка/упражнение»), причём
    добавляем лишь те канонические токены, которые реально прозвучали в ASR.
    Так раздел без прямого лексического пересечения получает шанс на якорь, но
    не превращается в произвольный semantic search.
    """
    base_text_tokens = _tokenize_canon(text)
    expanded = set(tokens)
    matched = False
    for group in _SYNONYM_PHRASE_GROUPS:
        phrase_tokens = [_tokenize_canon(phrase) for phrase in group]
        if not any(phrase and phrase <= base_text_tokens for phrase in phrase_tokens):
            continue
        group_tokens = frozenset().union(*phrase_tokens)
        spoken_group_tokens = group_tokens & spoken_tokens
        if spoken_group_tokens - tokens:
            expanded.update(spoken_group_tokens)
            matched = True
    return frozenset(expanded), matched


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


# ── Смысловые блоки (TextTiling-подобная сегментация) ───────────────────


@dataclass(frozen=True)
class SemanticBlock:
    """Смысловой блок лекции: настоящие границы темы, не фиксированный объём.

    ``keywords`` — топ TF-IDF токенов блока: детерминированное «имя смысла»
    для sidecar (``semantic_blocks``) и узлов видео в графе знаний.
    """

    t_start: float
    t_end: float
    tokens: frozenset[str]
    seg_lo: int  # индексы сегментов блока — для уточнения t_start внутри блока
    seg_hi: int
    keywords: tuple[str, ...] = ()


# Скоринг и slide-якорение работают с любым блоком этой формы.
_Block = SemanticBlock


def _gap_similarities(
    segments: tuple[TranscriptSegment, ...],
    seg_tokens: list[frozenset[str]],
) -> list[float]:
    """Лексическая связность на каждой границе сегментов i|i+1.

    Косинус (на множествах) между токенами окна ``_TILE_WINDOW_SPAN`` слева и
    справа от границы. Провал связности = смена темы лектором.
    """
    n = len(segments)
    sims: list[float] = []
    for i in range(n - 1):
        boundary = segments[i].end
        left: set[str] = set()
        j = i
        while j >= 0 and boundary - segments[j].start <= _TILE_WINDOW_SPAN:
            left |= seg_tokens[j]
            j -= 1
        right: set[str] = set()
        k = i + 1
        while k < n and segments[k].start - boundary <= _TILE_WINDOW_SPAN:
            right |= seg_tokens[k]
            k += 1
        if not left or not right:
            sims.append(1.0)
            continue
        hit = len(left & right)
        sims.append(hit / ((len(left) * len(right)) ** 0.5))
    return sims


def _depth_scores(sims: list[float]) -> list[float]:
    """Глубина провала связности в каждой точке (классический TextTiling).

    depth_i = (пик слева − sim_i) + (пик справа − sim_i): чем глубже долина
    между двумя горами связности, тем увереннее граница темы.
    """
    n = len(sims)
    depths = [0.0] * n
    for i in range(n):
        peak_left = sims[i]
        for j in range(i - 1, -1, -1):
            if sims[j] < peak_left:
                break
            peak_left = sims[j]
        peak_right = sims[i]
        for j in range(i + 1, n):
            if sims[j] < peak_right:
                break
            peak_right = sims[j]
        depths[i] = (peak_left - sims[i]) + (peak_right - sims[i])
    return depths


def _select_boundaries(
    segments: tuple[TranscriptSegment, ...], depths: list[float]
) -> list[int]:
    """Индексы границ (после сегмента i) по depth-скорам.

    Порог — классический µ−σ/2; границы не ближе ``_TILE_MIN_BLOCK`` друг к
    другу (жадный отбор по убыванию depth); блоки длиннее ``_TILE_MAX_BLOCK``
    дробятся по лучшему оставшемуся провалу — «конец смысла» не должен уезжать
    на десятки минут даже в монотонной речи.
    """
    n = len(depths)
    if n == 0:
        return []
    mean = sum(depths) / n
    var = sum((d - mean) ** 2 for d in depths) / n
    cutoff = mean + _TILE_DEPTH_SIGMA * (var**0.5)
    candidates = sorted(
        (i for i in range(n) if depths[i] > max(cutoff, 0.0)),
        key=lambda i: depths[i],
        reverse=True,
    )
    media_start = segments[0].start
    media_end = segments[-1].end

    def _far_enough(idx: int, chosen: list[int]) -> bool:
        t = segments[idx].end
        if t - media_start < _TILE_MIN_BLOCK or media_end - t < _TILE_MIN_BLOCK:
            return False
        return all(abs(t - segments[c].end) >= _TILE_MIN_BLOCK for c in chosen)

    boundaries: list[int] = []
    for idx in candidates:
        if _far_enough(idx, boundaries):
            boundaries.append(idx)
    boundaries.sort()

    # Принудительное дробление слишком длинных кусков по лучшему провалу внутри.
    changed = True
    while changed:
        changed = False
        edges = [-1, *boundaries, len(segments) - 1]
        for lo, hi in zip(edges, edges[1:]):
            span_start = segments[lo + 1].start if lo >= 0 else media_start
            span_end = segments[hi].end
            if span_end - span_start <= _TILE_MAX_BLOCK:
                continue
            inner = [
                i
                for i in range(lo + 1, min(hi, len(depths)))
                if _far_enough(i, boundaries)
            ]
            if not inner:
                continue
            best = max(inner, key=lambda i: depths[i])
            boundaries.append(best)
            boundaries.sort()
            changed = True
            break
    return boundaries


def _block_keywords(
    block_tokens: list[frozenset[str]],
    all_blocks: list[frozenset[str]],
    surface_by_canon: dict[str, str],
) -> tuple[str, ...]:
    """Топ-``_TILE_KEYWORDS`` токенов блока по TF·IDF (df — по блокам).

    Ранжирование — по каноническим токенам (стемминг/транслитерация склеивают
    словоформы), а показывается человекочитаемая исходная форма
    (``surface_by_canon``): «лэмка», а не «лэмк».
    """
    n_blocks = len(all_blocks)
    df: dict[str, int] = {}
    for tokens in all_blocks:
        for tok in tokens:
            df[tok] = df.get(tok, 0) + 1
    tf: dict[str, int] = {}
    for tokens in block_tokens:
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
    scored = sorted(
        tf,
        key=lambda tok: (-tf[tok] * math.log((1 + n_blocks) / (1 + df.get(tok, 0))), tok),
    )
    return tuple(surface_by_canon.get(tok, tok) for tok in scored[:_TILE_KEYWORDS])


def _surface_forms_by_canon(segments: tuple[TranscriptSegment, ...]) -> dict[str, str]:
    """Канонический токен → его самая частая исходная словоформа (для показа).

    Детерминированный tie-break: чаще → короче → лексикографически. Стемминг
    нужен для матчинга, но пользователю в граф-линзе показываем живое слово.
    """
    counts: dict[str, dict[str, int]] = {}
    for seg in segments:
        for surface in tokenize_filtered(seg.text):
            canon = _canon_token(surface)
            bucket = counts.setdefault(canon, {})
            bucket[surface] = bucket.get(surface, 0) + 1
    result: dict[str, str] = {}
    for canon, forms in counts.items():
        result[canon] = min(forms, key=lambda s: (-forms[s], len(s), s))
    return result


def build_semantic_blocks(segments: tuple[TranscriptSegment, ...]) -> list[SemanticBlock]:
    """Детерминированная сегментация транскрипта на смысловые блоки.

    Ключ к точным таймкодам: у раздела конспекта появляются настоящие
    «начало смысла» и «конец смысла» вместо произвольных границ блоков
    фиксированного объёма. Блоки же — готовые узлы смыслов видео.
    """
    if not segments:
        return []
    seg_tokens = [_tokenize_canon(s.text) for s in segments]
    sims = _gap_similarities(segments, seg_tokens)
    depths = _depth_scores(sims)
    boundaries = _select_boundaries(segments, depths)
    surface_by_canon = _surface_forms_by_canon(segments)

    edges = [-1, *boundaries, len(segments) - 1]
    ranges = [(lo + 1, hi) for lo, hi in zip(edges, edges[1:]) if lo + 1 <= hi]
    union_tokens = [
        frozenset().union(*seg_tokens[lo : hi + 1]) if hi >= lo else frozenset()
        for lo, hi in ranges
    ]
    blocks: list[SemanticBlock] = []
    for (lo, hi), tokens in zip(ranges, union_tokens):
        blocks.append(
            SemanticBlock(
                t_start=segments[lo].start,
                t_end=segments[hi].end,
                tokens=tokens,
                seg_lo=lo,
                seg_hi=hi,
                keywords=_block_keywords(seg_tokens[lo : hi + 1], union_tokens, surface_by_canon),
            )
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
        if tokens & _tokenize_canon(segments[idx].text):
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


def _heading_title_tokens(
    heading_text: str, background: frozenset[str] = frozenset()
) -> tuple[str, ...]:
    """Токены заголовка для title-reading; пусто для общеупотребимых H4.

    ``background`` (фоновые токены лекции, см. :func:`_background_tokens`)
    вычитается: короткие технические термины («mcp», «llm», «rag») теперь не
    отфильтровываются по длине, но не должны матчиться на связки лектора.
    """
    normalized = " ".join(_normalize_heading_for_title_read(heading_text).lower().split())
    if normalized in _GENERIC_HEADING_TITLES:
        return ()
    tokens = tuple(_tokenize_canon(_normalize_heading_for_title_read(heading_text)) - background)
    return tokens


def _title_read_score(title_tokens: tuple[str, ...], window_tokens: frozenset[str]) -> float:
    """Доля токенов заголовка, встретившихся в окне транскрипта (см. :func:`_build_windows`)."""
    if not title_tokens:
        return 0.0
    hit = len(set(title_tokens) & window_tokens)
    return hit / len(title_tokens)


@dataclass(frozen=True)
class _Window:
    t_start: float
    tokens: frozenset[str]


def _build_windows(
    segments: tuple[TranscriptSegment, ...], span: float = _TITLE_WINDOW_SPAN
) -> list[_Window]:
    """Скользящее окно токенов на каждый сегмент — для title-reading.

    Медианный ASR-сегмент ~2 с / 4 слова: заголовок раздела (обычно 3–6 слов)
    физически не помещается в один сегмент. Окно агрегирует все сегменты в
    ``span`` секунд вперёд от текущего — без сдвига якорной точки: индекс
    и ``t_start`` окна равны индексу/старту исходного сегмента.
    """
    n = len(segments)
    seg_tokens = [_tokenize_canon(s.text) for s in segments]
    windows: list[_Window] = []
    for i in range(n):
        limit = segments[i].start + span
        tokens: set[str] = set()
        for k in range(i, n):
            if segments[k].start > limit:
                break
            tokens |= seg_tokens[k]
        windows.append(_Window(t_start=segments[i].start, tokens=frozenset(tokens)))
    return windows


def _block_idx_for_seg(blocks: list[_Block], seg_idx: int) -> int:
    for i, block in enumerate(blocks):
        if block.seg_lo <= seg_idx <= block.seg_hi:
            return i
    return max(0, len(blocks) - 1)


def _idf_by_token(blocks: list[_Block]) -> dict[str, float]:
    """IDF токенов по смысловым блокам — «редкость» слова в этой лекции."""
    df: dict[str, int] = {}
    for block in blocks:
        for tok in block.tokens:
            df[tok] = df.get(tok, 0) + 1
    n = len(blocks)
    return {tok: math.log((1 + n) / (1 + count)) for tok, count in df.items()}


def _top_idf_token(tokens: tuple[str, ...], idf: dict[str, float]) -> str | None:
    """Самый редкий (по IDF) токен заголовка — его различительное ядро."""
    if not tokens:
        return None
    return max(tokens, key=lambda tok: (idf.get(tok, math.log(2)), tok))


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
    sections: list[ParsedSection],
    segments: tuple[TranscriptSegment, ...],
    slide_sections: list[tuple[int, int, str]],
    windows: list[_Window],
    background: frozenset[str],
    blocks: list[_Block],
) -> list[_SlideCue]:
    """Title-reading слайдов: лучшее окно по рангу title + смысловой блок.

    Прежний жадный курсор («только вперёд от последнего мэтча») каскадно
    утаскивал все последующие слайды за одним ложным мэтчем. Теперь каждый
    слайд получает argmax по всем окнам, ранжированный как
    ``title_score + 0.5·body_overlap`` — дословное чтение заголовка там, где
    и лексика тела раздела, отличает обсуждение от беглого упоминания.
    Хронологию наводит LIS-фильтр (:func:`_filter_slide_anchors_by_lis`).
    """
    cues: list[_SlideCue] = []
    for pos, slide_num, heading in sorted(slide_sections, key=lambda item: item[1]):
        title_tokens = _heading_title_tokens(_slide_title_from_heading(heading), background)
        if not title_tokens:
            continue
        body_tokens = (
            _tokenize_canon(sections[pos].own_text or sections[pos].text) - background
        )
        best_idx = -1
        best_rank = 0.0
        best_score = 0.0
        strong_idx = -1  # самое раннее дословное чтение в тематически своём блоке
        strong_score = 0.0
        for idx in range(len(segments)):
            score = _title_read_score(title_tokens, windows[idx].tokens)
            if score < _SLIDE_TITLE_MIN_SCORE:
                continue
            block = blocks[_block_idx_for_seg(blocks, idx)]
            body_overlap = _overlap_score(body_tokens, block)
            if (
                strong_idx < 0
                and score >= _SLIDE_TITLE_STRONG_SCORE
                and body_overlap >= _SLIDE_TITLE_BODY_MIN_OVERLAP
            ):
                strong_idx = idx
                strong_score = score
            rank = score + 0.5 * body_overlap
            if rank > best_rank:
                best_rank = rank
                best_score = score
                best_idx = idx
        if strong_idx >= 0:
            # Дословное чтение заголовка = анонс слайда: это момент НАЧАЛА
            # обсуждения, поэтому самое раннее такое окно точнее, чем окно с
            # максимальной плотностью лексики тела (пик обсуждения — позже).
            # Требование body_overlap отсекает беглые упоминания темы в интро.
            best_idx, best_score = strong_idx, strong_score
        if best_idx < 0:
            continue
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
    background: frozenset[str],
) -> tuple[int, float] | None:
    tokens = _heading_title_tokens(heading_text, background)
    if not tokens:
        return None
    best_num: int | None = None
    best_overlap = 0.0
    for _pos, slide_num, slide_heading in slide_sections:
        slide_tokens = _heading_title_tokens(_slide_title_from_heading(slide_heading), background)
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
    windows: list[_Window],
    background: frozenset[str],
) -> dict[int, tuple[int, float, float]]:
    """Title-reading в окне слайда, к которому тематически привязан раздел.

    Обязателен top-IDF токен заголовка в окне: «Детерминизм: почему 100% не
    будет» не должен якориться на «почему»+«будет» без слова «детерминизм» —
    совпадение связок без различительного ядра всегда ложное.
    """
    if len(anchors) < 2:
        return {}
    media_end = segments[-1].end if segments else float("inf")
    slide_windows = _slide_time_windows(slide_sections, anchors, media_end)
    idf = _idf_by_token(blocks)
    heading_anchors: dict[int, tuple[int, float, float]] = {}
    for pos, section in enumerate(sections):
        if pos in anchors or _slide_number_from_heading(section.heading_text):
            continue
        if section.level >= 5:
            continue
        title_tokens = _heading_title_tokens(section.heading_text, background)
        # H4-подзаголовки из двух слов («Важное ограничение») складываются из
        # бытовой лексики в любом окне; надёжен только развёрнутый заголовок.
        min_title_tokens = 2 if section.level <= 3 else 3
        if len(title_tokens) < min_title_tokens:
            continue
        top_token = _top_idf_token(title_tokens, idf)
        mapped = _best_slide_for_heading(section.heading_text, slide_sections, background)
        if mapped is None:
            t_lo, t_hi = 0.0, media_end
            min_score = 0.50
        else:
            slide_num, _overlap = mapped
            t_lo, t_hi = slide_windows.get(slide_num, (0.0, media_end))
            min_score = 0.35
        best_idx = -1
        best_score = 0.0
        for idx, seg in enumerate(segments):
            if not (t_lo <= seg.start <= t_hi):
                continue
            window_tokens = windows[idx].tokens
            if top_token is not None and top_token not in window_tokens:
                continue
            # Одного совпавшего слова мало: у 2-токенного заголовка score 0.50 —
            # это одинокое бытовое слово («минимальный», «практическое»)
            # в случайном месте лекции, а не чтение заголовка.
            if len(set(title_tokens) & window_tokens) < min(2, len(title_tokens)):
                continue
            score = _title_read_score(title_tokens, window_tokens)
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
    windows: list[_Window],
    background: frozenset[str],
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
        title_tokens = _heading_title_tokens(_slide_title_from_heading(heading), background)
        if not title_tokens:
            continue
        best_idx = -1
        best_score = 0.0
        for idx, seg in enumerate(segments):
            if not (t_lo <= seg.start <= t_hi):
                continue
            score = _title_read_score(title_tokens, windows[idx].tokens)
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
    windows: list[_Window],
    background: frozenset[str],
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
    title_cues = _detect_slide_title_cues(sections, segments, slide_sections, windows, background, blocks)
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
    anchors.update(
        _windowed_slide_match(
            unmatched, segments, blocks, anchors_by_num=anchors_by_num, windows=windows, background=background
        )
    )

    anchors.update(
        _detect_windowed_heading_cues(
            segments,
            sections,
            blocks,
            slide_sections=slide_sections,
            anchors=anchors,
            windows=windows,
            background=background,
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
    """LIS по seg_idx: отбрасывает slide-cue, ломающие хронологию (recap, ASR-шум).

    Вес — confidence якоря, не константа: при конфликте немонотонных cue
    выживает цепочка с бóльшим суммарным доверием, а не более длинная из слабых.
    """
    if not slide_anchor_by_pos:
        return {}
    lis_input = [
        (
            pos,
            _seg_idx_at_time(segments, slide_anchor_by_pos[pos][2]),
            _SLIDE_CUE_LIS_WEIGHT * slide_anchor_by_pos[pos][1],
        )
        for pos in sorted(slide_anchor_by_pos)
    ]
    kept = _weighted_lis(lis_input, prefer_later_section_on_tie=True)
    return {pos: slide_anchor_by_pos[pos] for pos in kept}


# ── Публичное выравнивание ──────────────────────────────────────────────


def _split_passes(sections: list[ParsedSection]) -> list[list[int]]:
    """Хронологические «проходы» конспекта: H1/H2 начинает новый.

    Реальный конспект несколько раз проходит одну лекцию (слайды → ключевые
    темы → примеры → эксперт). Монотонность таймкодов верна внутри прохода,
    между проходами — нет.
    """
    passes: list[list[int]] = []
    for pos, section in enumerate(sections):
        if section.level <= _PASS_HEADING_LEVEL or not passes:
            passes.append([])
        passes[-1].append(pos)
    return passes


@dataclass(frozen=True)
class _PassAnchor:
    t_start: float
    confidence: float
    block_idx: int
    anchored: bool


def _align_pass(
    pass_positions: list[int],
    sections: list[ParsedSection],
    segments: tuple[TranscriptSegment, ...],
    blocks: list[SemanticBlock],
    scoring_blocks: list[SemanticBlock],
    slide_anchor_all: dict[int, tuple[int, float, float]],
    spoken_tokens: frozenset[str],
    background: frozenset[str],
) -> dict[int, _PassAnchor]:
    """Якоря и интерполяция в пределах одного прохода конспекта."""
    pass_slides = _filter_slide_anchors_by_lis(
        {pos: slide_anchor_all[pos] for pos in pass_positions if pos in slide_anchor_all},
        segments,
    )

    block_floor_by_pos: dict[int, int] = {}
    floor = 0
    for pos in pass_positions:
        block_floor_by_pos[pos] = floor
        if pos in pass_slides:
            floor = pass_slides[pos][0]

    section_tokens: dict[int, frozenset[str]] = {}
    candidates: list[tuple[int, int, float]] = []
    for pos in pass_positions:
        if pos in pass_slides:
            block_idx, _conf, _t = pass_slides[pos]
            candidates.append((pos, block_idx, _SLIDE_CUE_LIS_WEIGHT))
            continue
        section = sections[pos]
        body_tokens = _tokenize_canon(section.own_text or section.text)
        heading_tokens = _tokenize_canon(section.heading_text) & spoken_tokens
        tokens = frozenset((body_tokens | heading_tokens) - background)
        tokens, expanded = _expand_learning_synonyms(
            "\n".join([section.heading_text, section.own_text or section.text]),
            tokens,
            spoken_tokens,
        )
        tokens = frozenset(tokens - background)
        min_tokens = _MIN_EXPANDED_SECTION_TOKENS if expanded else _MIN_SECTION_TOKENS
        if len(tokens) < min_tokens:
            continue
        section_tokens[pos] = tokens
        scores = [_overlap_score(tokens, block) for block in scoring_blocks]
        min_block = block_floor_by_pos[pos] if pass_slides else 0
        eligible = range(min_block, len(blocks))
        block_idx = max(eligible, key=lambda i: scores[i])
        if expanded:
            min_score = _MIN_EXPANDED_ANCHOR_SCORE
        else:
            min_score = _MIN_ANCHOR_SCORE if section.level <= 3 else _MIN_ANCHOR_SCORE_DEEP
        if scores[block_idx] >= min_score:
            candidates.append((pos, block_idx, scores[block_idx]))

    kept = _weighted_lis(candidates)
    kept_body = [
        (pos, blk, score) for pos, blk, score in candidates if pos in kept and pos not in pass_slides
    ]
    # Одинокий слабый body-якорь прохода: LIS его ничем не проверил (не с чем
    # согласовываться), а слабый overlap на 2-часовой лекции — почти наверняка
    # случайное совпадение лексики. Честное «нет таймкода» лучше промаха на час.
    if (
        len(kept_body) == 1
        and not pass_slides
        and kept_body[0][2] < _LONE_ANCHOR_MIN_SCORE
    ):
        kept.discard(kept_body[0][0])
        kept_body = []

    anchors: dict[int, _PassAnchor] = {}
    for pos, blk, score in candidates:
        if pos not in kept:
            continue
        if pos in pass_slides:
            block_idx, confidence, t_start = pass_slides[pos]
            anchors[pos] = _PassAnchor(
                t_start=round(t_start, 2), confidence=confidence, block_idx=block_idx, anchored=True
            )
        else:
            t_start = round(_refine_t_start(section_tokens[pos], blocks[blk], segments), 2)
            anchors[pos] = _PassAnchor(
                t_start=t_start, confidence=_anchor_confidence(score), block_idx=blk, anchored=True
            )

    # Интерполяция между якорями прохода — по номерам строк (объём контента),
    # а не по порядковому номеру раздела: разделы сильно разного размера.
    anchored_positions = sorted(anchors)
    for pos in pass_positions:
        if pos in anchors:
            continue
        prev_pos = max((p for p in anchored_positions if p < pos), default=None)
        next_pos = min((p for p in anchored_positions if p > pos), default=None)
        if prev_pos is None or next_pos is None:
            continue  # край прохода без двух опор — честнее не выдумывать таймкод
        l_prev = sections[prev_pos].line_start
        l_next = sections[next_pos].line_start
        frac = (
            (sections[pos].line_start - l_prev) / (l_next - l_prev) if l_next > l_prev else 0.0
        )
        t_prev = anchors[prev_pos].t_start
        t_next = anchors[next_pos].t_start
        anchors[pos] = _PassAnchor(
            t_start=round(t_prev + (t_next - t_prev) * frac, 2),
            confidence=_INTERPOLATED_CONFIDENCE,
            block_idx=anchors[prev_pos].block_idx,
            anchored=False,
        )

    # Монотонность — внутри прохода.
    floor_t: float | None = None
    for pos in pass_positions:
        anchor = anchors.get(pos)
        if anchor is None:
            continue
        if floor_t is not None and anchor.t_start < floor_t:
            anchors[pos] = _PassAnchor(
                t_start=floor_t,
                confidence=anchor.confidence,
                block_idx=anchor.block_idx,
                anchored=anchor.anchored,
            )
        floor_t = anchors[pos].t_start
    return anchors


def align_sections(
    sections: list[ParsedSection], segments: tuple[TranscriptSegment, ...]
) -> list[AlignedSection]:
    """Детерминированное выравнивание разделов по сегментам транскрипта."""
    blocks = build_semantic_blocks(segments)
    if not blocks:
        return [
            AlignedSection(section=s, t_start=None, t_end=None, confidence=0.0, anchored=False)
            for s in sections
        ]

    background = _background_tokens(blocks)
    windows = _build_windows(segments)
    slide_anchor_all = _build_slide_anchors(sections, segments, blocks, windows, background)

    scoring_blocks = [
        SemanticBlock(
            t_start=b.t_start, t_end=b.t_end, tokens=frozenset(b.tokens - background),
            seg_lo=b.seg_lo, seg_hi=b.seg_hi, keywords=b.keywords,
        )
        for b in blocks
    ]
    spoken_tokens = frozenset().union(*[b.tokens for b in blocks]) if blocks else frozenset()

    anchors: dict[int, _PassAnchor] = {}
    passes = _split_passes(sections)
    for pass_positions in passes:
        anchors.update(
            _align_pass(
                pass_positions,
                sections,
                segments,
                blocks,
                scoring_blocks,
                slide_anchor_all,
                spoken_tokens,
                background,
            )
        )

    t_end_by_pos = _pass_t_ends(passes, anchors, blocks)
    aligned: list[AlignedSection] = []
    for pos, section in enumerate(sections):
        anchor = anchors.get(pos)
        if anchor is None:
            aligned.append(
                AlignedSection(section=section, t_start=None, t_end=None, confidence=0.0, anchored=False)
            )
            continue
        aligned.append(
            AlignedSection(
                section=section,
                t_start=anchor.t_start,
                t_end=t_end_by_pos.get(pos),
                confidence=anchor.confidence,
                anchored=anchor.anchored,
            )
        )
    return aligned


def _pass_t_ends(
    passes: list[list[int]],
    anchors: dict[int, _PassAnchor],
    blocks: list[SemanticBlock],
) -> dict[int, float]:
    """``t_end`` разделов: начало следующего в проходе, у хвоста — конец смысла.

    Прежний ``_stretch_ends`` дотягивал последний раздел до конца медиа —
    «Практическое задание» получало 30-минутный интервал, а playlist_seconds
    превышал длительность лекции. Конец смыслового блока — честная граница.
    """
    t_ends: dict[int, float] = {}
    for pass_positions in passes:
        timed = [pos for pos in pass_positions if pos in anchors]
        for i, pos in enumerate(timed):
            t_start = anchors[pos].t_start
            next_start = next(
                (anchors[p].t_start for p in timed[i + 1 :] if anchors[p].t_start > t_start),
                None,
            )
            if next_start is not None:
                t_ends[pos] = round(next_start, 2)
                continue
            block_end = blocks[anchors[pos].block_idx].t_end
            t_ends[pos] = round(max(block_end, t_start), 2)
    return t_ends
