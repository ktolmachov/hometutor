from app.query_response_postprocessing import normalize_inline_numeric_citations


def test_normalize_inline_numeric_citations_remaps_invalid_single_source() -> None:
    answer, debug = normalize_inline_numeric_citations("ATP is energy currency [3].", 1)

    assert answer == "ATP is energy currency [1]."
    assert debug == {"changed": True, "invalid_indices": [3]}


def test_normalize_inline_numeric_citations_keeps_only_valid_mixed_indices() -> None:
    answer, debug = normalize_inline_numeric_citations("Use returned context [1, 4].", 2)

    assert answer == "Use returned context [1]."
    assert debug == {"changed": True, "invalid_indices": [4]}


def test_normalize_inline_numeric_citations_removes_markers_without_sources() -> None:
    answer, debug = normalize_inline_numeric_citations("Selected context is insufficient [2].", 0)

    assert answer == "Selected context is insufficient ."
    assert debug == {"changed": True, "invalid_indices": [2]}
