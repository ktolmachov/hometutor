from app.ui.constants import ALL_VIEWS
from app.ui.feature_registry import FEATURES, feature_by_id, features_for_surface, validate_registry


def test_feature_registry_is_valid() -> None:
    validate_registry()


def test_feature_ids_are_unique() -> None:
    ids = [spec.id for spec in FEATURES]
    assert len(ids) == len(set(ids))


def test_nav_feature_view_names_exist_in_all_views() -> None:
    all_views = set(ALL_VIEWS)
    for spec in features_for_surface("nav"):
        assert spec.view_name in all_views


def test_feature_lookup_by_id() -> None:
    spec = feature_by_id("view:quick_answer")
    assert spec is not None
    assert spec.tier == 1
