"""Прикрепить видео к конспекту как «видео урока целиком» — без потаймкодовых меток.

Зачем отдельный инструмент. ``scripts/build_media_sidecar.py`` требует ASR-транскрипт
(``.segments.json``) и выравнивает разделы конспекта по речи лекции. Это верно для
записанной лекции, из которой выведен конспект. Но короткий обзорный ролик (промо,
скринкаст без озвучки, тизер) не является записью лекции: его нечего выравнивать по
разделам, а ASR по немому видео даёт пустой транскрипт. Для такого случая честный вид
мультимедиа — прикрепить видео к конспекту ЦЕЛИКОМ (панель «🎞 Все видео урока» в Живом
конспекте, ``app.ui.living_konspekt_media._render_all_lesson_videos_panel``), без
фейковых потаймкодовых меток.

Пишет минимальный ``<konspekt>.media.json`` (schema_version=1, ``sections: []``) с локальным
видео в ``media.videos`` и добавляет указатель ``media_sidecar:`` во frontmatter конспекта
(тем же безопасным помощником, что и build_media_sidecar). Конспект и видео должны лежать
в DATA_DIR (контракт sidecar — data-relative пути; читатель отклоняет видео вне DATA_DIR).

Существующий sidecar не затирается вслепую: без ``--force`` инструмент откажется
перезаписывать sidecar, у которого есть разделы с таймкодами (это, вероятно, настоящий
ASR-sidecar — его портить нельзя). Локальные видео в ``media.videos`` дополняются без дублей.

Примеры:
    python scripts/attach_whole_lesson_video.py \
        "uploads/hometutor_101/konspekts/urok_1_pervyi_otvet.konspekt.md" \
        --video "uploads/hometutor_101/videos/video_1_pervyi_otvet.mp4"

    python scripts/attach_whole_lesson_video.py "<konspekt>.md" \
        --video "<video>.mp4" --title "Урок 1 · Первый ответ" --force
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Переиспользуем тот же безопасный писатель указателя, что и полный пайплайн:
# он ищет/пишет media_sidecar: строго во frontmatter-scope (не в теле), сохраняет CRLF/LF.
from scripts.build_media_sidecar import _ensure_frontmatter_pointer  # noqa: E402
from app.media_sidecar import (  # noqa: E402
    parse_media_sidecar,
    sha256_file,
    sha256_konspekt_file,
)
from app.path_safety import (  # noqa: E402
    data_relative_from_path,
    resolve_data_relative_path,
    validate_data_relative_path,
)

_TOOL = "scripts/attach_whole_lesson_video.py"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_konspekt(raw: str) -> Path:
    data_root = resolve_data_relative_path(".").resolve()
    p = Path(raw)
    abs_path = p.resolve() if p.is_absolute() else resolve_data_relative_path(raw)
    try:
        abs_path.relative_to(data_root)
    except ValueError:
        raise SystemExit(
            f"Конспект {abs_path} вне DATA_DIR ({data_root}) — sidecar требует data-relative путей."
        ) from None
    if not abs_path.is_file():
        raise SystemExit(f"Конспект не найден: {abs_path}")
    return abs_path


def _existing(sidecar_path: Path) -> dict | None:
    if not sidecar_path.is_file():
        return None
    try:
        return json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _preserved_local_videos(existing: dict | None, video_entry: dict) -> list[dict]:
    """Текущее видео первым + прочие видео старого sidecar (URL и другие локальные), без дублей."""
    videos: list[dict] = [video_entry]
    for raw in ((existing or {}).get("media") or {}).get("videos") or []:
        same_local = raw.get("kind") == "local" and raw.get("path") == video_entry.get("path")
        if not same_local:
            videos.append(raw)
    return videos


def build_payload(*, konspekt_abs: Path, video_rel: str, existing: dict | None) -> dict:
    video_abs = resolve_data_relative_path(video_rel)
    if not video_abs.is_file():
        raise SystemExit(f"Видео не найдено: {video_abs}")
    video_entry = {
        "kind": "local",
        "path": validate_data_relative_path(video_rel),
        "sha256": sha256_file(video_abs),
        "title": video_abs.stem.replace("_", " "),
    }
    return {
        "schema_version": 1,
        "konspekt_sha256": sha256_konspekt_file(konspekt_abs),
        "media_sha256": video_entry["sha256"],
        # Намеренно БЕЗ alignment_version: выравнивания не было (видео целиком, без
        # таймкодов), и sidecar_stale_reasons сверяет alignment_version только когда он
        # объявлен — иначе панель «🎞 Все видео урока» показала бы ложное «таймкоды
        # устарели» на sidecar, у которого таймкодов нет вовсе.
        "generated_by": {
            "tool": _TOOL,
            "created_at": _utc_now(),
        },
        "media": {"video": video_entry, "videos": _preserved_local_videos(existing, video_entry)},
        "sections": [],
        "semantic_blocks": [],
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("konspekt", help="Конспект: data-relative путь (или абсолютный внутри DATA_DIR)")
    parser.add_argument("--video", required=True, help="Data-relative путь к видео внутри DATA_DIR")
    parser.add_argument("--title", help="Название видео (по умолчанию из имени файла)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать даже sidecar с потаймкодовыми разделами (обычно — настоящий ASR-sidecar)",
    )
    parser.add_argument("--no-frontmatter", action="store_true", help="Не писать указатель media_sidecar:")
    parser.add_argument("--dry-run", action="store_true", help="Показать результат, файлы не писать")
    args = parser.parse_args(argv)

    konspekt_abs = _resolve_konspekt(args.konspekt)
    sidecar_path = konspekt_abs.with_suffix(".media.json")
    existing = _existing(sidecar_path)

    if existing and not args.force:
        has_timecoded = any("t_start" in (s or {}) for s in existing.get("sections") or [])
        if has_timecoded:
            print(
                f"ОТКАЗ: {sidecar_path.name} уже содержит разделы с таймкодами "
                "(похоже на ASR-sidecar). Перезапись затрёт их. Повторите с --force, если это осознанно.",
                file=sys.stderr,
            )
            return 2

    video_rel = args.video.replace("\\", "/")
    payload = build_payload(konspekt_abs=konspekt_abs, video_rel=video_rel, existing=existing)
    if args.title:
        payload["media"]["video"]["title"] = args.title
        payload["media"]["videos"][0]["title"] = args.title
    parse_media_sidecar(payload)  # контрактная валидация до записи

    video_title = payload["media"]["video"]["title"]
    print(f"Конспект: {data_relative_from_path(konspekt_abs)}")
    print(f"Видео (целиком, без таймкодов): {video_rel} · «{video_title}»")
    print(f"Всего видео в sidecar: {len(payload['media']['videos'])}")

    if args.dry_run:
        print("(dry-run: файлы не записаны)")
        return 0

    sidecar_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"Записано: {sidecar_path}")

    if args.no_frontmatter:
        print(f"Указатель для frontmatter (добавьте вручную): media_sidecar: "
              f"{data_relative_from_path(sidecar_path)}")
    else:
        _, msg = _ensure_frontmatter_pointer(konspekt_abs, sidecar_path)
        print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
