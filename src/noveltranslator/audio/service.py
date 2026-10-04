"""Generación local de audio por capítulo con metadatos de sincronización.

El audio se sintetiza secuencialmente por unidades seguras de texto, pero no
se conserva un WAV por unidad. Solo se publica un WAV y un manifest por
capítulo. Esto reduce drásticamente la cantidad de archivos y permite limitar
los hilos de CPU del motor ONNX.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from noveltranslator.storage.identifiers import slugify
from noveltranslator.storage.repository import NovelRepository


@dataclass(frozen=True)
class AudioGenerationSummary:
    novel_id: str
    chapters_processed: int
    chapters_skipped: int
    segments_generated: int
    segments_skipped: int
    output_paths: tuple[Path, ...]


@dataclass(frozen=True)
class _SpeechUnit:
    unit_id: str
    chunk_index: int
    paragraph_index: int
    unit_index: int
    text: str
    text_hash: str


@dataclass(frozen=True)
class _AudioData:
    params: wave._wave_params
    frames: bytes
    duration_seconds: float


class AudioGenerationService:
    """Genera un WAV por capítulo y un manifest sincronizable."""

    VERSION = 4

    def __init__(
        self,
        repository: NovelRepository,
        progress_callback: Callable[[str], None] | None = None,
        progress_detail_callback: Callable[[dict[str, Any]], None] | None = None,
        engine_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.progress_callback = progress_callback or (lambda message: print(message))
        self.progress_detail_callback = progress_detail_callback or (lambda event: None)
        self.engine_factory = engine_factory or self._create_engine

    @staticmethod
    def _configure_threads(threads: int) -> None:
        if threads < 1:
            raise ValueError("threads debe ser como mínimo 1")
        for name in (
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "ORT_INTRA_OP_NUM_THREADS",
            "ORT_INTER_OP_NUM_THREADS",
        ):
            os.environ[name] = str(threads)

    @staticmethod
    def _create_engine(voice: str) -> Any:
        try:
            from supertonic import TTS
        except ImportError as exc:
            raise RuntimeError(
                "El soporte de audio no está instalado. Ejecuta: "
                "python -m pip install -e \".[audio]\""
            ) from exc
        engine = TTS(model="supertonic-3", auto_download=True)
        return engine, engine.get_voice_style(voice_name=voice)

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        """Obtiene líneas narrativas sin conservar saltos vacíos."""
        return [part.strip() for part in re.split(r"\r?\n+", text.strip()) if part.strip()]

    @staticmethod
    def _normalize_boundary(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        return re.sub(r"[^\wáéíóúüñ]+", " ", normalized, flags=re.UNICODE).strip()

    @staticmethod
    def _ends_sentence(text: str) -> bool:
        return text.rstrip().endswith((".", "!", "?", "…", ":", ";", ")", "]", "}", "»", "”", '"'))

    @classmethod
    def _remove_boundary_overlap(cls, lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
        """Quita duplicaciones producidas por el solapamiento entre chunks."""
        result: list[tuple[int, str]] = []
        for chunk_index, line in lines:
            if not result:
                result.append((chunk_index, line))
                continue
            previous = result[-1][1]
            if cls._normalize_boundary(previous) == cls._normalize_boundary(line):
                continue
            previous_match = re.search(r"([\wáéíóúüñ]+)[\s.!?,;:…]*$", previous, flags=re.IGNORECASE)
            current_match = re.match(r"^[\s¡¿—–\-\"«»“”']*([\wáéíóúüñ]+)(.*)$", line, flags=re.IGNORECASE)
            if previous_match and current_match:
                last_word = cls._normalize_boundary(previous_match.group(1))
                first_word = cls._normalize_boundary(current_match.group(1))
                previous_ends_sentence = AudioGenerationService._ends_sentence(previous)
                if last_word == first_word and len(last_word) >= 5 and not previous_ends_sentence:
                    remainder = current_match.group(2).lstrip(" ,;:—–-\"")
                    if remainder:
                        line = remainder[0].lower() + remainder[1:]
                    else:
                        continue
            result.append((chunk_index, line))
        return result

    @classmethod
    def _join_continuations(cls, lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
        """Une líneas que continúan una oración y no terminan en puntuación."""
        result: list[tuple[int, str]] = []
        for chunk_index, line in lines:
            if result and not cls._is_short_expression(result[-1][1]):
                previous_chunk, previous = result[-1]
                if not cls._ends_sentence(previous):
                    result[-1] = (previous_chunk, f"{previous} {line}")
                    continue
            result.append((chunk_index, line))
        return result

    @classmethod
    def _is_short_expression(cls, text: str) -> bool:
        if len(text) > 100:
            return False
        words = re.findall(r"[\wáéíóúüñ]+(?:-[\wáéíóúüñ]+)*", text.casefold(), flags=re.IGNORECASE)
        if not words or len(words) > 8:
            return False
        markers = {
            "ah", "eh", "hm", "hmm", "hm-hm", "oh", "uf", "uy", "ugh", "snif", "huff",
            "pum", "ploc", "toc", "crac", "crash", "zas", "bang", "splash", "squeak",
            "grr", "grrr", "ja", "je", "jajaja",
        }
        if any(word.strip("-…") in markers for word in words):
            return True
        return any("-" in word or re.search(r"(.)\1{2,}", word) for word in words)

    @staticmethod
    def _split_long_text(text: str, max_characters: int) -> list[str]:
        """Divide texto largo sin cortar palabras ni oraciones a la mitad."""
        if len(text) <= max_characters:
            return [text]
        sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", text) if part.strip()]
        units: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > max_characters:
                words = sentence.split()
                if current:
                    units.append(current)
                    current = ""
                word_chunk = ""
                for word in words:
                    candidate = f"{word_chunk} {word}".strip()
                    if word_chunk and len(candidate) > max_characters:
                        units.append(word_chunk)
                        word_chunk = word
                    else:
                        word_chunk = candidate
                if word_chunk:
                    units.append(word_chunk)
                continue
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > max_characters:
                units.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            units.append(current)
        return units or [text]

    @classmethod
    def _chapter_speech_units(
        cls,
        chunk_texts: list[tuple[int, str]],
        max_characters: int,
    ) -> list[_SpeechUnit]:
        lines: list[tuple[int, str]] = []
        for chunk_index, text in chunk_texts:
            lines.extend((chunk_index, line) for line in cls._split_lines(text))
        lines = cls._join_continuations(cls._remove_boundary_overlap(lines))

        grouped: list[tuple[int, str]] = []
        pending_expressions: list[tuple[int, str]] = []
        for chunk_index, line in lines:
            if cls._is_short_expression(line):
                pending_expressions.append((chunk_index, line))
                continue
            if pending_expressions:
                line = " ".join([item[1] for item in pending_expressions] + [line])
                chunk_index = pending_expressions[0][0]
                pending_expressions = []
            grouped.append((chunk_index, line))
        if pending_expressions:
            if grouped:
                previous_chunk, previous_line = grouped[-1]
                grouped[-1] = (previous_chunk, " ".join([previous_line] + [item[1] for item in pending_expressions]))
            else:
                grouped.extend(pending_expressions)

        units: list[_SpeechUnit] = []
        for paragraph_index, (chunk_index, line) in enumerate(grouped, start=1):
            for unit_index, unit_text in enumerate(cls._split_long_text(line, max_characters), start=1):
                unit_id = f"unit_{len(units) + 1:04d}"
                units.append(
                    _SpeechUnit(
                        unit_id,
                        chunk_index,
                        paragraph_index,
                        unit_index,
                        unit_text,
                        cls._text_hash(unit_text),
                    )
                )
        return units

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _tts_text(text: str) -> str:
        """Da al motor un cierre de frase si la unidad quedó sin puntuación."""
        stripped = text.rstrip()
        if not stripped:
            return stripped
        if stripped[-1] in ".!?…:;»”)]}*-":
            return stripped
        return f"{stripped}."

    @staticmethod
    def _read_audio(path: Path) -> _AudioData:
        with wave.open(str(path), "rb") as wav_file:
            params = wav_file.getparams()
            frames = wav_file.readframes(wav_file.getnframes())
        if params.framerate <= 0:
            raise ValueError(f"Frecuencia inválida en el audio: {path}")
        duration = len(frames) / (params.framerate * params.nchannels * params.sampwidth)
        return _AudioData(params, frames, duration)

    @staticmethod
    def _silence(params: wave._wave_params, seconds: float) -> bytes:
        frames = max(0, int(round(params.framerate * seconds)))
        return b"\x00" * frames * params.nchannels * params.sampwidth

    @staticmethod
    def _write_wav(path: Path, params: wave._wave_params, frames: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with wave.open(str(temporary), "wb") as wav_file:
            wav_file.setparams(params)
            wav_file.writeframes(frames)
        temporary.replace(path)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _chapter_audio_dir(repository: NovelRepository, novel_id: str, chapter: int, audio_id: str) -> Path:
        return repository.root / novel_id / "chapters" / f"{chapter:03d}" / "audio" / audio_id

    @staticmethod
    def _load_existing_manifest(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @classmethod
    def _is_reusable(
        cls,
        manifest: dict[str, Any],
        chapter_audio_path: Path,
        units: list[_SpeechUnit],
        *,
        novel_id: str,
        chapter: int,
        translation_id: str,
        voice: str,
        speed: float,
        steps: int,
        pause_seconds: float,
        tail_silence_seconds: float,
        max_characters: int,
    ) -> bool:
        return (
            chapter_audio_path.is_file()
            and manifest.get("version") == cls.VERSION
            and manifest.get("novel_id") == novel_id
            and manifest.get("chapter_number") == chapter
            and manifest.get("translation_id") == translation_id
            and manifest.get("voice") == voice
            and float(manifest.get("speed", -1)) == speed
            and int(manifest.get("steps", -1)) == steps
            and float(manifest.get("pause_seconds", -1)) == pause_seconds
            and float(manifest.get("tail_silence_seconds", -1)) == tail_silence_seconds
            and int(manifest.get("max_unit_characters", -1)) == max_characters
            and manifest.get("unit_hashes") == [unit.text_hash for unit in units]
        )

    def _synthesize_unit(
        self,
        engine: Any,
        style: Any,
        unit: _SpeechUnit,
        speed: float,
        steps: int,
        temporary_path: Path,
    ) -> _AudioData:
        started = time.perf_counter()
        temporary_path.parent.mkdir(parents=True, exist_ok=True)
        audio, _ = engine.synthesize(
            self._tts_text(unit.text),
            voice_style=style,
            lang="es",
            speed=speed,
            total_steps=steps,
        )
        engine.save_audio(audio, str(temporary_path))
        result = self._read_audio(temporary_path)
        temporary_path.unlink(missing_ok=True)
        self.progress_callback(
            f"{unit.unit_id} generado · {result.duration_seconds:.1f}s · "
            f"síntesis {time.perf_counter() - started:.1f}s"
        )
        return result

    def generate_novel(
        self,
        novel_id: str,
        translation_id: str = "hf-opus-v3",
        voice: str = "M5",
        speed: float = 1.40,
        steps: int = 8,
        from_chapter: int | None = None,
        to_chapter: int | None = None,
        overwrite: bool = False,
        pause_seconds: float = 0.25,
        tail_silence_seconds: float = 0.35,
        threads: int = 4,
        max_unit_characters: int = 900,
    ) -> AudioGenerationSummary:
        if not 0.5 <= speed <= 2.0:
            raise ValueError("speed debe estar entre 0.5 y 2.0")
        if not 1 <= steps <= 100:
            raise ValueError("steps debe estar entre 1 y 100")
        if pause_seconds < 0 or tail_silence_seconds < 0:
            raise ValueError("los silencios no pueden ser negativos")
        if max_unit_characters < 100:
            raise ValueError("max_unit_characters debe ser como mínimo 100")
        self._configure_threads(threads)
        chapters = [
            number
            for number in self.repository.list_chapters(novel_id)
            if (from_chapter is None or number >= from_chapter)
            and (to_chapter is None or number <= to_chapter)
        ]
        if not chapters:
            raise ValueError("No hay capítulos dentro del rango solicitado")

        engine, style = self.engine_factory(voice)
        audio_id = slugify(f"supertonic-{voice.lower()}-{translation_id}-speed-{speed:.2f}-steps-{steps}-chapter-v4", 96)
        chapters_processed = 0
        chapters_skipped = 0
        units_generated = 0
        units_skipped = 0
        output_paths: list[Path] = []

        chunks_by_chapter = {
            chapter: self.repository.list_translation_chunks(novel_id, chapter, translation_id)
            for chapter in chapters
        }

        for chapter_position, chapter in enumerate(chapters, start=1):
            chunk_indexes = chunks_by_chapter[chapter]
            if not chunk_indexes:
                raise ValueError(f"El capítulo {chapter:03d} no tiene traducciones {translation_id}")
            chunk_positions = {chunk_index: position for position, chunk_index in enumerate(chunk_indexes, start=1)}
            chunk_texts: list[tuple[int, str]] = []
            for chunk_index in chunk_indexes:
                chunk = self.repository.load_translation_chunk(novel_id, chapter, translation_id, chunk_index)
                chunk_texts.append((chunk_index, str(chunk.get("translated_text", ""))))
            all_units = self._chapter_speech_units(chunk_texts, max_unit_characters)

            self.progress_detail_callback(
                {
                    "event": "chapter_started",
                    "chapter": chapter,
                    "chapter_position": chapter_position,
                    "chapters_total": len(chapters),
                    "units_total": len(all_units),
                    "chunks_total": len(chunk_indexes),
                    "threads": threads,
                }
            )

            output_dir = self._chapter_audio_dir(self.repository, novel_id, chapter, audio_id)
            manifest_path = output_dir / "manifest.json"
            chapter_audio_path = output_dir / f"chapter_{chapter:03d}.wav"
            existing = self._load_existing_manifest(manifest_path)
            if not overwrite and self._is_reusable(
                existing,
                chapter_audio_path,
                all_units,
                novel_id=novel_id,
                chapter=chapter,
                translation_id=translation_id,
                voice=voice,
                speed=speed,
                steps=steps,
                pause_seconds=pause_seconds,
                tail_silence_seconds=tail_silence_seconds,
                max_characters=max_unit_characters,
            ):
                chapters_skipped += 1
                units_skipped += len(all_units)
                output_paths.append(output_dir)
                self.progress_callback(f"Audio capítulo {chapter:03d}: omitido · ya está completo")
                self.progress_detail_callback(
                    {
                        "event": "chapter_skipped",
                        "chapter": chapter,
                        "chapter_position": chapter_position,
                        "chapters_total": len(chapters),
                        "units_total": len(all_units),
                        "chunks_total": len(chunk_indexes),
                    }
                )
                continue

            self.progress_callback(
                f"Audio capítulo {chapter:03d}: {len(all_units)} unidades · "
                f"{threads} hilos máximos · salida única"
            )
            audio_parts: list[bytes] = []
            entries: list[dict[str, Any]] = []
            params: wave._wave_params | None = None
            elapsed = 0.0
            temporary_path = output_dir / ".unit.tmp.wav"
            for position, unit in enumerate(all_units, start=1):
                audio_data = self._synthesize_unit(engine, style, unit, speed, steps, temporary_path)
                params = params or audio_data.params
                if (
                    audio_data.params.nchannels,
                    audio_data.params.sampwidth,
                    audio_data.params.framerate,
                    audio_data.params.comptype,
                ) != (params.nchannels, params.sampwidth, params.framerate, params.comptype):
                    raise ValueError(f"Formato de audio incompatible en {unit.unit_id}")
                start = elapsed
                end = start + audio_data.duration_seconds
                entries.append(
                    {
                        "id": unit.unit_id,
                        "chunk_index": unit.chunk_index,
                        "paragraph_index": unit.paragraph_index,
                        "unit_index": unit.unit_index,
                        "text": unit.text,
                        "text_hash": unit.text_hash,
                        "start_seconds": round(start, 3),
                        "end_seconds": round(end, 3),
                        "duration_seconds": round(audio_data.duration_seconds, 3),
                    }
                )
                audio_parts.append(audio_data.frames)
                elapsed = end
                if position < len(all_units):
                    audio_parts.append(self._silence(params, pause_seconds))
                    elapsed += pause_seconds
                units_generated += 1
                self.progress_detail_callback(
                    {
                        "event": "unit_completed",
                        "chapter": chapter,
                        "chapter_position": chapter_position,
                        "chapters_total": len(chapters),
                        "unit_position": position,
                        "units_total": len(all_units),
                        "chunk_index": unit.chunk_index,
                        "chunk_position": chunk_positions[unit.chunk_index],
                        "chunks_total": len(chunk_indexes),
                        "unit_id": unit.unit_id,
                        "duration_seconds": audio_data.duration_seconds,
                    }
                )
            if params is None:
                raise ValueError(f"El capítulo {chapter:03d} no contiene texto traducido")
            audio_parts.append(self._silence(params, tail_silence_seconds))
            self._write_wav(chapter_audio_path, params, b"".join(audio_parts))
            temporary_path.unlink(missing_ok=True)
            manifest = {
                "version": self.VERSION,
                "novel_id": novel_id,
                "chapter_number": chapter,
                "translation_id": translation_id,
                "provider": "supertonic",
                "model": "supertonic-3",
                "voice": voice,
                "language": "es",
                "speed": speed,
                "steps": steps,
                "pause_seconds": pause_seconds,
                "tail_silence_seconds": tail_silence_seconds,
                "max_unit_characters": max_unit_characters,
                "sample_rate": params.framerate,
                "audio": chapter_audio_path.name,
                "duration_seconds": round(elapsed + tail_silence_seconds, 3),
                "unit_hashes": [unit.text_hash for unit in all_units],
                "segments": entries,
            }
            self._write_json(manifest_path, manifest)
            output_paths.append(output_dir)
            chapters_processed += 1
            self.progress_callback(
                f"Audio capítulo {chapter:03d}: OK · unidades {len(all_units)} · "
                f"duración {manifest['duration_seconds']:.1f}s · salida {chapter_audio_path}"
            )
            self.progress_detail_callback(
                {
                    "event": "chapter_completed",
                    "chapter": chapter,
                    "chapter_position": chapter_position,
                    "chapters_total": len(chapters),
                    "units_total": len(all_units),
                    "chunks_total": len(chunk_indexes),
                    "duration_seconds": manifest["duration_seconds"],
                }
            )

        return AudioGenerationSummary(
            novel_id,
            chapters_processed,
            chapters_skipped,
            units_generated,
            units_skipped,
            tuple(output_paths),
        )
