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
    AlignedSection,
    align_sections,
    compute_section_id,
    load_segments_file,
)
# _FRONTMATTER_RE/_MEDIA_SIDECAR_RE — тот же контракт, что у читателя приложения
# (app.media_sidecar.read_media_sidecar_pointer). Писатель обязан работать в том же
# frontmatter-scope: иначе «wired» не гарантирует, что приложение найдёт указатель
# (строка media_sidecar: в теле конспекта читателем игнорируется).
from app.media_sidecar import (  # noqa: E402
    _FRONTMATTER_RE,
    _MEDIA_SIDECAR_RE,
    parse_media_sidecar,
    sha256_file,
    sha256_konspekt_file,
)
from app.path_safety import data_relative_from_path, resolve_data_relative_path  # noqa: E402
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
) -> tuple[dict, list[AlignedSection], float | None]:
    segments_file = load_segments_file(segments_path)
    sections = parse_sections(konspekt_abs)
    aligned = align_sections(sections, segments_file.segments)
    media_duration = segments_file.segments[-1].end if segments_file.segments else None

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

    return (
        {
            "schema_version": 1,
            "konspekt_sha256": sha256_konspekt_file(konspekt_abs),
            "media_sha256": video_entry["sha256"],
            "generated_by": {
                "tool": "scripts/build_media_sidecar.py",
                "asr_model": segments_file.asr_model,
                "alignment_version": ALIGNMENT_VERSION,
                "created_at": _utc_now(),
                # fingerprint ASR-параметров → stale detection (см. GeneratedBy.asr_params)
                **({"asr_params": segments_file.asr_params} if segments_file.asr_params else {}),
            },
            "media": {"video": video_entry, "videos": _preserved_videos(existing, video_entry)},
            "sections": sections_payload,
        },
        aligned,
        media_duration,
    )


def _fmt_ts(seconds: float | None) -> str:
    """Человеко-читаемое время H:MM:SS / M:SS; None → «—».

    Прежний формат «{мин}:{сек:02d}» ломался после часа (5400 c → «90:00»),
    маскируя двухчасовые лекции.
    """
    if seconds is None:
        return "—"
    total = int(round(seconds))
    h, total = divmod(total, 3600)
    m, s = divmod(total, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _coverage_metrics(
    payload: dict, aligned: list[AlignedSection], media_duration: float | None
) -> dict:
    """Продуктовые метрики покрытия для отчёта и batch-манифеста.

    Метки считаются по реальному флагу ``aligned.anchored``, а не по confidence:
    payload хранит только confidence, поэтому прежний отчёт не мог отличить
    настоящий якорь (выживший LIS) со score 0.18–0.40 от интерполяции — оба
    оказывались «ниже 0.70» и клались в одну корзину «интерполировано».
    """
    sections = payload["sections"]
    with_ts = [s for s in sections if "t_start" in s]
    confident = [s for s in with_ts if s["confidence"] >= 0.70]
    anchored_n = sum(1 for a in aligned if a.anchored)
    interpolated_n = sum(1 for a in aligned if (not a.anchored) and a.t_start is not None)
    no_ts_n = sum(1 for a in aligned if a.t_start is None)
    # «Мои 18 минут»: суммарная длительность confident-фрагментов (ставка W5.5/W6).
    playlist_seconds = 0.0
    for s in confident:
        t0, t1 = s.get("t_start"), s.get("t_end")
        if t0 is not None and t1 is not None and t1 > t0:
            playlist_seconds += t1 - t0
    return {
        "sections": len(sections),
        "with_timestamp": len(with_ts),
        "anchored": anchored_n,
        "interpolated": interpolated_n,
        "no_timestamp": no_ts_n,
        "confident": len(confident),
        "playlist_seconds": round(playlist_seconds, 2),
        "media_seconds": round(media_duration, 2) if media_duration is not None else None,
    }


def _print_coverage(
    payload: dict, aligned: list[AlignedSection], media_duration: float | None
) -> None:
    sections = payload["sections"]
    m = _coverage_metrics(payload, aligned, media_duration)
    print(
        f"Разделов: {m['sections']}; с таймкодом: {m['with_timestamp']} "
        f"(якорей: {m['anchored']}, интерполировано: {m['interpolated']}, без таймкода: {m['no_timestamp']})"
    )
    print(
        f"Confident (≥0.70, кликабельны в UI): {m['confident']}/{m['sections']} · "
        f"плейлист-готово: {_fmt_ts(m['playlist_seconds'])} из {_fmt_ts(m['media_seconds'])}"
    )
    for a, s in list(zip(aligned, sections))[:12]:
        ts = s.get("t_start")
        kind = "⚓" if a.anchored else ("≈" if a.t_start is not None else "·")
        print(f"  [{_fmt_ts(ts):>7}] conf={s['confidence']:.2f} {kind} {s['heading'][:70]}")
    if len(sections) > 12:
        print(f"  … ещё {len(sections) - 12} разделов")


def _write_coverage_json(path: Path, metrics: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _ensure_frontmatter_pointer(konspekt_abs: Path, sidecar_abs: Path) -> tuple[bool, str]:
    """Идемпотентная запись ``media_sidecar:`` в frontmatter конспекта.

    Без указателя sidecar невидим приложению: обнаружение идёт ТОЛЬКО через YAML-блок
    ``---`` в начале файла (``app.media_sidecar.read_media_sidecar_pointer``),
    co-location fallback'а нет. Поиск и запись идут строго в том же scope (через
    ``_FRONTMATTER_RE``/``_MEDIA_SIDECAR_RE`` приложения): строка ``media_sidecar:``
    в теле конспекта (пример/документация о фиче) НЕ считается указателем и не
    переписывается — иначе писатель отрапортует «wired», а читатель ничего не найдёт.
    Построчная обработка с определением разделителя сохраняет окончания строк
    остального файла (минимальный diff), CRLF и LF обрабатываются корректно.
    """
    sidecar_rel = data_relative_from_path(sidecar_abs)
    raw = konspekt_abs.read_bytes()
    nl = "\r\n" if b"\r\n" in raw[:8192] else "\n"
    text = raw.decode("utf-8")
    desired = f"media_sidecar: {sidecar_rel}"

    fm = _FRONTMATTER_RE.match(text)
    if not fm:
        # Frontmatter-блока нет — без него читатель указатель не найдёт; создаём поверх.
        konspekt_abs.write_bytes(f"---{nl}{desired}{nl}---{nl}{nl}{text}".encode("utf-8"))
        return True, f"Добавлен frontmatter: {desired}"

    body_start, body_end = fm.start("body"), fm.end("body")
    parts = [p.rstrip("\r") for p in text[body_start:body_end].split("\n")]
    idx = next((i for i, ln in enumerate(parts) if _MEDIA_SIDECAR_RE.search(ln)), None)
    if idx is not None:
        current = _MEDIA_SIDECAR_RE.search(parts[idx]).group("path").strip().strip("'\"")
        if current == sidecar_rel:
            return False, f"Frontmatter уже подключён: {desired}"
        parts[idx] = desired
        konspekt_abs.write_bytes((text[:body_start] + nl.join(parts) + text[body_end:]).encode("utf-8"))
        return True, f"Обновлён frontmatter (было «{current}»): {desired}"

    # Блок есть, указателя в нём нет — вставляем первой строкой тела блока.
    parts.insert(0, desired)
    konspekt_abs.write_bytes((text[:body_start] + nl.join(parts) + text[body_end:]).encode("utf-8"))
    return True, f"Добавлен frontmatter: {desired}"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("konspekt", help="Конспект: data-relative путь (или абсолютный внутри DATA_DIR)")
    parser.add_argument("--video", help="Data-relative путь к видео (default: из существующего sidecar)")
    parser.add_argument("--segments", help="Путь к .segments.json (default: рядом с конспектом/видео)")
    parser.add_argument("--dry-run", action="store_true", help="Показать покрытие, файл не писать")
    parser.add_argument(
        "--coverage-json",
        help="Абсолютный путь, куда записать метрики покрытия (для batch-манифеста)",
    )
    parser.add_argument(
        "--no-frontmatter",
        action="store_true",
        help="Не записывать указатель media_sidecar: в frontmatter конспекта",
    )
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

    payload, aligned, media_duration = build_payload(
        konspekt_abs=konspekt_abs, video_rel=video_rel, segments_path=segments_path, existing=existing
    )
    parse_media_sidecar(payload)  # контрактная валидация до записи

    frontmatter_msg: str | None = None
    if not args.dry_run and not args.no_frontmatter:
        rewired, frontmatter_msg = _ensure_frontmatter_pointer(konspekt_abs, sidecar_path)
        if rewired:
            payload, aligned, media_duration = build_payload(
                konspekt_abs=konspekt_abs,
                video_rel=video_rel,
                segments_path=segments_path,
                existing=existing,
            )
            parse_media_sidecar(payload)

    _print_coverage(payload, aligned, media_duration)
    if args.coverage_json:
        _write_coverage_json(Path(args.coverage_json), _coverage_metrics(payload, aligned, media_duration))

    if args.dry_run:
        print("(dry-run: файл не записан)")
        return 0
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"Записано: {sidecar_path}")
    if args.no_frontmatter:
        print(f"Указатель для frontmatter (добавьте вручную): media_sidecar: "
              f"{data_relative_from_path(sidecar_path)}")
    else:
        print(
            frontmatter_msg
            or f"Frontmatter уже подключён: media_sidecar: {data_relative_from_path(sidecar_path)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
