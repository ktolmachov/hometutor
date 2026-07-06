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


def transcribe(media: Path, *, model_name: str, language: str | None, device: str) -> dict:
    WhisperModel = _import_whisper()
    print(f"[1/3] Загрузка модели {model_name} (device={device})…")
    model = WhisperModel(model_name, device=device, compute_type="auto")
    print(f"[2/3] Транскрибация {media.name} (VAD включён)…")
    started = time.monotonic()
    segments_iter, info = model.transcribe(
        str(media),
        language=None if language in (None, "auto") else language,
        vad_filter=True,
        beam_size=5,
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

    segments_path = media.with_suffix(".segments.json")
    txt_path = media.with_suffix(".txt")

    print(f"Хэширование {media.name} ({media.stat().st_size / 1e6:.0f} МБ)…")
    media_sha = sha256_file(media)

    existing = _load_existing(segments_path)
    if (
        not args.force
        and existing is not None
        and existing.get("media_sha256") == media_sha
        and (existing.get("asr") or {}).get("model") == args.model
    ):
        print(f"Актуальный {segments_path.name} уже существует ({len(existing.get('segments') or [])} "
              "сегментов) — пропускаю. Используйте --force для повторной транскрибации.")
        if args.remux:
            remux_to_mp4(media)
        return 0

    result = transcribe(media, model_name=args.model, language=args.language, device=args.device)
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
