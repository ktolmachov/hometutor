"""Сборка/обновление media-sidecar конспекта: разделы ↔ таймкоды видео.

Берёт конспект (``.md`` в DATA_DIR), сегменты транскрипта (``.segments.json``
из ``scripts/transcribe_media.py``) и data-relative путь к видео; выравнивает
разделы по таймкодам (``app.media_alignment``, anchor-lis-v1) и пишет
``<konspekt>.media.json`` по схеме ``app.media_sidecar`` (schema_version=1).

Существующий sidecar не затирается вслепую: список видео (``media.videos``,
включая YouTube-ссылки) и картинки разделов сохраняются; обновляются таймкоды,
confidence, section_id и sha-поля инвалидации.

Примеры:
    python scripts/build_media_sidecar.py "ИИ Агенты/урок_2_как_агент_думает_и_действует.md" \
        --video "ИИ Агенты/урок_2_как_агент_думает_и_действует.mp4"
    python scripts/build_media_sidecar.py "ИИ Агенты/урок_2....md" --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.media_alignment import (  # noqa: E402
    ALIGNMENT_VERSION,
    align_sections,
    compute_section_id,
    load_segments_file,
)
from app.media_sidecar import parse_media_sidecar, sha256_file  # noqa: E402
from app.path_safety import resolve_data_relative_path  # noqa: E402
from app.section_index import parse_sections  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_konspekt(raw: str) -> tuple[Path, str]:
    """(абсолютный путь, data-relative строка) для конспекта.

    Абсолютный путь допустим только внутри DATA_DIR: sidecar-контракт хранит
    data-relative пути, конспект вне DATA_DIR им не адресуем.
    """
    data_root = resolve_data_relative_path(".").resolve()
    p = Path(raw)
    if p.is_absolute():
        abs_path = p.resolve()
        try:
            rel = abs_path.relative_to(data_root)
        except ValueError:
            raise SystemExit(
                f"Конспект {abs_path} лежит вне DATA_DIR ({data_root}) — "
                "sidecar-контракт требует data-relative путей."
            ) from None
        return abs_path, rel.as_posix()
    abs_path = resolve_data_relative_path(raw)
    return abs_path, raw.replace("\\", "/")


def _guess_segments_path(konspekt_abs: Path, video_rel: str | None) -> Path | None:
    candidates = [konspekt_abs.with_suffix(".segments.json")]
    if video_rel:
        try:
            video_abs = resolve_data_relative_path(video_rel)
            candidates.append(video_abs.with_suffix(".segments.json"))
        except Exception:  # noqa: BLE001 — подсказка кандидата, не контракт
            pass
    for c in candidates:
        if c.is_file():
            return c
    return None


def _existing_payload(sidecar_path: Path) -> dict | None:
    if not sidecar_path.is_file():
        return None
    try:
        return json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _preserved_videos(existing: dict | None, video_entry: dict) -> list[dict]:
    """Существующие видео (в т.ч. URL) + текущее видео первым, без дублей."""
    videos: list[dict] = [video_entry]
    for raw in ((existing or {}).get("media") or {}).get("videos") or []:
        same_local = raw.get("kind") == "local" and raw.get("path") == video_entry.get("path")
        if not same_local:
            videos.append(raw)
    return videos


def _preserved_images(existing: dict | None) -> tuple[dict[str, list[dict]], dict[tuple[str, int], list[dict]]]:
    """Картинки старого sidecar: сначала по стабильному section_id, затем fallback."""
    by_id: dict[str, list[dict]] = {}
    by_pos: dict[tuple[str, int], list[dict]] = {}
    for raw in (existing or {}).get("sections") or []:
        images = raw.get("images") or []
        if not images:
            continue
        if raw.get("section_id"):
            by_id[str(raw["section_id"]).lower()] = images
        by_pos[(str(raw.get("section_slug")), int(raw.get("line_start") or 0))] = images
    return by_id, by_pos


def build_payload(
    *,
    konspekt_abs: Path,
    video_rel: str,
    segments_path: Path,
    existing: dict | None,
) -> dict:
    segments_file = load_segments_file(segments_path)
    sections = parse_sections(konspekt_abs)
    aligned = align_sections(sections, segments_file.segments)

    video_abs = resolve_data_relative_path(video_rel)
    video_sha = sha256_file(video_abs)
    if segments_file.media_sha256 and segments_file.media_sha256.lower() != video_sha.lower():
        raise SystemExit(
            f"Сегменты {segments_path.name} получены НЕ из этого видео:\n"
            f"  segments.media_sha256 = {segments_file.media_sha256}\n"
            f"  sha256({video_rel})   = {video_sha}\n"
            "Транскрибируйте именно этот файл (например, playable .mp4 после ремукса):\n"
            f'  python scripts/transcribe_media.py "{video_abs}"'
        )
    video_entry = {
        "kind": "local",
        "path": video_rel.replace("\\", "/"),
        "sha256": video_sha,
        "title": video_abs.stem.replace("_", " "),
    }
    images_by_id, images_by_pos = _preserved_images(existing)

    sections_payload = []
    for item in aligned:
        s = item.section
        section_id = compute_section_id(s)
        entry: dict = {
            "section_id": section_id,
            "section_slug": s.slug,
            "heading": s.heading_text,
            "line_start": s.line_start,
            "line_end": s.line_end,
            "confidence": item.confidence,
        }
        if item.t_start is not None:
            entry["t_start"] = item.t_start
        if item.t_end is not None:
            entry["t_end"] = item.t_end
        preserved = images_by_id.get(section_id) or images_by_pos.get((s.slug, s.line_start))
        if preserved:
            entry["images"] = preserved
        sections_payload.append(entry)

    return {
        "schema_version": 1,
        "konspekt_sha256": sha256_file(konspekt_abs),
        "media_sha256": video_entry["sha256"],
        "generated_by": {
            "tool": "scripts/build_media_sidecar.py",
            "asr_model": segments_file.asr_model,
            "alignment_version": ALIGNMENT_VERSION,
            "created_at": _utc_now(),
        },
        "media": {"video": video_entry, "videos": _preserved_videos(existing, video_entry)},
        "sections": sections_payload,
    }


def _print_coverage(payload: dict) -> None:
    sections = payload["sections"]
    with_ts = [s for s in sections if "t_start" in s]
    anchored = [s for s in with_ts if s["confidence"] >= 0.70]
    print(f"Разделов: {len(sections)}; с таймкодом: {len(with_ts)} "
          f"(якорных: {len(anchored)}, интерполировано: {len(with_ts) - len(anchored)})")
    for s in sections[:12]:
        ts = s.get("t_start")
        mark = f"{int(ts // 60):3d}:{int(ts % 60):02d}" if ts is not None else "  — "
        print(f"  [{mark}] conf={s['confidence']:.2f}  {s['heading'][:70]}")
    if len(sections) > 12:
        print(f"  … ещё {len(sections) - 12} разделов")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("konspekt", help="Конспект: data-relative путь (или абсолютный внутри DATA_DIR)")
    parser.add_argument("--video", help="Data-relative путь к видео (default: из существующего sidecar)")
    parser.add_argument("--segments", help="Путь к .segments.json (default: рядом с конспектом/видео)")
    parser.add_argument("--dry-run", action="store_true", help="Показать покрытие, файл не писать")
    args = parser.parse_args(argv)

    konspekt_abs, _ = _resolve_konspekt(args.konspekt)
    if not konspekt_abs.is_file():
        print(f"Конспект не найден: {konspekt_abs}", file=sys.stderr)
        return 2

    sidecar_path = konspekt_abs.with_suffix(".media.json")
    existing = _existing_payload(sidecar_path)

    video_rel = args.video
    if not video_rel and existing is not None:
        video_raw = ((existing.get("media") or {}).get("video")) or {}
        if video_raw.get("kind") == "local":
            video_rel = video_raw.get("path")
    if not video_rel:
        print("Не задан --video, и в существующем sidecar нет локального видео.", file=sys.stderr)
        return 2

    segments_path = Path(args.segments) if args.segments else _guess_segments_path(konspekt_abs, video_rel)
    if segments_path is None or not segments_path.is_file():
        print(
            "Не найден .segments.json. Сначала транскрибируйте видео:\n"
            f'  python scripts/transcribe_media.py "<путь к видео>"',
            file=sys.stderr,
        )
        return 2

    payload = build_payload(
        konspekt_abs=konspekt_abs, video_rel=video_rel, segments_path=segments_path, existing=existing
    )
    parse_media_sidecar(payload)  # контрактная валидация до записи

    _print_coverage(payload)
    if args.dry_run:
        print("(dry-run: файл не записан)")
        return 0
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"Записано: {sidecar_path}")
    if existing is None:
        print(f"Не забудьте frontmatter-указатель в конспекте: media_sidecar: <data-relative путь к {sidecar_path.name}>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
