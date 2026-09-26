from dataclasses import dataclass, field

from noveltranslator.core.models import Chunk, Entity, GlossaryTerm


@dataclass(frozen=True)
class TranslationContext:
    novel_title: str
    chapter_title: str
    chapter_number: int
    chunk: Chunk
    previous_chunk_text: str | None = None
    glossary_terms: list[GlossaryTerm] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)


class ContextBuilder:
    def __init__(self, previous_chunks: int = 1, include_glossary: bool = True, include_entities: bool = True) -> None:
        self.previous_chunks = max(0, previous_chunks)
        self.include_glossary = include_glossary
        self.include_entities = include_entities

    def build(self, novel_title: str, chapter_title: str, chapter_number: int, chunk: Chunk, previous_chunks: list[Chunk], glossary_terms: list[GlossaryTerm], entities: list[Entity]) -> TranslationContext:
        searchable = f"{chunk.source_text}\n" + "\n".join(item.source_text for item in previous_chunks[-self.previous_chunks:])
        lowered = searchable.casefold()
        terms = [term for term in glossary_terms if term.term.casefold() in lowered] if self.include_glossary else []
        found_entities = [entity for entity in entities if entity.text.casefold() in lowered] if self.include_entities else []
        previous = "\n\n".join(item.source_text for item in previous_chunks[-self.previous_chunks:]) or None
        return TranslationContext(novel_title, chapter_title, chapter_number, chunk, previous, terms, found_entities)
