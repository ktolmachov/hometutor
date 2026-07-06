"""Инварианты выравнивания разделов конспекта по ASR-сегментам (anchor-lis-v1)."""

from __future__ import annotations

from app.media_alignment import (
    AlignedSection,
    TranscriptSegment,
    align_sections,
    compute_section_id,
)
from app.section_index import ParsedSection


def _section(heading: str, text: str, pos: int) -> ParsedSection:
    line = pos * 10 + 1
    return ParsedSection(
        heading_text=heading,
        slug=heading.lower().replace(" ", "-"),
        level=2,
        line_start=line,
        line_end=line + 8,
        text=text,
        own_text=text,
    )


def _segments_from_topics(topics: list[str], words_per_topic: int = 200) -> tuple[TranscriptSegment, ...]:
    """Синтетическая лекция: на каждую тему — свой словарь, 30 сек на сегмент."""
    segments: list[TranscriptSegment] = []
    t = 0.0
    for topic_idx, topic in enumerate(topics):
        vocab = [f"{topic}слово{i}" for i in range(words_per_topic)]
        for chunk_start in range(0, words_per_topic, 25):
            text = " ".join(vocab[chunk_start : chunk_start + 25])
            segments.append(TranscriptSegment(start=t, end=t + 30.0, text=text))
            t += 30.0
    return tuple(segments)


def _topic_text(topic: str, words: int = 40) -> str:
    return " ".join(f"{topic}слово{i}" for i in range(words))


def test_alignment_anchors_match_topics_in_order():
    topics = ["альфа", "бета", "гамма", "дельта"]
    segments = _segments_from_topics(topics)
    sections = [_section(f"Тема {t}", _topic_text(t), i) for i, t in enumerate(topics)]

    aligned = align_sections(sections, segments)

    assert len(aligned) == 4
    assert all(a.anchored for a in aligned), [a.confidence for a in aligned]
    starts = [a.t_start for a in aligned]
    assert starts == sorted(starts)
    # Каждая тема занимает 8 сегментов × 30 сек = 240 сек; якорь должен попасть в свой блок.
    for i, a in enumerate(aligned):
        assert i * 240.0 <= a.t_start < (i + 1) * 240.0, (i, a.t_start)
        assert a.confidence >= 0.70


def test_alignment_is_monotonic_even_with_confusable_sections():
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
    assert starts == sorted(starts), "таймкоды обязаны быть неубывающими"


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


def test_anchor_t_end_stretches_to_next_timestamp():
    topics = ["альфа", "бета"]
    segments = _segments_from_topics(topics)
    sections = [_section(f"Тема {t}", _topic_text(t), i) for i, t in enumerate(topics)]

    aligned = align_sections(sections, segments)

    assert aligned[0].t_end == aligned[1].t_start
    assert aligned[1].t_end == segments[-1].end


def test_alignment_survives_shared_vocabulary_between_topics():
    """Реалистичный случай: общие термины (модель, токен, агент…) звучат всю лекцию,
    темы различаются лишь частью лексики. Якоря обязаны остаться хронологичными и
    попасть в окно своей темы."""
    shared = " ".join(f"общий{i}" for i in range(15))  # фон, повторяющийся в каждом сегменте
    topics = ["альфа", "бета", "гамма", "дельта"]
    segments: list[TranscriptSegment] = []
    t = 0.0
    for topic in topics:
        for chunk in range(8):
            specific = " ".join(f"{topic}слово{chunk * 12 + i}" for i in range(12))
            segments.append(TranscriptSegment(start=t, end=t + 30.0, text=f"{shared} {specific}"))
            t += 30.0
    sections = [
        _section(
            f"Тема {topic}",
            f"{shared} " + " ".join(f"{topic}слово{i}" for i in range(30)),
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


def test_slide_order_rank_without_spoken_numbers():
    """Без номеров в речи: title-reading по хронологии слайдов."""
    segments = (
        TranscriptSegment(10.0, 15.0, "работает но не работает в проде"),
        TranscriptSegment(200.0, 205.0, "бюджет рантайма важен"),
    )
    sections = [
        ParsedSection(
            heading_text='Слайд 3: "Работает, но не работает"',
            slug="slide-3",
            level=3,
            line_start=1,
            line_end=9,
            text="текст " * 6,
            own_text="текст " * 6,
        ),
        ParsedSection(
            heading_text="Слайд 26: Бюджет рантайма",
            slug="slide-26",
            level=3,
            line_start=11,
            line_end=19,
            text="текст " * 6,
            own_text="текст " * 6,
        ),
    ]

    aligned = align_sections(sections, segments)

    assert aligned[0].anchored and aligned[0].confidence >= 0.70
    assert aligned[0].t_start == 10.0
    assert aligned[1].anchored and aligned[1].confidence >= 0.70
    assert aligned[1].t_start == 200.0
    assert aligned[0].t_start < aligned[1].t_start


def test_no_slide_cues_matches_lexical_baseline():
    """Конспект без слайдовых заголовков — поведение лексического anchor-lis-v1."""
    topics = ["альфа", "бета"]
    segments = _segments_from_topics(topics)
    sections = [_section(f"Тема {t}", _topic_text(t), i) for i, t in enumerate(topics)]

    aligned = align_sections(sections, segments)

    assert all(a.anchored for a in aligned)
    assert all(a.confidence >= 0.70 for a in aligned)
    starts = [a.t_start for a in aligned]
    assert starts == sorted(starts)
