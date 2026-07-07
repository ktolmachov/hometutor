"""Инварианты выравнивания разделов конспекта по ASR-сегментам (anchor-lis-v3).

Фикстуры v3: конспект — иерархия H2-«проходов» (level=2) с содержательными
разделами внутри (level=3+); хронология таймкодов гарантируется внутри прохода,
между проходами — независима (реальные конспекты несколько раз проходят одну
лекцию: слайды → ключевые темы → примеры).
"""

from __future__ import annotations

from app.media_alignment import (
    AlignedSection,
    TranscriptSegment,
    align_sections,
    build_semantic_blocks,
    compute_section_id,
    _slide_number_from_heading,
    _split_passes,
    _stem_ru,
    _transliterate,
    _tokenize_canon,
)
from app.section_index import ParsedSection


def _section(heading: str, text: str, pos: int, *, level: int = 3) -> ParsedSection:
    line = pos * 10 + 1
    return ParsedSection(
        heading_text=heading,
        slug=heading.lower().replace(" ", "-"),
        level=level,
        line_start=line,
        line_end=line + 8,
        text=text,
        own_text=text,
    )


def _segments_from_topics(topics: list[str], *, chunks: int = 8) -> tuple[TranscriptSegment, ...]:
    """Синтетическая лекция: у темы общее лексическое ядро + уникальный хвост.

    Ядро повторяется в каждом сегменте темы (высокая связность внутри темы),
    хвосты уникальны (нулевая связность на границе тем) — так сегментация
    находит настоящие границы смысловых блоков. 30 сек на сегмент.
    """
    segments: list[TranscriptSegment] = []
    t = 0.0
    for topic in topics:
        core = " ".join(f"{topic}ядро{i} " for i in range(10))
        for chunk in range(chunks):
            unique = " ".join(f"{topic}слово{chunk * 15 + i}" for i in range(15))
            segments.append(TranscriptSegment(start=t, end=t + 30.0, text=f"{core} {unique}"))
            t += 30.0
    return tuple(segments)


def _topic_text(topic: str, words: int = 40) -> str:
    core = " ".join(f"{topic}ядро{i}" for i in range(10))
    return core + " " + " ".join(f"{topic}слово{i}" for i in range(words))


def test_alignment_anchors_match_topics_in_order():
    topics = ["альфа", "бета", "гамма", "дельта"]
    segments = _segments_from_topics(topics)
    sections = [_section(f"Тема {t}", _topic_text(t), i) for i, t in enumerate(topics)]

    aligned = align_sections(sections, segments)

    assert len(aligned) == 4
    assert all(a.anchored for a in aligned), [a.confidence for a in aligned]
    starts = [a.t_start for a in aligned]
    assert starts == sorted(starts)
    # Каждая тема занимает 8 сегментов × 30 сек = 240 сек; якорь должен попасть в свою тему.
    for i, a in enumerate(aligned):
        assert i * 240.0 <= a.t_start < (i + 1) * 240.0, (i, a.t_start)
        assert a.confidence >= 0.70


def test_semantic_blocks_follow_topic_boundaries():
    """Сегментация находит границы тем: блоки не пересекают смену словаря."""
    topics = ["альфа", "бета", "гамма"]
    segments = _segments_from_topics(topics)

    blocks = build_semantic_blocks(segments)

    assert blocks, "сегментация обязана вернуть блоки"
    assert blocks[0].t_start == segments[0].start
    assert blocks[-1].t_end == segments[-1].end
    # Границы блоков — на стыках тем (240 и 480 сек) с точностью до сегмента.
    boundaries = {round(b.t_start) for b in blocks} - {0}
    assert any(210 <= b <= 270 for b in boundaries), boundaries
    assert any(450 <= b <= 510 for b in boundaries), boundaries
    # Ключевые слова блока — из словаря его темы.
    first_kw = " ".join(blocks[0].keywords)
    assert "альфа" in first_kw


def test_semantic_blocks_have_sane_metadata():
    segments = _segments_from_topics(["альфа", "бета"])
    blocks = build_semantic_blocks(segments)
    for block in blocks:
        assert block.t_end > block.t_start
        assert 0 <= block.seg_lo <= block.seg_hi < len(segments)
        assert block.keywords, "каждый блок обязан иметь ключевые слова"
    # Блоки покрывают весь транскрипт без пересечений.
    for prev, cur in zip(blocks, blocks[1:]):
        assert cur.seg_lo == prev.seg_hi + 1


def test_multipass_konspekt_allows_non_monotonic_timestamps_between_passes():
    """Ключевой инвариант v3: конспект с двумя проходами по одной лекции.

    Первый проход (H2 «Слайды») идёт по темам в хронологии; второй проход
    (H2 «Ключевые темы») снова возвращается к ранним темам. Глобальная
    монотонность v1/v2 прижимала второй проход к хвосту лекции; v3 обязан
    дать раннюю тему второго прохода в её настоящем (раннем) времени.
    """
    topics = ["альфа", "бета", "гамма", "дельта"]
    segments = _segments_from_topics(topics)
    sections = [
        _section("Проход по слайдам", "обзор", 0, level=2),
        _section("Тема альфа", _topic_text("альфа"), 1),
        _section("Тема гамма", _topic_text("гамма"), 2),
        _section("Тема дельта", _topic_text("дельта"), 3),
        _section("Ключевые темы", "обзор", 4, level=2),
        _section("Снова альфа", _topic_text("альфа"), 5),
        _section("Снова бета", _topic_text("бета"), 6),
    ]

    aligned = align_sections(sections, segments)

    # Первый проход хронологичен.
    first_pass = [aligned[1], aligned[2], aligned[3]]
    assert all(a.anchored for a in first_pass)
    starts = [a.t_start for a in first_pass]
    assert starts == sorted(starts)
    # Второй проход вернулся к раннему времени: «Снова альфа» — в теме альфа
    # (первые 240 сек), хотя в документе стоит ПОСЛЕ дельты (720+ сек).
    again_alpha = aligned[5]
    assert again_alpha.anchored
    assert again_alpha.t_start < 240.0, again_alpha.t_start
    again_beta = aligned[6]
    assert again_beta.anchored
    assert 240.0 <= again_beta.t_start < 480.0, again_beta.t_start
    # Внутри второго прохода — своя монотонность.
    assert again_alpha.t_start <= again_beta.t_start


def test_split_passes_groups_by_h2():
    sections = [
        _section("Проход 1", "…", 0, level=2),
        _section("Раздел", "…", 1),
        _section("Подраздел", "…", 2, level=4),
        _section("Проход 2", "…", 3, level=2),
        _section("Раздел", "…", 4),
    ]
    passes = _split_passes(sections)
    assert passes == [[0, 1, 2], [3, 4]]


def test_alignment_is_monotonic_within_pass_even_with_confusable_sections():
    topics = ["альфа", "бета", "гамма"]
    segments = _segments_from_topics(topics)
    sections = [
        _section("Тема альфа", _topic_text("альфа"), 0),
        # Раздел-обманка: словарь последней темы, но стоит в середине конспекта.
        _section("Отступление", _topic_text("гамма"), 1),
        _section("Тема бета", _topic_text("бета"), 2),
        _section("Тема гамма", _topic_text("гамма"), 3),
    ]

    aligned = align_sections(sections, segments)

    starts = [a.t_start for a in aligned if a.t_start is not None]
    assert starts == sorted(starts), "таймкоды прохода обязаны быть неубывающими"


def test_unanchored_section_between_anchors_is_interpolated_low_confidence():
    topics = ["альфа", "бета"]
    segments = _segments_from_topics(topics)
    sections = [
        _section("Тема альфа", _topic_text("альфа"), 0),
        _section("Врезка без лексики из лекции", "совершенно посторонние независимые слова " * 3, 1),
        _section("Тема бета", _topic_text("бета"), 2),
    ]

    aligned = align_sections(sections, segments)

    middle = aligned[1]
    assert not middle.anchored
    assert middle.t_start is not None, "между якорями таймкод интерполируется"
    assert aligned[0].t_start <= middle.t_start <= aligned[2].t_start
    assert middle.confidence < 0.70, "интерполяция обязана быть low-confidence для UI"


def test_practical_assignment_anchors_via_local_synonym_expansion():
    """Регрессия для раздела без прямого лексического пересечения с речью.

    В конспекте типовой заголовок «Практическое задание», а лектор говорит
    «домашка/попробуйте сами/упражнение». L1-синонимия должна помочь найти
    таймкод детерминированно и локально, без LLM.
    """
    segments = (
        TranscriptSegment(
            0.0,
            30.0,
            "сначала обсуждаем архитектуру агент инструменты контекст память планирование",
        ),
        TranscriptSegment(
            30.0,
            60.0,
            "теперь домашка попробуйте сами сделайте упражнение повторите самостоятельно",
        ),
        TranscriptSegment(
            60.0,
            90.0,
            "после этого перейдем к вопросам и разберем ответы",
        ),
    )
    sections = [
        _section(
            "Практическое задание",
            "Завершающий самостоятельный шаг после урока.",
            0,
        )
    ]

    aligned = align_sections(sections, segments)

    assert aligned[0].anchored
    assert aligned[0].t_start == 30.0
    assert aligned[0].confidence >= 0.70


def test_edge_section_without_both_anchors_gets_no_timestamp():
    segments = _segments_from_topics(["альфа"])
    sections = [
        _section("Посторонний пролог", "иные никак не встречающиеся токены " * 3, 0),
        _section("Тема альфа", _topic_text("альфа"), 1),
    ]

    aligned = align_sections(sections, segments)

    assert aligned[0].t_start is None, "край без двух опор не выдумывает таймкод"
    assert aligned[0].confidence == 0.0
    assert aligned[1].anchored


def test_empty_segments_yield_no_timestamps():
    sections = [_section("Тема", _topic_text("альфа"), 0)]
    aligned = align_sections(sections, tuple())
    assert aligned == [
        AlignedSection(section=sections[0], t_start=None, t_end=None, confidence=0.0, anchored=False)
    ]


def test_t_end_is_next_section_start_and_last_ends_at_semantic_block():
    """t_end = начало следующего раздела прохода; хвост — конец смысла, не медиа.

    Прежний ``_stretch_ends`` дотягивал последний раздел до конца файла:
    «Практическое задание» получало 30-минутный интервал, а сумма плейлиста
    превышала длительность лекции.
    """
    topics = ["альфа", "бета", "гамма"]
    segments = _segments_from_topics(topics)
    # Конспект покрывает только первые две темы; гамма (480–720 c) — не его.
    sections = [
        _section("Тема альфа", _topic_text("альфа"), 0),
        _section("Тема бета", _topic_text("бета"), 1),
    ]

    aligned = align_sections(sections, segments)

    assert aligned[0].t_end == aligned[1].t_start
    last = aligned[1]
    assert last.anchored
    assert last.t_end is not None
    # Конец последнего раздела — конец его смыслового блока (тема бета
    # заканчивается на 480 c), а не конец медиа (720 c).
    assert last.t_end <= 480.0 + 30.0, last.t_end


def test_alignment_survives_shared_vocabulary_between_topics():
    """Реалистичный случай: общие термины (модель, токен, агент…) звучат всю
    лекцию, темы различаются лишь частью лексики."""
    shared = " ".join(f"общий{i}" for i in range(15))
    topics = ["альфа", "бета", "гамма", "дельта"]
    segments: list[TranscriptSegment] = []
    t = 0.0
    for topic in topics:
        core = " ".join(f"{topic}ядро{i}" for i in range(8))
        for chunk in range(8):
            specific = " ".join(f"{topic}слово{chunk * 10 + i}" for i in range(10))
            segments.append(
                TranscriptSegment(start=t, end=t + 30.0, text=f"{shared} {core} {specific}")
            )
            t += 30.0
    sections = [
        _section(
            f"Тема {topic}",
            f"{shared} " + " ".join(f"{topic}ядро{i}" for i in range(8)) + " "
            + " ".join(f"{topic}слово{i}" for i in range(30)),
            i,
        )
        for i, topic in enumerate(topics)
    ]

    aligned = align_sections(sections, tuple(segments))

    starts = [a.t_start for a in aligned]
    assert all(s is not None for s in starts)
    assert starts == sorted(starts)
    for i, a in enumerate(aligned):
        assert i * 240.0 <= a.t_start < (i + 1) * 240.0, (i, a.t_start)


def test_section_id_stable_and_content_sensitive():
    a1 = _section("Тема", _topic_text("альфа"), 0)
    a2 = _section("Тема", _topic_text("альфа"), 5)  # другие строки — id тот же
    b = _section("Тема", _topic_text("бета"), 0)

    assert compute_section_id(a1) == compute_section_id(a2)
    assert compute_section_id(a1) != compute_section_id(b)
    assert compute_section_id(a1).startswith("sha256:")


def test_slide_direct_number_cue_is_confident():
    """Явное «слайд N» в речи + заголовок с номером → confident-якорь на cue-сегменте."""
    segments = (
        TranscriptSegment(0.0, 5.0, "вступление"),
        TranscriptSegment(60.0, 65.0, "перейдём к слайду 3 про надёжность"),
        TranscriptSegment(120.0, 125.0, "дальше про деплой"),
    )
    sections = [
        ParsedSection(
            heading_text="Слайд 3: Надёжность",
            slug="slide-3",
            level=3,
            line_start=1,
            line_end=9,
            text="конспект про надёжность " * 5,
            own_text="конспект про надёжность " * 5,
        ),
    ]

    aligned = align_sections(sections, segments)

    assert aligned[0].anchored
    assert aligned[0].t_start == 60.0
    assert aligned[0].confidence >= 0.70


def test_slide_recap_late_mention_dropped_by_lis():
    """Поздний recap «slide 1» не должен давать уверенный якорь раньше slide 3 в хронологии."""
    segments = (
        TranscriptSegment(10.0, 15.0, "переходим к slide 3 основной материал"),
        TranscriptSegment(80.0, 85.0, "напомню slide 1 из начала лекции"),
    )
    sections = [
        ParsedSection(
            heading_text="Slide 1: Вступление",
            slug="slide-1",
            level=3,
            line_start=1,
            line_end=9,
            text="текст " * 6,
            own_text="текст " * 6,
        ),
        ParsedSection(
            heading_text="Slide 2: Середина",
            slug="slide-2",
            level=3,
            line_start=11,
            line_end=19,
            text="текст " * 6,
            own_text="текст " * 6,
        ),
        ParsedSection(
            heading_text="Slide 3: Основное",
            slug="slide-3",
            level=3,
            line_start=21,
            line_end=29,
            text="текст " * 6,
            own_text="текст " * 6,
        ),
    ]

    aligned = align_sections(sections, segments)

    assert aligned[2].anchored
    assert aligned[2].t_start == 10.0
    assert aligned[2].confidence >= 0.70
    slide1 = aligned[0]
    assert not (slide1.anchored and slide1.confidence >= 0.70 and slide1.t_start == 80.0)


def test_plural_slide_range_heading_extracts_first_number():
    assert _slide_number_from_heading("Слайд 3: works") == 3
    assert _slide_number_from_heading("Слайды 8–12: LLM") == 8
    assert _slide_number_from_heading("Слайды 25-27: Workflow") == 25
    assert _slide_number_from_heading("Тема без слайда") is None


def test_ru_stemming_collapses_wordforms():
    """«токенов»/«токена»/«токеном» — одна лексема для скоринга overlap."""
    forms = ["токенов", "токена", "токеном", "токены", "токен"]
    stems = {_stem_ru(f) for f in forms}
    assert len(stems) == 1, stems


def test_ru_stemming_does_not_touch_short_or_latin_tokens():
    assert _stem_ru("тест") == "тест"  # <=4 символов — не трогаем
    assert _stem_ru("skills") == "skills"  # латиница — не по этому пути


def test_transliteration_bridges_latin_term_and_cyrillic_asr():
    """Конспект пишет термин латиницей, ASR — кириллицей; canon должен их сблизить."""
    assert _transliterate("skills") is not None
    assert _transliterate("токен") is None  # не латиница — None
    canon_konspekt = _tokenize_canon("Skills и Compacting контекста")
    canon_asr = _tokenize_canon("Скиллы и компактинг контекста, вот")
    assert canon_konspekt & canon_asr, (canon_konspekt, canon_asr)


def test_alignment_finds_title_anchor_across_multiple_short_asr_segments():
    """Заголовок раздела (несколько слов) не влезает в один 2-секундный ASR-сегмент —
    title-match должен агрегировать окно сегментов, а не только текущий."""
    segments = (
        TranscriptSegment(0.0, 2.0, "так, вот"),
        TranscriptSegment(2.0, 4.0, "смотрите"),
        TranscriptSegment(4.0, 6.0, "logit biasing"),
        TranscriptSegment(6.0, 8.0, "и token masking"),
        TranscriptSegment(8.0, 10.0, "это важная штука"),
        TranscriptSegment(60.0, 62.0, "дальше про другое"),
    )
    sections = [
        ParsedSection(
            heading_text="Слайд 30: Logit biasing / token masking",
            slug="slide-30",
            level=3,
            line_start=1,
            line_end=9,
            text="конспект про логиты " * 5,
            own_text="конспект про логиты " * 5,
        ),
    ]

    aligned = align_sections(sections, segments)

    assert aligned[0].anchored
    # Окно агрегирует несколько сегментов вперёд — якорь попадает где-то в
    # начало реплики, а не строго на первый сегмент с частью термина; важно,
    # что он НЕ ушёл на посторонний блок в 60 c.
    assert 0.0 <= aligned[0].t_start < 60.0
    assert aligned[0].confidence >= 0.70
