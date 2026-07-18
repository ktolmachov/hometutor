"""P0-1: course boundaries and honest lesson floors in the course graph compiler."""

from __future__ import annotations

from types import SimpleNamespace

from app.course_graph_compiler import (
    NON_CURRICULUM_TOP_FOLDERS,
    _course_top_folder,
    _is_non_curriculum_path,
    _lesson_anchor_id,
    _lesson_canonical_path_key,
    compile_course_graph,
)


def _doc(path: str, *, title: str | None = None, chunk_id: str | None = None, text: str | None = None):
    return SimpleNamespace(
        text=text or f"Body of {path}",
        metadata={
            "doc_id": path,
            "relative_path": path,
            "chunk_id": chunk_id or f"chunk:{path}",
            "title": title or path,
            "file_name": path.rsplit("/", 1)[-1],
        },
    )


def _deterministic_extract(doc_id: str, _rows: list[dict]):
    """One concept per document, id derived from path stem — no LLM."""
    stem = doc_id.replace("\\", "/").rsplit("/", 1)[-1]
    for ext in (".md", ".txt", ".markdown"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    label = f"Concept {stem}"
    return (
        {
            "concepts": [
                {
                    "label": label,
                    "normalized_label": label,
                    "source_chunk_id": f"chunk:{doc_id}",
                }
            ],
            "relations": [],
        },
        None,
    )


def _lesson_nodes(payload: dict) -> dict[str, dict]:
    return {
        cid: node
        for cid, node in (payload.get("concepts") or {}).items()
        if isinstance(node, dict) and node.get("level") == "lesson"
    }


def _precedes_edges(payload: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for rel in payload.get("typed_relations") or []:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("relation_type") or "") != "precedes":
            continue
        out.append((str(rel.get("source_concept_id") or ""), str(rel.get("target_concept_id") or "")))
    return out


def _part_of_targets(payload: dict, concept_id: str) -> set[str]:
    targets: set[str] = set()
    for rel in payload.get("typed_relations") or []:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("relation_type") or "") != "part_of":
            continue
        if str(rel.get("source_concept_id") or "") != concept_id:
            continue
        targets.add(str(rel.get("target_concept_id") or ""))
    return targets


def test_non_curriculum_roots_helper():
    assert "living-konspekt" in NON_CURRICULUM_TOP_FOLDERS
    assert _course_top_folder("ИИ Агенты/урок_1.md") == "ИИ Агенты"
    assert _course_top_folder("course_a/lesson-1.txt") == "course_a"
    assert _course_top_folder("lone.md") == ""
    assert _is_non_curriculum_path("living-konspekt/foo.md") is True
    assert _is_non_curriculum_path("living-konspekt\\bar.txt") is True
    assert _is_non_curriculum_path("course_a/lesson-1.md") is False


def test_lesson_anchor_id_is_extension_agnostic():
    md_id = _lesson_anchor_id("course_a/lesson-1.md")
    txt_id = _lesson_anchor_id("course_a/lesson-1.txt")
    assert md_id == txt_id
    assert md_id.startswith("lesson:")
    assert not md_id.endswith("-md")
    assert not md_id.endswith("-txt")
    assert "-md" not in md_id
    assert "-txt" not in md_id
    # Same stem in different courses must not collide.
    other = _lesson_anchor_id("course_b/lesson-1.md")
    assert other != md_id
    assert _lesson_canonical_path_key("course_a/lesson-1.md") == "course_a/lesson-1"


def test_compile_groups_md_txt_excludes_living_konspekt_and_scopes_precedes():
    """Synthetic mega-bundle fixture: 2 courses × dual-format lessons + living-konspekt."""
    docs = [
        # Course A: two lessons, each as .md + .txt
        _doc("course_a/lesson-1.md", title="Lesson 1 Intro"),
        _doc("course_a/lesson-1.txt", title="Lesson 1 Intro"),
        _doc("course_a/lesson-2.md", title="Lesson 2 Tools"),
        _doc("course_a/lesson-2.txt", title="Lesson 2 Tools"),
        # Course B: one dual-format lesson + a second single-format lesson
        _doc("course_b/module-1.md", title="Module 1 Deep"),
        _doc("course_b/module-1.txt", title="Module 1 Deep"),
        _doc("course_b/module-2.md", title="Module 2 Evals"),
        # Non-curriculum personal note — must not become a lesson floor
        _doc("living-konspekt/working-notes.md", title="Working notes"),
    ]

    result = compile_course_graph(
        docs,
        generation_id="gen-p0-1",
        scope_hash="scope-p0-1",
        llm_extract_fn=_deterministic_extract,
    )
    assert result.error is None
    payload = result.payload
    lessons = _lesson_nodes(payload)

    # 4 curriculum lessons (not 7 files, not 8 with living-konspekt)
    assert len(lessons) == 4, sorted(lessons.keys())

    # living-konspekt never becomes a lesson node
    for cid, node in lessons.items():
        docs_for_lesson = node.get("documents") or []
        assert not any("living-konspekt" in str(p).replace("\\", "/") for p in docs_for_lesson)
        assert "living-konspekt" not in cid

    # md+txt of the same lesson → one node with both paths
    a1 = _lesson_anchor_id("course_a/lesson-1.md")
    assert a1 in lessons
    a1_docs = set(lessons[a1].get("documents") or [])
    assert "course_a/lesson-1.md" in a1_docs
    assert "course_a/lesson-1.txt" in a1_docs
    assert set(lessons[a1].get("related_documents") or []) == a1_docs
    assert lessons[a1].get("course") == "course_a"

    b1 = _lesson_anchor_id("course_b/module-1.md")
    assert b1 in lessons
    b1_docs = set(lessons[b1].get("documents") or [])
    assert "course_b/module-1.md" in b1_docs
    assert "course_b/module-1.txt" in b1_docs
    assert lessons[b1].get("course") == "course_b"

    # precedes only inside a top-folder
    precedes = _precedes_edges(payload)
    lesson_course = {cid: str(node.get("course") or "") for cid, node in lessons.items()}
    for src, tgt in precedes:
        assert src in lessons and tgt in lessons
        assert lesson_course[src] == lesson_course[tgt], (src, tgt, lesson_course)
        assert lesson_course[src], "precedes must stay inside a named course folder"

    # Course A has two lessons → exactly one precedes edge inside A
    a2 = _lesson_anchor_id("course_a/lesson-2.md")
    a_edges = {(s, t) for s, t in precedes if lesson_course.get(s) == "course_a"}
    assert a_edges == {(a1, a2)}

    # Course B has two lessons → one internal precedes, no cross-link to A
    b2 = _lesson_anchor_id("course_b/module-2.md")
    b_edges = {(s, t) for s, t in precedes if lesson_course.get(s) == "course_b"}
    assert b_edges == {(b1, b2)}
    assert not any(
        (lesson_course.get(s) == "course_a" and lesson_course.get(t) == "course_b")
        or (lesson_course.get(s) == "course_b" and lesson_course.get(t) == "course_a")
        for s, t in precedes
    )

    # Concepts from .md and .txt of the same lesson share part_of → common lesson node
    # Deterministic labels: "Concept lesson-1" from both md and txt merge into one concept.
    concepts = payload.get("concepts") or {}
    concept_ids = [
        cid
        for cid, node in concepts.items()
        if isinstance(node, dict) and node.get("level") != "lesson" and "lesson-1" in str(node.get("label") or "")
    ]
    assert concept_ids, "expected merged concept for lesson-1 dual files"
    for cid in concept_ids:
        targets = _part_of_targets(payload, cid)
        assert a1 in targets


def test_lone_file_without_folder_is_own_group_no_cross_course():
    docs = [
        _doc("standalone.md", title="Standalone"),
        _doc("course_a/lesson-1.md", title="In course"),
        _doc("course_a/lesson-2.md", title="In course 2"),
    ]
    result = compile_course_graph(
        docs,
        generation_id="gen-lone",
        scope_hash="scope-lone",
        llm_extract_fn=_deterministic_extract,
    )
    lessons = _lesson_nodes(result.payload)
    assert len(lessons) == 3
    precedes = _precedes_edges(result.payload)
    # Only course_a chain; standalone has no precedes partner in its empty folder group.
    a1 = _lesson_anchor_id("course_a/lesson-1.md")
    a2 = _lesson_anchor_id("course_a/lesson-2.md")
    lone = _lesson_anchor_id("standalone.md")
    assert lone in lessons
    assert (a1, a2) in precedes
    assert not any(lone in edge for edge in precedes)
