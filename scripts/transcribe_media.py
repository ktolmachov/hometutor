"""Транскрибация видео/аудио лекции → <stem>.segments.json + <stem>.txt (offline).

ASR: faster-whisper (extra ``asr``: ``pip install -e .[asr]``). Аудио декодируется
из медиафайла напрямую (PyAV внутри faster-whisper) — системный ffmpeg для
транскрибации НЕ нужен; он нужен только для ``--remux`` (браузерный .mp4 из .ts).

Идемпотентность: если рядом уже лежит ``.segments.json`` с тем же sha256 медиа
и той же моделью — повторная транскрибация не выполняется (``--force`` обходит).

Примеры:
    python scripts/transcribe_media.py "D:/AI/app/data/ИИ Агенты/урок_2_как_агент_думает_и_действует.ts"
    python scripts/transcribe_media.py lecture.ts --model large-v3-turbo --remux
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.media_alignment import SEGMENTS_SCHEMA_VERSION  # noqa: E402
from app.media_sidecar import sha256_file  # noqa: E402

MEDIA_SUFFIXES = {".ts", ".mp4", ".mkv", ".webm", ".mov", ".mp3", ".wav", ".m4a", ".ogg"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_existing(segments_path: Path) -> dict | None:
    if not segments_path.exists():
        return None
    try:
        return json.loads(segments_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _data_dir() -> Path:
    from app.path_safety import resolve_data_relative_path

    return resolve_data_relative_path(".").resolve()


def _import_media_to_data(media: Path, target_rel_dir: str) -> Path:
    """Копировать внешний медиафайл в DATA_DIR/<target_rel_dir>/ (ADR 0002)."""
    from app.path_safety import resolve_data_relative_path, validate_data_relative_path

    rel_dir = validate_data_relative_path(target_rel_dir)
    target_dir = resolve_data_relative_path(rel_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / media.name
    if target.resolve() == media.resolve():
        return media
    if target.exists() and sha256_file(target) == sha256_file(media):
        print(f"Импорт: {target} уже существует с тем же содержимым — копирование пропущено.")
        return target
    print(f"Импорт в DATA_DIR: {media} → {target} ({media.stat().st_size / 1e6:.0f} МБ)…")
    shutil.copy2(media, target)
    return target


def _asr_params_fingerprint(model: str, language: str, beam_size: int) -> dict:
    """Все параметры, влияющие на результат ASR — участвуют в идемпотентности."""
    return {
        "schema_version": SEGMENTS_SCHEMA_VERSION,
        "model": model,
        "language_requested": language,
        "beam_size": beam_size,
        "vad_filter": True,
    }


def _import_whisper():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "faster-whisper не установлен. Установите ASR-extra:\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install -e .[asr]",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    return WhisperModel


def transcribe(media: Path, *, model_name: str, language: str, device: str, beam_size: int) -> dict:
    WhisperModel = _import_whisper()
    print(f"[1/3] Загрузка модели {model_name} (device={device})…")
    model = WhisperModel(model_name, device=device, compute_type="auto")
    print(f"[2/3] Транскрибация {media.name} (VAD включён)…")
    started = time.monotonic()
    segments_iter, info = model.transcribe(
        str(media),
        language=None if language == "auto" else language,
        vad_filter=True,
        beam_size=beam_size,
    )
    segments = []
    for seg in segments_iter:
        segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
        done = seg.end
        if len(segments) % 100 == 0:
            print(f"    …{done / 60:.1f} мин аудио обработано ({len(segments)} сегментов)")
    elapsed = time.monotonic() - started
    print(f"[3/3] Готово: {len(segments)} сегментов, язык={info.language}, {elapsed / 60:.1f} мин работы.")
    return {
        "asr": {
            "tool": "faster-whisper",
            "model": model_name,
            "language": info.language,
            "created_at": _utc_now(),
            "params": _asr_params_fingerprint(model_name, language, beam_size),
        },
        "segments": segments,
    }


def remux_to_mp4(media: Path) -> Path | None:
    """Ремукс контейнера в браузерный .mp4 без перекодирования (нужен ffmpeg)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print(
            "--remux пропущен: ffmpeg не найден в PATH. Установка: winget install Gyan.FFmpeg",
            file=sys.stderr,
        )
        return None
    target = media.with_suffix(".mp4")
    if target.exists():
        print(f"--remux пропущен: {target.name} уже существует.")
        return target
    print(f"Ремукс {media.name} → {target.name} (без перекодирования)…")
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(media),
         "-c", "copy", "-movflags", "+faststart", str(target)],
        check=False,
    )
    if result.returncode != 0:
        print("Ремукс copy-режимом не удался (кодек вне mp4-профиля); попробуйте перекодировать:\n"
              f'  ffmpeg -i "{media}" -c:v libx264 -crf 20 -c:a aac "{target}"', file=sys.stderr)
        return None
    return target


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("media", help="Путь к видео/аудио файлу лекции")
    parser.add_argument("--model", default="large-v3", help="Модель faster-whisper (default: large-v3)")
    parser.add_argument("--language", default="auto", help="Код языка или auto (default: auto)")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--beam-size", type=int, default=5, help="beam_size faster-whisper (default: 5)")
    parser.add_argument(
        "--import-to-data",
        metavar="REL_DIR",
        help="Скопировать внешний файл в DATA_DIR/<REL_DIR>/ и работать с копией (ADR 0002)",
    )
    parser.add_argument("--remux", action="store_true", help="Также сделать браузерный .mp4 (нужен ffmpeg)")
    parser.add_argument("--force", action="store_true", help="Игнорировать существующий .segments.json")
    args = parser.parse_args(argv)

    media = Path(args.media).resolve()
    if not media.is_file():
        print(f"Файл не найден: {media}", file=sys.stderr)
        return 2
    if media.suffix.lower() not in MEDIA_SUFFIXES:
        print(f"Неподдерживаемое расширение {media.suffix}; ожидается одно из {sorted(MEDIA_SUFFIXES)}",
              file=sys.stderr)
        return 2

    if args.import_to_data:
        media = _import_media_to_data(media, args.import_to_data)
    else:
        try:
            media.relative_to(_data_dir())
        except ValueError:
            print(
                f"ВНИМАНИЕ: {media} лежит вне DATA_DIR ({_data_dir()}). Артефакты рядом с ним\n"
                "не смогут использоваться sidecar-контрактом (data-relative paths). Используйте\n"
                "--import-to-data <относительная-папка>, чтобы импортировать файл в DATA_DIR.",
                file=sys.stderr,
            )

    segments_path = media.with_suffix(".segments.json")
    txt_path = media.with_suffix(".txt")

    print(f"Хэширование {media.name} ({media.stat().st_size / 1e6:.0f} МБ)…")
    media_sha = sha256_file(media)

    fingerprint = _asr_params_fingerprint(args.model, args.language, args.beam_size)
    existing = _load_existing(segments_path)
    if (
        not args.force
        and existing is not None
        and existing.get("media_sha256") == media_sha
        and ((existing.get("asr") or {}).get("params") or {}) == fingerprint
    ):
        print(f"Актуальный {segments_path.name} уже существует ({len(existing.get('segments') or [])} "
              "сегментов, те же ASR-параметры) — пропускаю. --force для повторной транскрибации.")
        if args.remux:
            remux_to_mp4(media)
        return 0

    result = transcribe(
        media, model_name=args.model, language=args.language, device=args.device, beam_size=args.beam_size
    )
    payload = {
        "schema_version": SEGMENTS_SCHEMA_VERSION,
        "media_sha256": media_sha,
        "source_file": media.name,
        **result,
    }
    segments_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    txt_path.write_text(
        "\n".join(s["text"] for s in result["segments"]) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Записано: {segments_path.name}, {txt_path.name}")

    if args.remux:
        remux_to_mp4(media)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
