from noveltranslator.core.models import Entity

from .entity_extractor import EntityExtractor


class TextAnalyzer:
    def __init__(self, entity_extractor: EntityExtractor | None = None) -> None:
        self.entity_extractor = entity_extractor or EntityExtractor()

    def analyze(self, paragraphs: list[str], *, chapter_number: int | None = None) -> dict:
        entities: list[Entity] = self.entity_extractor.extract(paragraphs, chapter_number=chapter_number)
        return {"entities": entities, "terms_found": [entity.text for entity in entities]}

