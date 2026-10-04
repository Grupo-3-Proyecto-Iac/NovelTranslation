import json
import wave
from pathlib import Path

from noveltranslator.audio.service import AudioGenerationService
from noveltranslator.core.models import Chapter, Novel
from noveltranslator.storage.repository import NovelRepository


class FakeAudioEngine:
    def synthesize(self, text, voice_style, lang, speed, total_steps):
        return text, 0.1

    def save_audio(self, audio, path):
        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(b"\x00\x00" * 2400)


def make_repository(tmp_path: Path) -> NovelRepository:
    repository = NovelRepository(tmp_path / "novels")
    novel = Novel("demo", "Demo", None, "en", None, None, "test", "https://example.test")
    repository.create_novel(novel, "demo")
    repository.create_chapter("demo", Chapter(0, "Chapter 0", "https://example.test/0"))
    repository.save_translation_chunk(
        "demo",
        0,
        "test-translation",
        {"chapter_number": 0, "chunk_index": 1, "translated_text": "Primer párrafo.\n\nSegundo párrafo."},
    )
    return repository


def test_audio_generation_creates_one_chapter_audio_and_manifest(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    events: list[dict[str, object]] = []
    service = AudioGenerationService(
        repository,
        progress_detail_callback=events.append,
        engine_factory=lambda voice: (FakeAudioEngine(), object()),
    )

    first = service.generate_novel("demo", translation_id="test-translation", from_chapter=0, to_chapter=0)
    assert first.segments_generated == 2
    assert first.segments_skipped == 0

    output = first.output_paths[0]
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["segments"]) == 2
    assert (output / "chapter_000.wav").is_file()
    assert len(manifest["segments"]) == 2
    assert not (output / "segments").exists()
    assert manifest["version"] == 4
    assert manifest["steps"] == 8
    assert manifest["tail_silence_seconds"] == 0.35
    assert events[0]["event"] == "chapter_started"
    assert [event["event"] for event in events[1:]] == ["unit_completed", "unit_completed", "chapter_completed"]
    assert events[1]["chunk_index"] == 1
    assert events[2]["unit_position"] == 2

    second = service.generate_novel("demo", translation_id="test-translation", from_chapter=0, to_chapter=0)
    assert second.segments_generated == 0
    assert second.chapters_skipped == 1
    assert second.segments_skipped == 2


def test_audio_units_group_expressions_and_remove_boundary_overlap() -> None:
    units = AudioGenerationService._chapter_speech_units(
        [
            (1, "La puerta se abrió Mientras"),
            (2, "mientras las gotas golpeaban el alero.\n\nPloc, ploc, ploc."),
            (3, "La noche cayó."),
        ],
        max_characters=900,
    )

    assert [unit.text for unit in units] == [
        "La puerta se abrió Mientras las gotas golpeaban el alero.",
        "Ploc, ploc, ploc. La noche cayó.",
    ]

