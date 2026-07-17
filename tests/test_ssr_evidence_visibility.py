"""B2: сырая EvidenceItem-диагностика SSR видна только на tier 5 (panel:debug_summary).

Обычный пользователь не должен видеть строки вроде «source-trust» или
«Локальный руль SSR» даже после раскрытия «Как выбрана подсказка».
Человекочитаемые секции («Другие варианты», «Если выбрать иначе», «Маршрут»)
остаются доступны всем.
"""
from __future__ import annotations

from app.smart_study_recommendation import SmartStudyRecommendation
from app.ui import mission_control as mc

_RAW_EVIDENCE_LINES = [
    "Очередь flashcards (локально): нет срочных (0)",
    "Коррекция по опоре на базу (source-trust): нет",
    "Локальный руль SSR (сохранено): нет (базовая политика)",
]


def _sample_rec() -> SmartStudyRecommendation:
    return SmartStudyRecommendation(
        hint_kind="answer_ready",
        primary_label_ru="Свериться с базой",
        why_now_ru="Готов быстрый ответ по индексу.",
        primary_nav="qa_continue",
        secondaries=(),
        route_pedagogy_ru="Короткая сверка с источниками помогает зайти в тему уверенно.",
        ml_audit_ru="trace: recovery_ladder_step=1",
    )


def _patched_evidence(_index_stats=None):
    return list(_RAW_EVIDENCE_LINES)


def test_non_debug_user_does_not_see_raw_evidence(monkeypatch):
    monkeypatch.setattr(mc, "build_ssr_evidence_for_banner", _patched_evidence)
    monkeypatch.setattr(mc, "feature_visible_by_id", lambda _fid, **_kw: False)

    html_out = mc._build_ssr_banner_html(_sample_rec(), index_stats=None)

    assert "source-trust" not in html_out
    assert "Локальный руль SSR" not in html_out
    # Человекочитаемые секции остаются для всех.
    assert "Другие варианты" in html_out
    assert "Если выбрать иначе" in html_out
    assert "Маршрут" in html_out


def test_debug_user_sees_full_evidence(monkeypatch):
    monkeypatch.setattr(mc, "build_ssr_evidence_for_banner", _patched_evidence)
    monkeypatch.setattr(mc, "feature_visible_by_id", lambda _fid, **_kw: True)

    html_out = mc._build_ssr_banner_html(_sample_rec(), index_stats=None)

    assert "source-trust" in html_out
    assert "Локальный руль SSR" in html_out
    assert 'data-testid="e2e-ssr-evidence"' in html_out
    # Человекочитаемые секции по-прежнему на месте.
    assert "Другие варианты" in html_out
    assert "Маршрут" in html_out


def test_debug_gate_only_affects_panel_debug_summary(monkeypatch):
    """feature_visible_by_id вызывается именно для panel:debug_summary."""
    monkeypatch.setattr(mc, "build_ssr_evidence_for_banner", _patched_evidence)
    seen_ids: list[str] = []

    def _gate(feature_id: str, **_kw: object) -> bool:
        seen_ids.append(feature_id)
        return False

    monkeypatch.setattr(mc, "feature_visible_by_id", _gate)
    mc._build_ssr_banner_html(_sample_rec(), index_stats=None)

    assert "panel:debug_summary" in seen_ids


def test_ml_audit_tail_also_hidden_for_non_debug(monkeypatch):
    """ml_audit_ru — тоже сырая диагностика; не должна светиться без tier 5."""
    monkeypatch.setattr(mc, "build_ssr_evidence_for_banner", _patched_evidence)
    monkeypatch.setattr(mc, "feature_visible_by_id", lambda _fid, **_kw: False)

    html_out = mc._build_ssr_banner_html(_sample_rec(), index_stats=None)

    assert "recovery_ladder_step" not in html_out


def test_banner_heading_uses_primary_label_ru(monkeypatch):
    """Заголовок баннера отражает конкретную рекомендацию, а не статичный текст."""
    monkeypatch.setattr(mc, "build_ssr_evidence_for_banner", _patched_evidence)
    monkeypatch.setattr(mc, "feature_visible_by_id", lambda _fid, **_kw: False)

    html_out = mc._build_ssr_banner_html(_sample_rec(), index_stats=None)

    assert '<h2 id="mc_ssr_heading">Свериться с базой</h2>' in html_out


def test_banner_heading_falls_back_when_primary_label_ru_blank(monkeypatch):
    """Пустой primary_label_ru не должен рендериться как пустой заголовок."""
    monkeypatch.setattr(mc, "build_ssr_evidence_for_banner", _patched_evidence)
    monkeypatch.setattr(mc, "feature_visible_by_id", lambda _fid, **_kw: False)

    rec = _sample_rec()
    blank_rec = mc.SmartStudyRecommendation(
        hint_kind=rec.hint_kind,
        primary_label_ru="   ",
        why_now_ru=rec.why_now_ru,
        primary_nav=rec.primary_nav,
        secondaries=rec.secondaries,
        route_pedagogy_ru=rec.route_pedagogy_ru,
        ml_audit_ru=rec.ml_audit_ru,
    )
    html_out = mc._build_ssr_banner_html(blank_rec, index_stats=None)

    assert '<h2 id="mc_ssr_heading">С чего можно продолжить</h2>' in html_out
