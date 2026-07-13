"""
Опциональный голосовой режим (микрофон + TTS). 

Для распознавания (ASR) предпочтителен локальный faster-whisper из extra ``[asr]`` (уже используется
для транскрибации лекций). Облачный ``recognize_google`` удалён (local-first).

Зависимости для ASR: ``faster-whisper`` (опционально). Для TTS и микрофона записи — voice extra.
На сервере/в Docker микрофон часто недоступен — вызовы возвращают понятную ошибку.
Streamlit: предпочтительно ``st.audio_input`` + ``transcribe_audio_bytes``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def voice_dependencies_available() -> dict[str, bool]:
    out = {
        "speech_recognition": False,
        "pyttsx3": False,
        "pyaudio": False,
        "faster_whisper": False,
    }
    try:
        import speech_recognition  # noqa: F401

        out["speech_recognition"] = True
    except ImportError:
        pass
    try:
        import pyttsx3  # noqa: F401

        out["pyttsx3"] = True
    except ImportError:
        pass
    try:
        import pyaudio  # noqa: F401

        out["pyaudio"] = True
    except ImportError:
        pass
    try:
        import faster_whisper  # noqa: F401

        out["faster_whisper"] = True
    except ImportError:
        pass
    return out


class VoiceService:
    """Тонкая обёртка: распознавание (локальный faster-whisper при наличии [asr]) и озвучивание (локально)."""

    def __init__(self) -> None:
        self._sr = None
        self._engine = None
        self._whisper = None
        # Для интерактивного голоса (sidebar) — tiny (быстрая, ~39M). Лекции используют large-v3 в transcribe_media.
        self._whisper_model = "tiny"
        try:
            import speech_recognition as sr

            self._sr = sr
            self.recognizer = sr.Recognizer()
        except ImportError:
            self.recognizer = None
        try:
            import pyttsx3

            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 150)
        except Exception as e:
            logger.debug("pyttsx3 init failed: %s", e)
            self._engine = None

    def _get_whisper_model(self):
        """Lazy load faster-whisper. Returns model or None (graceful)."""
        if self._whisper is not None:
            return self._whisper
        try:
            from faster_whisper import WhisperModel

            # cpu + int8 for low footprint on interactive voice. Heavy models for batch lecture ASR.
            self._whisper = WhisperModel(
                self._whisper_model, device="cpu", compute_type="int8"
            )
            return self._whisper
        except Exception as e:  # noqa: BLE001 - graceful degradation is the contract
            logger.debug("faster_whisper model load failed (install [asr] if desired): %s", e)
            self._whisper = None
            return None

    def listen_microphone_once(self, *, timeout: float = 5.0, phrase_time_limit: float = 12.0) -> str:
        """Запись с default-микрофона + локальное распознавание (faster-whisper если доступен).

        Требует PyAudio + speech_recognition для захвата + faster-whisper ([asr]) для ASR.
        Google Speech удалён (local-first).
        """
        if not self._sr or not self.recognizer:
            return "Голосовой ввод (микрофон) недоступен: нужен speech_recognition + PyAudio."
        try:
            with self._sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            # Получаем WAV-данные от sr и отдаём в локальный ASR (если есть).
            wav_bytes = audio.get_wav_data()
            return self._transcribe_wav_bytes(wav_bytes)
        except Exception as e:
            en = type(e).__name__
            if en == "WaitTimeoutError":
                return "Не расслышал — повторите вопрос."
            logger.warning("listen_microphone_once failed | error=%s", e)
            return f"Ошибка микрофона: {e}"

    def transcribe_audio_bytes(self, audio_bytes: bytes, *, format_hint: str = "wav") -> str:
        """
        Распознавание из байтов. Предпочтительно локальный faster-whisper ([asr]).
        Поддерживает WAV/OGG/WebM и др. (через запись во временный файл + ffmpeg при наличии).
        """
        if not audio_bytes:
            return "Пустой аудиофайл."
        # Предпочитаем локальный ASR. sr.AudioFile оставлен только как fallback для старых путей.
        asr_text = self._transcribe_with_whisper(audio_bytes, format_hint=format_hint)
        if asr_text is not None:
            return asr_text
        # Если whisper недоступен — честное сообщение (google удалён).
        return (
            "Локальный ASR (faster-whisper) недоступен. "
            "Установите 'pip install -e .[asr]' (или hometutor[asr]) для оффлайн-распознавания. "
            "Облачный Google удалён по local-first."
        )

    def _transcribe_with_whisper(self, audio_bytes: bytes, *, format_hint: str = "wav") -> str | None:
        """Return transcribed text using faster-whisper, or None if not available / failed."""
        model = self._get_whisper_model()
        if model is None:
            return None
        import os
        import tempfile

        suffix = f".{format_hint}" if format_hint else ".wav"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            segments, info = model.transcribe(
                tmp_path,
                language="ru",
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text for seg in segments).strip()
            return text or "Пустой результат распознавания"
        except Exception as e:  # noqa: BLE001 - must not break caller; honest degradation
            logger.debug("_transcribe_with_whisper failed: %s", e)
            return f"Ошибка локального ASR: {e}"
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _transcribe_wav_bytes(self, wav_bytes: bytes) -> str:
        """Internal: transcribe wav bytes (from mic) preferring whisper."""
        txt = self._transcribe_with_whisper(wav_bytes, format_hint="wav")
        if txt is not None:
            return txt
        return "Локальный ASR недоступен (нужен [asr])."

    def speak(self, text: str) -> None:
        """Синтез речи (локально, pyttsx3)."""
        if not self._engine:
            logger.warning("TTS недоступен (pyttsx3)")
            return
        t = (text or "").strip()
        if not t:
            return
        try:
            self._engine.say(t[:8000])
            self._engine.runAndWait()
        except Exception as e:
            logger.warning("speak failed | error=%s", e)


__all__ = ["VoiceService", "voice_dependencies_available"]
