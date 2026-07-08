"""
Knowledge graph: JSON-backed reader (MVP) + tutor helpers (next step, prerequisites).

Путь по умолчанию: ``DATA_DIR / "concept_graph.json"``. Совместимо с ADR-020
(PropertyGraphIndex) как отдельный read-path позже.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.config import DATA_DIR
from app.knowledge_graph_bundle import (
    KnowledgeGraphBundleError,
    load_graph_snapshot_payload,
    write_graph_snapshot_payload,
)
from app.knowledge_graph_payload import (
    build_graph_payload_from_documents,
    _ensure_concept_provenance_defaults,
    _parse_iso_datetime,
)

logger = logging.getLogger(__name__)

GRADUATION_STABILITY_DAYS = 7


def _tarjan_sccs(vertices: List[str], adj: Dict[str, List[str]]) -> List[List[str]]:
    """Tarjan SCC decomposition; ``adj`` maps node -> direct successors."""
    index_counter = [0]
    stack: List[str] = []
    index: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    on_stack: set[str] = set()
    sccs: List[List[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            comp: List[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)

    for v in vertices:
        if v not in index:
            strongconnect(v)
    return sccs


class KnowledgeGraphReader:
    """Интерфейс чтения графа (pipeline / API / UI)."""

    def get_concepts(self) -> Dict[str, Dict]:
        raise NotImplementedError

    def get_typed_relations(self) -> List[Dict[str, Any]]:
        """Semantic relations emitted by the course graph compiler."""
        return []

    def get_document_concepts(self, doc_id: str) -> List[str]:
        raise NotImplementedError

    def get_prerequisites(self, concept_id: str) -> List[str]:
        raise NotImplementedError

    def get_related_documents(self, concept_id: str) -> List[str]:
        raise NotImplementedError

    def find_prerequisite_cycles(self, concept_ids: List[str]) -> List[List[str]]:
        """Циклы в подграфе prerequisites (рёбра: prerequisite -> узел)."""
        raise NotImplementedError

    def topological_sort(
        self,
        concept_ids: List[str],
        trace: Dict[str, Any] | None = None,
    ) -> List[str]:
        raise NotImplementedError


class JsonKnowledgeGraph(KnowledgeGraphReader):
    """JSON-граф: ``concepts``, опционально ``documents`` / ``edges``."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DATA_DIR / "concept_graph.json"
        self._data: Dict[str, Any] = {"concepts": {}, "documents": {}, "edges": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
                self._data.setdefault("concepts", {})
                self._data.setdefault("documents", {})
                self._data.setdefault("edges", {})
                _ensure_concept_provenance_defaults(self._data)
                for _name, c in self._data.get("concepts", {}).items():
                    if isinstance(c, dict):
                        c.setdefault("learned", False)
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning("knowledge_graph_load_failed | path=%s error=%s", self.path, e)
            self._data = {"concepts": {}, "documents": {}, "edges": {}}

    def save(self) -> None:
        """Сохранить текущий граф в JSON."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("knowledge_graph_save_failed | path=%s error=%s", self.path, e)

    def get_concepts(self) -> Dict[str, Dict]:
        return dict(self._data.get("concepts", {}))

    def get_typed_relations(self) -> List[Dict[str, Any]]:
        relations = self._data.get("typed_relations") or []
        return [dict(item) for item in relations if isinstance(item, dict)]

    def get_document_concepts(self, doc_id: str) -> List[str]:
        for cid, doc in self._data.get("documents", {}).items():
            if cid == doc_id:
                return list(doc.get("concepts", []) or [])
        for concept in self._data.get("concepts", {}).values():
            if doc_id in concept.get("documents", []):
                return list(concept.get("concepts", []))
        return []

    def get_prerequisites(self, concept_id: str) -> List[str]:
        c = self.get_concepts().get(concept_id, {})
        prereq = c.get("prerequisites") or c.get("prerequisite_for") or []
        return list(prereq)

    def get_related_documents(self, concept_id: str) -> List[str]:
        c = self.get_concepts().get(concept_id, {})
        return list(c.get("related_documents", c.get("documents", [])))

    def _prerequisite_successor_adjacency(self, concept_ids: List[str]) -> Dict[str, List[str]]:
        """Ориентированные рёбра prerequisite -> concept (для топологической сортировки)."""
        concepts = self.get_concepts()
        ids = set(concept_ids)
        adj: Dict[str, List[str]] = {cid: [] for cid in concept_ids}
        for cid in concept_ids:
            c = concepts.get(cid, {})
            prereqs = list(c.get("prerequisites", [])) or list(c.get("prerequisite_for", []))
            for p in prereqs:
                ps = str(p).strip()
                if ps in ids:
                    adj[ps].append(cid)
        return adj

    def find_prerequisite_cycles(self, concept_ids: List[str]) -> List[List[str]]:
        """
        Возвращает список циклов в подграфе по ``concept_ids``.
        Каждый элемент — упорядоченный набор узлов SCC (при |SCC|>1) или один узел при self-loop.
        """
        if not concept_ids:
            return []
        adj = self._prerequisite_successor_adjacency(concept_ids)
        sccs = _tarjan_sccs(list(concept_ids), adj)
        out: List[List[str]] = []
        for comp in sccs:
            if len(comp) > 1:
                out.append(sorted(comp))
            elif len(comp) == 1:
                u = comp[0]
                successors = adj.get(u, [])
                if u in successors:
                    out.append([u])
        return out

    def topological_sort(
        self,
        concept_ids: List[str],
        trace: Dict[str, Any] | None = None,
    ) -> List[str]:
        cycles = self.find_prerequisite_cycles(concept_ids)
        if cycles:
            logger.warning(
                "topological_sort_prerequisite_cycles | count=%s cycles=%s",
                len(cycles),
                cycles[:5],
            )
        concepts = self.get_concepts()
        graph: Dict[str, List[str]] = {}
        indeg: Dict[str, int] = {}
        for cid in concept_ids:
            c = concepts.get(cid, {})
            prereqs = list(c.get("prerequisites", [])) or list(c.get("prerequisite_for", []))
            graph[cid] = prereqs
            indeg[cid] = len(prereqs)
        from collections import deque

        q = deque([cid for cid in concept_ids if indeg.get(cid, 0) == 0])
        order: List[str] = []
        while q:
            n = q.popleft()
            order.append(n)
            for m, prereqs in graph.items():
                if n in prereqs:
                    indeg[m] = indeg.get(m, 0) - 1
                    if indeg[m] == 0:
                        q.append(m)
        ok = len(order) == len(concept_ids)
        if trace is not None:
            trace["prerequisite_cycles"] = cycles
            trace["topological_order_ok"] = ok
            if not ok:
                trace["fallback"] = "identity_order"
        if not ok:
            return list(concept_ids)
        return order

    # --- Tutor / AI helpers (итерация 19.1) ---

    def next_best_action(self, current_concept: str, learned_concepts: List[str]) -> Dict[str, Any]:
        """Следующий шаг: концепт, у которого ``current_concept`` в prerequisites."""
        concepts = self._data.get("concepts", {})
        learned = set(learned_concepts)
        if current_concept not in concepts:
            return {
                "action": "explore_new",
                "concept": "Общая_тема",
                "reason": "Концепт не найден в графе",
            }

        candidates: List[Tuple[str, int]] = []
        for target, data in concepts.items():
            if target in learned:
                continue
            prereqs = list(data.get("prerequisites", []))
            if current_concept in prereqs:
                candidates.append((target, len(prereqs)))

        if not candidates:
            return {
                "action": "deepen",
                "concept": current_concept,
                "reason": "Углубление текущей темы",
            }

        candidates.sort(key=lambda x: x[1])
        next_concept = candidates[0][0]
        return {
            "action": "next_concept",
            "concept": next_concept,
            "reason": f"Логическое продолжение после {current_concept}",
            "prerequisites_met": True,
        }

    def recommend_tutor_next_step(
        self,
        *,
        current_concept: str,
        learned_concepts: List[str] | None = None,
        route: str | None = None,
        due_review_preview: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Mode-aware tutor recommendation backed by graph progression and review state."""
        topic = (current_concept or "").strip() or "\u041e\u0431\u0449\u0430\u044f_\u0442\u0435\u043c\u0430"
        learned = [str(item).strip() for item in (learned_concepts or []) if str(item).strip()]
        due_preview = [str(item).strip() for item in (due_review_preview or []) if str(item).strip()]
        route_key = (route or "").strip().lower() or "standard"
        graph_step = self.next_best_action(topic, learned)
        next_concept = str(graph_step.get("concept") or topic).strip() or topic
        graph_reason = str(graph_step.get("reason") or "").strip()
        _reason_fallback_advance = (
            "\u0413\u0440\u0430\u0444 \u043f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442 \u0433\u043e\u0442\u043e\u0432\u043d\u043e\u0441\u0442\u044c \u043a \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u043c\u0443 \u0448\u0430\u0433\u0443."
        )
        _reason_fallback_standard = (
            "\u042d\u0442\u043e \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442 \u0441\u0432\u044f\u0437\u043d\u043e\u0435 \u043f\u0440\u043e\u0434\u0432\u0438\u0436\u0435\u043d\u0438\u0435 \u043f\u043e \u0433\u0440\u0430\u0444\u0443 \u0437\u043d\u0430\u043d\u0438\u0439."
        )

        if route_key == "due_review":
            focus = due_preview[0] if due_preview else topic
            return {
                "next_action": "\u041f\u043e\u0440\u0430 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c",
                "next_action_reason": (
                    f"\u0421\u0435\u0439\u0447\u0430\u0441 \u0432\u0430\u0436\u043d\u0435\u0435 \u043e\u0441\u0432\u0435\u0436\u0438\u0442\u044c \u0442\u0435\u043c\u0443 {focus}: \u0435\u0441\u0442\u044c pending review, \u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0435\u043d\u0438\u0435 \u043b\u0443\u0447\u0448\u0435 "
                    "\u0437\u0430\u043a\u0440\u0435\u043f\u0438\u0442 \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b \u043f\u0435\u0440\u0435\u0434 \u043f\u0435\u0440\u0435\u0445\u043e\u0434\u043e\u043c \u043a \u043d\u043e\u0432\u043e\u043c\u0443 \u0448\u0430\u0433\u0443."
                ),
                "suggested_ctas": [
                    "\u041f\u043e\u0440\u0430 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c",
                    "\u041f\u0440\u043e\u0432\u0435\u0440\u044c \u043c\u0435\u043d\u044f",
                    "\u0414\u0430\u0439 \u043f\u0440\u0438\u043c\u0435\u0440",
                    "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433",
                ],
                "graph_recommendation": graph_step,
            }

        if route_key == "targeted_reinforcement":
            return {
                "next_action": "\u0414\u0430\u0439 \u043f\u0440\u0438\u043c\u0435\u0440",
                "next_action_reason": (
                    f"\u0422\u0435\u043a\u0443\u0449\u0443\u044e \u0442\u0435\u043c\u0443 {topic} \u043b\u0443\u0447\u0448\u0435 \u0437\u0430\u043a\u0440\u0435\u043f\u0438\u0442\u044c \u043d\u0430 \u043f\u0440\u0438\u043c\u0435\u0440\u0435, \u0447\u0442\u043e\u0431\u044b \u0441\u043d\u044f\u0442\u044c \u0441\u043b\u0430\u0431\u043e\u0435 \u043c\u0435\u0441\u0442\u043e; "
                    f"\u043f\u043e\u0441\u043b\u0435 \u044d\u0442\u043e\u0433\u043e \u0431\u0443\u0434\u0435\u0442 \u043f\u0440\u043e\u0449\u0435 \u043f\u0435\u0440\u0435\u0439\u0442\u0438 \u043a {next_concept}."
                ),
                "suggested_ctas": [
                    "\u0414\u0430\u0439 \u043f\u0440\u0438\u043c\u0435\u0440",
                    "\u041f\u0440\u043e\u0432\u0435\u0440\u044c \u043c\u0435\u043d\u044f",
                    "\u041e\u0431\u044a\u044f\u0441\u043d\u0438 \u043f\u0440\u043e\u0449\u0435",
                    "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433",
                ],
                "graph_recommendation": graph_step,
            }

        if route_key == "foundation":
            return {
                "next_action": "\u041e\u0431\u044a\u044f\u0441\u043d\u0438 \u043f\u0440\u043e\u0449\u0435",
                "next_action_reason": (
                    f"\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0441\u0442\u043e\u0438\u0442 \u0443\u043f\u0440\u043e\u0441\u0442\u0438\u0442\u044c \u0431\u0430\u0437\u043e\u0432\u043e\u0435 \u043e\u0431\u044a\u044f\u0441\u043d\u0435\u043d\u0438\u0435 \u043f\u043e \u0442\u0435\u043c\u0435 {topic}, \u0447\u0442\u043e\u0431\u044b \u0437\u0430\u0442\u0435\u043c \u0431\u0435\u0437 \u043f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u0430 "
                    f"\u0434\u043e\u0439\u0442\u0438 \u0434\u043e \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0433\u043e \u0448\u0430\u0433\u0430 {next_concept}."
                ),
                "suggested_ctas": [
                    "\u041e\u0431\u044a\u044f\u0441\u043d\u0438 \u043f\u0440\u043e\u0449\u0435",
                    "\u041f\u0440\u043e\u0432\u0435\u0440\u044c \u043c\u0435\u043d\u044f",
                    "\u0414\u0430\u0439 \u043f\u0440\u0438\u043c\u0435\u0440",
                    "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433",
                ],
                "graph_recommendation": graph_step,
            }

        if route_key == "advance":
            return {
                "next_action": "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433",
                "next_action_reason": (
                    f"\u041c\u043e\u0436\u043d\u043e \u0434\u0432\u0438\u0433\u0430\u0442\u044c\u0441\u044f \u0434\u0430\u043b\u044c\u0448\u0435 \u043a \u0442\u0435\u043c\u0435 {next_concept}. "
                    f"{graph_reason or _reason_fallback_advance}"
                ),
                "suggested_ctas": [
                    "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433",
                    "\u0414\u0430\u0439 \u0437\u0430\u0434\u0430\u0447\u0443 \u043d\u0430 \u043f\u0440\u0438\u043c\u0435\u043d\u0435\u043d\u0438\u0435",
                    "\u041f\u0440\u043e\u0432\u0435\u0440\u044c \u043c\u0435\u043d\u044f",
                    "\u0414\u0430\u0439 \u043f\u0440\u0438\u043c\u0435\u0440",
                ],
                "graph_recommendation": graph_step,
            }

        return {
            "next_action": (
                "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433"
                if graph_step.get("action") == "next_concept"
                else "\u041f\u0440\u043e\u0432\u0435\u0440\u044c \u043c\u0435\u043d\u044f"
            ),
            "next_action_reason": (
                f"\u041b\u043e\u0433\u0438\u0447\u043d\u044b\u0439 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433 \u043f\u043e\u0441\u043b\u0435 {topic}: {next_concept}. "
                f"{graph_reason or _reason_fallback_standard}"
            ),
            "suggested_ctas": [
                "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433",
                "\u041f\u0440\u043e\u0432\u0435\u0440\u044c \u043c\u0435\u043d\u044f",
                "\u0414\u0430\u0439 \u043f\u0440\u0438\u043c\u0435\u0440",
                "\u041e\u0431\u044a\u044f\u0441\u043d\u0438 \u043f\u0440\u043e\u0449\u0435",
            ],
            "graph_recommendation": graph_step,
        }

    def check_prerequisites(self, concept: str, learned: List[str]) -> Tuple[bool, List[str]]:
        """Все ли prerequisites для ``concept`` есть в ``learned``."""
        concepts = self._data.get("concepts", {})
        if concept not in concepts:
            return True, []
        required = list(concepts[concept].get("prerequisites", []))
        learned_set = set(learned)
        missing = [p for p in required if p not in learned_set]
        return len(missing) == 0, missing

    def get_graph_summary(self, learned_concepts: List[str] | None = None) -> str:
        """Краткая строка для промптов (tutor)."""
        learned_concepts = learned_concepts or []
        all_c = self._data.get("concepts", {})
        total = len(all_c)
        if total == 0:
            return "В графе пока нет концептов (0% прогресса)."
        progress = len([c for c in learned_concepts if c in all_c])
        pct = (progress / total) * 100.0
        return (
            f"Всего концептов: {total}. Изучено из списка: {progress}. "
            f"Прогресс по покрытию графа: {pct:.0f}%."
        )

    def remove_prerequisite_edge(self, concept_id: str, prerequisite_id: str) -> bool:
        """
        Удалить одно ребро prerequisite → ``concept_id`` в JSON и синхронизировать ``edges``.
        Ручная коррекция после ``find_prerequisite_cycles`` (без отдельного UI в MVP).
        """
        bucket = self._data.setdefault("concepts", {})
        node = bucket.get(concept_id)
        if not isinstance(node, dict):
            return False
        prereqs = list(node.get("prerequisites") or [])
        if prerequisite_id not in prereqs:
            return False
        node["prerequisites"] = [p for p in prereqs if p != prerequisite_id]
        edges = self._data.setdefault("edges", {})
        if isinstance(edges, dict) and concept_id in edges:
            e = edges[concept_id]
            if isinstance(e, list) and prerequisite_id in e:
                edges[concept_id] = [x for x in e if x != prerequisite_id]
        self.save()
        return True

    def add_concept(
        self,
        name: str,
        description: str,
        prerequisites: List[str],
    ) -> None:
        """Добавить или обновить концепт."""
        self._data.setdefault("concepts", {})
        existing = self._data["concepts"].get(name, {})
        self._data["concepts"][name] = {
            **existing,
            "description": description,
            "prerequisites": list(prerequisites),
        }
        self.save()

    def rebuild_from_ingestion_documents(self, documents: List[Any]) -> Dict[str, Any]:
        """Rebuild graph state from ingestion metadata while preserving learned progress."""
        existing_concepts = self.get_concepts()
        payload = build_graph_payload_from_documents(documents, existing_concepts)
        relation_count = int(payload.pop("_relation_count", 0))
        self._data = {
            "concepts": payload["concepts"],
            "documents": payload["documents"],
            "edges": payload["edges"],
            "generated_at": payload.get("generated_at"),
            "source_doc_count": payload.get("source_doc_count"),
            "source_concept_count": payload.get("source_concept_count"),
        }
        self.save()
        documents_bucket = self._data.get("documents") or {}
        concepts_bucket = self._data.get("concepts") or {}
        logger.info(
            "knowledge_graph_rebuilt_from_ingestion | documents=%s concepts=%s relations=%s path=%s",
            len(documents_bucket),
            len(concepts_bucket),
            relation_count,
            self.path,
        )
        return {
            "documents": len(documents_bucket),
            "concepts": len(concepts_bucket),
            "relations": relation_count,
            "path": str(self.path),
        }

    def get_concept(self, name: str) -> Dict[str, Any] | None:
        return self._data.get("concepts", {}).get(name)

    def mark_concepts_as_learned(self, concepts: List[str]) -> int:
        """Помечает концепты как изученные (после успешного quiz и т.п.), сохраняет JSON."""
        names = [c.strip() for c in concepts if c and str(c).strip()]
        if not names:
            return 0
        bucket = self._data.setdefault("concepts", {})
        updated = 0
        now = datetime.now().isoformat()
        for name in names:
            if name not in bucket:
                continue
            node = bucket[name]
            if not isinstance(node, dict):
                continue
            node["learned"] = True
            node["learned_at"] = now
            updated += 1
        if updated > 0:
            self.save()
            logger.info("knowledge_graph_mark_learned | count=%s", updated)
        return updated

    def refresh_concept_graduation(
        self,
        quiz_mastery_rows: List[Dict[str, Any]],
        *,
        now: datetime | None = None,
        stability_days: int = GRADUATION_STABILITY_DAYS,
    ) -> Dict[str, str]:
        """Update concept graduation status from transfer-level quiz mastery history."""
        bucket = self._data.setdefault("concepts", {})
        if not isinstance(bucket, dict):
            return {}

        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        else:
            current = current.astimezone(timezone.utc)
        threshold_days = max(0, int(stability_days))
        statuses: Dict[str, str] = {}
        seen_concepts: set[str] = set()
        changed = False

        for row in quiz_mastery_rows or []:
            concept = str((row or {}).get("concept") or "").strip()
            if not concept or concept not in bucket:
                continue
            seen_concepts.add(concept)
            node = bucket.get(concept)
            if not isinstance(node, dict):
                continue

            level = str((row or {}).get("current_level") or "").strip().lower()
            if level != "transfer":
                statuses[concept] = "not graduated yet"
                updates = {
                    "graduated": False,
                    "graduation_status": "not graduated yet",
                    "graduation_basis": "mastery_not_transfer",
                }
                for key, value in updates.items():
                    if node.get(key) != value:
                        node[key] = value
                        changed = True
                continue

            transfer_at_raw = (row or {}).get("last_updated")
            transfer_at = _parse_iso_datetime(transfer_at_raw)
            stable = transfer_at is not None and (current - transfer_at) > timedelta(days=threshold_days)
            status = "graduated" if stable else "not graduated yet"
            statuses[concept] = status

            updates: Dict[str, Any] = {
                "graduated": stable,
                "graduation_status": status,
                "graduation_basis": (
                    f"transfer_stable_gt_{threshold_days}d" if stable else "transfer_history_not_stable"
                ),
            }
            if transfer_at is not None:
                updates["transfer_confirmed_at"] = transfer_at.isoformat()
            if stable:
                updates["graduated_at"] = current.isoformat()
                updates["learned"] = True
                if not node.get("learned_at"):
                    updates["learned_at"] = transfer_at.isoformat()

            for key, value in updates.items():
                if node.get(key) != value:
                    node[key] = value
                    changed = True

        if not quiz_mastery_rows:
            for concept, node in bucket.items():
                concept_id = str(concept or "").strip()
                if not concept_id or concept_id in seen_concepts or not isinstance(node, dict):
                    continue
                statuses[concept_id] = "not graduated yet"
                updates = {
                    "graduated": False,
                    "graduation_status": "not graduated yet",
                    "graduation_basis": "mastery_history_empty",
                }
                for key, value in updates.items():
                    if node.get(key) != value:
                        node[key] = value
                        changed = True

        if changed:
            self.save()
            logger.info("knowledge_graph_refresh_graduation | count=%s", len(statuses))
        return statuses

    def graduated_concept_ids(self) -> set[str]:
        """Concept ids with an active graduated status."""
        out: set[str] = set()
        for concept, node in self._data.get("concepts", {}).items():
            if (
                isinstance(node, dict)
                and node.get("graduated") is True
                and str(node.get("graduation_status") or "").strip() == "graduated"
            ):
                out.add(str(concept))
        return out

    def get_progress_stats(self) -> Dict[str, Any]:
        """Сводка для дашборда: mastery, распределение по level, timeline изученных."""
        concepts = self._data.get("concepts", {})
        total = len(concepts)
        learned = sum(
            1 for c in concepts.values() if isinstance(c, dict) and c.get("learned")
        )
        mastery = round((learned / total * 100.0), 1) if total else 0.0

        levels: Dict[str, int] = {"beginner": 0, "intermediate": 0, "advanced": 0}
        for c in concepts.values():
            if not isinstance(c, dict):
                continue
            lvl = (c.get("level") or "intermediate")
            if isinstance(lvl, str):
                lvl = lvl.strip().lower()
            else:
                lvl = "intermediate"
            if lvl not in levels:
                lvl = "intermediate"
            levels[lvl] = levels.get(lvl, 0) + 1

        timeline: List[Tuple[str, str]] = []
        for name, c in concepts.items():
            if not isinstance(c, dict):
                continue
            la = c.get("learned_at")
            if la and c.get("learned"):
                timeline.append((str(la), str(name)))
        timeline.sort(key=lambda x: x[0], reverse=True)
        timeline = timeline[:10]

        return {
            "total_concepts": total,
            "learned": learned,
            "mastery_percent": mastery,
            "level_distribution": levels,
            "recent_timeline": timeline,
        }

    def _prerequisite_readiness_score(
        self, concept_id: str, user_mastery_pct: Dict[str, float]
    ) -> float:
        """0..1: насколько сильны prerequisites (по шкале освоения)."""
        prereqs = self.get_prerequisites(concept_id)
        if not prereqs:
            return 1.0
        vals = [float(user_mastery_pct.get(str(p), 0.0)) / 100.0 for p in prereqs]
        return min(vals) if vals else 1.0

    def get_next_best_actions(
        self,
        user_mastery_pct: Dict[str, float],
        *,
        limit: int = 3,
        due_priority: Dict[str, float] | None = None,
        trace: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Ранжирование концептов: слабые места + готовность prerequisites + очередь spaced repetition.
        ``user_mastery_pct``: ``concept_id -> 0..100``.
        При ``trace`` заполняются поля топосортировки (циклы, fallback), как у ``topological_sort``.
        """
        lim = max(1, min(20, int(limit)))
        concepts = self.get_concepts()
        all_ids = [cid for cid, c in concepts.items() if isinstance(c, dict)]
        if not all_ids:
            if trace is not None:
                trace["topological_order_ok"] = True
                trace["prerequisite_cycles"] = []
            return []

        topo_trace: Dict[str, Any] = {}
        topo = self.topological_sort(all_ids, trace=topo_trace)
        if trace is not None:
            trace["topological_order_ok"] = topo_trace.get("topological_order_ok")
            trace["prerequisite_cycles"] = topo_trace.get("prerequisite_cycles") or []
            if topo_trace.get("fallback"):
                trace["topological_fallback"] = topo_trace["fallback"]
        due = due_priority or {}
        scored: List[Tuple[str, float, Dict[str, Any]]] = []
        for concept in topo:
            m = float(user_mastery_pct.get(concept, 0.0))
            m = max(0.0, min(100.0, m))
            weak = (100.0 - m) / 100.0 * 0.4
            prereq = self._prerequisite_readiness_score(concept, user_mastery_pct) * 0.3
            spaced = float(due.get(concept, 0.0)) * 0.3
            total = weak + prereq + spaced
            scored.append(
                (
                    concept,
                    total,
                    {
                        "weak_component": round(weak, 4),
                        "prerequisite_component": round(prereq, 4),
                        "spaced_component": round(spaced, 4),
                    },
                )
            )

        scored.sort(key=lambda x: -x[1])
        out: List[Dict[str, Any]] = []
        for concept, score, meta in scored[:lim]:
            out.append(
                {
                    "concept": concept,
                    "score": round(score, 4),
                    **meta,
                }
            )
        return out


class SqliteBundleKnowledgeGraph(JsonKnowledgeGraph):
    """Граф из каталога generation: payload в SQLite (итерация 16 tail / ADR-020)."""

    def __init__(self, bundle_dir: Path | str) -> None:
        self.bundle_dir = Path(bundle_dir)
        self._sqlite_path = self.bundle_dir / "kg.sqlite"
        self.path = self.bundle_dir / "concept_graph.json"
        self._data: Dict[str, Any] = {"concepts": {}, "documents": {}, "edges": {}}
        self._load()

    def _load(self) -> None:
        if not self._sqlite_path.exists():
            return
        try:
            payload = load_graph_snapshot_payload(self.bundle_dir)
            if not payload:
                return
            loaded = json.loads(payload)
            if isinstance(loaded, dict):
                self._data = loaded
                self._data.setdefault("concepts", {})
                self._data.setdefault("documents", {})
                self._data.setdefault("edges", {})
                _ensure_concept_provenance_defaults(self._data)
                for _name, c in self._data.get("concepts", {}).items():
                    if isinstance(c, dict):
                        c.setdefault("learned", False)
        except (json.JSONDecodeError, OSError, TypeError, KnowledgeGraphBundleError) as e:
            logger.warning("sqlite_bundle_kg_load_failed | path=%s error=%s", self._sqlite_path, e)
            self._data = {"concepts": {}, "documents": {}, "edges": {}}

    def save(self) -> None:
        try:
            payload = json.dumps(self._data, ensure_ascii=False)
            write_graph_snapshot_payload(self.bundle_dir, payload)
        except (OSError, KnowledgeGraphBundleError) as e:
            logger.error("sqlite_bundle_kg_save_failed | path=%s error=%s", self._sqlite_path, e)


def get_knowledge_graph(path: Path | str | None = None) -> KnowledgeGraphReader:
    """Фабрика: JSON-reader по умолчанию в ``DATA_DIR/concept_graph.json``."""
    return JsonKnowledgeGraph(path)


def get_personalized_subgraph(
    *,
    seed_topic: str | None = None,
    limit: int = 12,
    kg: JsonKnowledgeGraph | None = None,
) -> dict[str, Any]:
    """
    Компактный подграф вокруг темы + уровни ``quiz_mastery`` для graph-augmented промптов.

    ``user_id`` в однопользовательском режиме не нужен: mastery берётся из ``quiz_mastery``.
    """
    from app.quiz_adaptive import get_all_mastery_levels

    graph = kg or knowledge_graph
    topic = (seed_topic or "").strip() or "general"
    mastery_all = get_all_mastery_levels()
    concepts = graph.get_concepts()
    cluster: list[str] = []
    if topic in concepts:
        node = concepts.get(topic) or {}
        related = list(node.get("related_concepts") or [])
        if not related:
            related = list(node.get("examples") or [])
        prereqs = list(graph.get_prerequisites(topic))
        seen: set[str] = set()
        for x in [topic, *prereqs, *related]:
            s = str(x).strip()
            if s and s not in seen:
                seen.add(s)
                cluster.append(s)
            if len(cluster) >= max(1, limit):
                break
    else:
        cluster = [topic] if topic else []

    nodes: list[dict[str, Any]] = []
    for cid in cluster[: max(1, limit)]:
        lv = str(mastery_all.get(cid, "recognition")).strip()
        nodes.append(
            {
                "id": cid,
                "quiz_mastery_level": lv,
                "prerequisites": list(graph.get_prerequisites(cid))[:8],
            }
        )
    return {
        "seed_topic": topic,
        "nodes": nodes,
        "mastery": {n["id"]: n["quiz_mastery_level"] for n in nodes},
    }


def get_topic_subgraph(topic_identifier: str) -> dict[str, Any]:
    """
    Краткий срез по теме каталога KB: ключевые концепты и пути документов.
    ``topic_identifier`` — обычно ``topic_id`` из ``/topics``; иначе пробуем имя концепта из графа.
    """
    tid = (topic_identifier or "").strip()
    if not tid:
        return {"topic_name": "", "key_concepts": [], "documents": []}

    from app.knowledge_service import get_topics_catalog

    catalog = get_topics_catalog()
    for topic in catalog.get("topics") or []:
        if topic.get("topic_id") == tid:
            docs = [
                d.get("relative_path") or d.get("file_name")
                for d in (topic.get("documents") or [])
            ]
            return {
                "topic_name": topic.get("topic_name") or tid,
                "key_concepts": list(topic.get("key_concepts") or []),
                "documents": [x for x in docs if x],
            }

    concepts = knowledge_graph.get_concepts()
    node = concepts.get(tid)
    if isinstance(node, dict):
        rel = list(node.get("related_documents") or node.get("documents") or [])[:32]
        return {
            "topic_name": tid,
            "key_concepts": [tid],
            "documents": [x for x in rel if x],
        }

    return {"topic_name": tid, "key_concepts": [], "documents": []}


def synthesize_topic_summary(topic_id: str) -> str:
    """Текст конспекта по ``topic_id`` (тот же путь, что и learning plan / synthesis)."""
    from app.knowledge_service import synthesize_topic

    try:
        res = synthesize_topic(topic_id=topic_id)
    except ValueError:
        # Topic not in catalog (e.g. summary collection empty). Return empty so the
        # caller's "too little text" guard produces a user-facing message, not a 500.
        return ""
    return (res.get("summary") or "").strip()


def get_mastery_vector(
    user_id: str | None = None,
    *,
    concept_ids: List[str] | set[str] | None = None,
) -> Dict[str, float]:
    """
    Вектор освоения по концептам из ``quiz_mastery`` (0–1) + ``avg`` по известным концептам.
    ``user_id`` зарезервирован для мульти-пользователя; в локальном режиме не используется.
    """
    _ = user_id
    from app.quiz_adaptive import LEVEL_TO_MASTERY_PCT, get_all_mastery_levels

    levels = get_all_mastery_levels()
    concept_filter: set[str] | None = None
    if concept_ids is not None:
        concept_filter = {str(item).strip() for item in concept_ids if str(item).strip()}
    out: Dict[str, float] = {}
    for concept, lv in levels.items():
        c = str(concept or "").strip()
        if not c:
            continue
        if concept_filter is not None and c not in concept_filter:
            continue
        pct = int(LEVEL_TO_MASTERY_PCT.get(str(lv).strip().lower(), 44))
        out[c] = max(0.0, min(1.0, float(pct) / 100.0))
    if out:
        out["avg"] = sum(out.values()) / float(len(out))
    else:
        out["avg"] = 0.0
    return out


def write_staging_knowledge_graph_bundle(
    documents: List[Any],
    staging_chunks_collection: str,
    *,
    source_paths: list[str] | None = None,
    scope_hash: str = "",
    source_content_hashes: list[str] | None = None,
) -> Dict[str, Any]:
    """Собрать граф в staging-каталог; после swap вызывается promote в ``activate_staging_index``."""
    from app.course_cache import graph_llm_probe_ok
    from app.knowledge_graph_bundle import write_bundle_for_staging

    existing = get_active_knowledge_graph().get_concepts()
    use_compiler = graph_llm_probe_ok()
    return write_bundle_for_staging(
        documents,
        staging_chunks_collection,
        existing,
        source_paths=source_paths,
        scope_hash=scope_hash,
        source_content_hashes=source_content_hashes,
        use_compiler=use_compiler,
    )


def write_generation_knowledge_graph_bundle(
    documents: List[Any],
    generation_id: str,
    *,
    existing_concepts: Dict[str, Dict],
    source_paths: list[str] | None = None,
    scope_hash: str = "",
    source_content_hashes: list[str] | None = None,
) -> Dict[str, Any]:
    """Записать bundle в каталог generation (после ``activate_reset_generation``)."""
    from app.course_cache import graph_llm_probe_ok
    from app.knowledge_graph_bundle import write_bundle_for_generation

    use_compiler = graph_llm_probe_ok()
    return write_bundle_for_generation(
        documents,
        generation_id,
        existing_concepts,
        source_paths=source_paths,
        scope_hash=scope_hash,
        source_content_hashes=source_content_hashes,
        use_compiler=use_compiler,
    )


_kg_singleton: JsonKnowledgeGraph | SqliteBundleKnowledgeGraph | None = None
_kg_generation: str | None = None


def invalidate_knowledge_graph_singleton() -> None:
    global _kg_singleton, _kg_generation
    _kg_singleton = None
    _kg_generation = None


def _active_graph_bundle_target() -> tuple[str, Path]:
    """Resolve active graph bundle, falling back to the last promoted bundle."""
    from app.graph_generation_paths import generation_bundle_dir
    from app.index_registry import get_active_generation_view, load_registry

    active_gid = get_active_generation_view().generation_id
    active_dir = generation_bundle_dir(active_gid)
    if (active_dir / "kg.sqlite").exists():
        return active_gid, active_dir

    registry = load_registry()
    previous = registry.get("previous_generation") or {}
    previous_gid = str(previous.get("generation_id") or "").strip()
    if previous_gid and previous_gid != active_gid:
        previous_dir = generation_bundle_dir(previous_gid)
        if (previous_dir / "kg.sqlite").exists():
            logger.warning(
                "active_knowledge_graph_bundle_missing_use_previous | active_generation=%s | previous_generation=%s",
                active_gid,
                previous_gid,
            )
            return f"{active_gid}|fallback:{previous_gid}", previous_dir

    return active_gid, active_dir


def get_graph_prerequisites_health() -> Dict[str, Any]:
    """
    Сводка по графу prerequisites для API и learning-plan path: циклы и успех топосортировки.
    Не вызывает LLM; стабильный контракт для baseline-тестов.
    """
    kg = get_active_knowledge_graph()
    concepts = kg.get_concepts()
    all_ids = [cid for cid, c in concepts.items() if isinstance(c, dict)]
    id_set = set(all_ids)
    cycles = kg.find_prerequisite_cycles(all_ids)
    trace: Dict[str, Any] = {}
    kg.topological_sort(all_ids, trace=trace)
    topo_ok = bool(trace.get("topological_order_ok", True)) if trace else True
    relation_count = sum(
        len([p for p in (c.get("prerequisites") or []) if p in id_set])
        for c in concepts.values()
        if isinstance(c, dict)
    )
    return {
        "schema_version": 1,
        "concept_count": len(all_ids),
        "relation_count": relation_count,
        "cycle_count": len(cycles),
        "cycles": cycles,
        "has_prerequisite_cycles": len(cycles) > 0,
        "topological_order_ok": topo_ok,
    }


def get_active_knowledge_graph() -> JsonKnowledgeGraph:
    """Активный граф по ``generation_id`` из registry (bundle SQLite или legacy JSON)."""
    global _kg_singleton, _kg_generation

    cache_key, bundle_dir = _active_graph_bundle_target()
    if _kg_singleton is not None and _kg_generation == cache_key:
        return _kg_singleton
    sqlite_path = bundle_dir / "kg.sqlite"
    if sqlite_path.exists():
        _kg_singleton = SqliteBundleKnowledgeGraph(bundle_dir)
    else:
        _kg_singleton = JsonKnowledgeGraph(DATA_DIR / "concept_graph.json")
    _kg_generation = cache_key
    return _kg_singleton


def get_next_best_actions_for_user(
    *,
    limit: int = 8,
    due_limit: int = 200,
    trace: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    NBA для активного графа: mastery из quiz (`mastery_percent_for_level`) и due-priority из spaced repetition.
    Стабильный контракт для API и learning-plan; без LLM.
    """
    from app.quiz_adaptive import get_all_mastery_levels, mastery_percent_for_level
    from app.spaced_repetition import due_priority_by_concept

    kg = get_active_knowledge_graph()
    mastery_levels = get_all_mastery_levels()
    concepts = kg.get_concepts()
    user_pct: Dict[str, float] = {}
    for cid, node in concepts.items():
        if not isinstance(node, dict):
            continue
        lv = mastery_levels.get(cid, "recognition")
        user_pct[cid] = float(mastery_percent_for_level(lv))
    due_map = due_priority_by_concept(limit=due_limit)
    inner_trace: Dict[str, Any] = {}
    actions = kg.get_next_best_actions(
        user_pct,
        limit=limit,
        due_priority=due_map,
        trace=inner_trace,
    )
    lim = max(1, min(20, int(limit)))
    out: Dict[str, Any] = {
        "schema_version": 1,
        "limit": lim,
        "actions": actions,
        "topological_order_ok": bool(inner_trace.get("topological_order_ok", True)),
        "prerequisite_cycles": list(inner_trace.get("prerequisite_cycles") or []),
    }
    if inner_trace.get("topological_fallback"):
        out["topological_fallback"] = inner_trace["topological_fallback"]
    if trace is not None:
        trace.update(inner_trace)
    return out


def get_learning_plan_graph_bundle(
    *,
    nba_limit: int = 8,
    due_limit: int = 200,
    topo_preview_limit: int = 12,
) -> Dict[str, Any]:
    """Без-LLM снимок для learning-plan: prerequisites health + NBA + топопорядок (preview)."""
    health = get_graph_prerequisites_health()
    nba = get_next_best_actions_for_user(limit=nba_limit, due_limit=due_limit)
    kg = get_active_knowledge_graph()
    concepts = kg.get_concepts()
    all_ids = [cid for cid, c in concepts.items() if isinstance(c, dict)]
    topo_trace: Dict[str, Any] = {}
    order = kg.topological_sort(all_ids, trace=topo_trace)
    tlim = max(0, min(50, int(topo_preview_limit)))
    preview = order[:tlim]
    bundle: Dict[str, Any] = {
        "schema_version": 1,
        "prerequisites": health,
        "next_best_actions": {
            "limit": nba["limit"],
            "actions": nba["actions"],
            "topological_order_ok": nba["topological_order_ok"],
            "prerequisite_cycles": nba["prerequisite_cycles"],
        },
        "topological_preview": preview,
    }
    if nba.get("topological_fallback"):
        bundle["next_best_actions"]["topological_fallback"] = nba["topological_fallback"]
    if topo_trace.get("fallback"):
        bundle["topological_fallback"] = topo_trace["fallback"]
    return bundle


class _KnowledgeGraphProxy:
    """Ленивое разрешение активного generation без смены импортов в UI/pipeline."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_active_knowledge_graph(), name)


knowledge_graph = _KnowledgeGraphProxy()

__all__ = [
    "GRADUATION_STABILITY_DAYS",
    "JsonKnowledgeGraph",
    "KnowledgeGraphReader",
    "SqliteBundleKnowledgeGraph",
    "build_graph_payload_from_documents",
    "get_graph_prerequisites_health",
    "get_next_best_actions_for_user",
    "get_learning_plan_graph_bundle",
    "get_active_knowledge_graph",
    "get_knowledge_graph",
    "get_mastery_vector",
    "get_personalized_subgraph",
    "get_topic_subgraph",
    "invalidate_knowledge_graph_singleton",
    "knowledge_graph",
    "synthesize_topic_summary",
    "write_generation_knowledge_graph_bundle",
    "write_staging_knowledge_graph_bundle",
]
