"""
Опциональный голосовой режим (микрофон + TTS). Зависимости: ``SpeechRecognition``, ``pyttsx3``.

На сервере/в Docker микрофон часто недоступен — вызовы возвращают понятную ошибку.
Streamlit: предпочтительно ``st.audio_input`` + ``transcribe_audio_bytes`` (без PyAudio).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def voice_dependencies_available() -> dict[str, bool]:
    out = {"speech_recognition": False, "pyttsx3": False, "pyaudio": False}
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
    return out


class VoiceService:
    """Тонкая обёртка: распознавание и озвучивание (локально)."""

    def __init__(self) -> None:
        self._sr = None
        self._engine = None
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

    def listen_microphone_once(self, *, timeout: float = 5.0, phrase_time_limit: float = 12.0) -> str:
        """Запись с default-микрофона (нужны PyAudio + speech_recognition)."""
        if not self._sr or not self.recognizer:
            return "Голосовой ввод недоступен: установите speech_recognition (и PyAudio для микрофона)."
        try:
            with self._sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            text = self.recognizer.recognize_google(audio, language="ru-RU")
            return (text or "").strip() or "Пустой результат распознавания"
        except Exception as e:
            en = type(e).__name__
            if en == "WaitTimeoutError":
                return "Не расслышал — повторите вопрос."
            if en == "UnknownValueError":
                return "Не удалось распознать речь."
            logger.warning("listen_microphone_once failed | error=%s", e)
            return f"Ошибка микрофона: {e}"

    def transcribe_audio_bytes(self, audio_bytes: bytes, *, format_hint: str = "wav") -> str:
        """
        Распознавание из байтов (WAV через ``AudioFile``). WebM/OGG из браузера могут не читаться
        без ffmpeg/pydub — тогда используйте микрофонный метод или конвертацию в WAV.
        """
        if not self._sr or not self.recognizer:
            return "speech_recognition не установлен."
        if not audio_bytes:
            return "Пустой аудиофайл."
        import io

        _ = format_hint
        try:
            audio_src = self._sr.AudioFile(io.BytesIO(audio_bytes))
            with audio_src as source:
                rec = self.recognizer.record(source, duration=30)
            return (self.recognizer.recognize_google(rec, language="ru-RU") or "").strip()
        except Exception as e:
            if type(e).__name__ == "UnknownValueError":
                return "Не удалось распознать речь в записи."
            logger.debug("transcribe_audio_bytes: %s", e)
            return (
                f"Не удалось прочитать аудио ({e}). "
                "Нужен WAV или конвертация (pydub/ffmpeg) для формата из браузера."
            )

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
