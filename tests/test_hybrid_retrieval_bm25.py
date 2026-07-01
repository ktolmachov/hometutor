from app.hybrid_retrieval import _effective_bm25_top_k


def test_effective_bm25_top_k_caps_to_corpus_size():
    assert _effective_bm25_top_k(10, 6) == 6


def test_effective_bm25_top_k_keeps_requested_when_corpus_is_larger():
    assert _effective_bm25_top_k(5, 20) == 5


def test_effective_bm25_top_k_never_below_one():
    assert _effective_bm25_top_k(10, 0) == 10
