from noveltranslator.core.enums import EntityStatus, EntityType, GlossaryStatus
from noveltranslator.core.models import Entity, GlossaryTerm
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso


class GlossaryManager:
    def __init__(self, repository: NovelRepository, novel_id: str) -> None:
        self.repository = repository
        self.novel_id = novel_id

    def list_terms(self) -> list[GlossaryTerm]:
        payload = self.repository.load_glossary(self.novel_id)
        return [GlossaryTerm(**{**item, "status": GlossaryStatus(item.get("status", GlossaryStatus.CANDIDATE))}) for item in payload.get("terms", [])]

    def _save(self, terms: list[GlossaryTerm]) -> None:
        self.repository.save_glossary(self.novel_id, {"terms": terms, "updated_at": utc_now_iso()})

    @staticmethod
    def _key(term: str) -> str:
        return " ".join(term.casefold().split())

    def get(self, term: str) -> GlossaryTerm | None:
        key = self._key(term)
        return next((item for item in self.list_terms() if self._key(item.term) == key), None)

    def exists(self, term: str) -> bool:
        return self.get(term) is not None

    def add(self, item: GlossaryTerm) -> GlossaryTerm:
        terms = self.list_terms()
        existing = next((term for term in terms if self._key(term.term) == self._key(item.term)), None)
        if existing:
            if existing.locked or existing.status in {GlossaryStatus.CONFIRMED, GlossaryStatus.LOCKED}:
                return existing
            if item.translation is not None:
                existing.translation = item.translation
            existing.type = item.type or existing.type
            existing.first_seen_chapter = existing.first_seen_chapter or item.first_seen_chapter
            existing.first_seen_chunk = existing.first_seen_chunk or item.first_seen_chunk
            self._save(terms)
            return existing
        self._save(terms + [item])
        return item

    def add_entity(self, entity: Entity) -> GlossaryTerm:
        return self.add(GlossaryTerm(entity.text, entity.type, entity.translation, entity.status is EntityStatus.LOCKED, GlossaryStatus.CANDIDATE, "automatic", entity.preserve, entity.first_seen_chapter, entity.first_seen_chunk))

    def update(self, term: str, **changes) -> GlossaryTerm:
        terms = self.list_terms()
        item = next((value for value in terms if self._key(value.term) == self._key(term)), None)
        if item is None:
            raise KeyError(term)
        if item.locked and any(key in changes for key in ("term", "type")):
            raise ValueError("locked glossary terms cannot change identity")
        for key, value in changes.items():
            if not hasattr(item, key):
                raise AttributeError(key)
            setattr(item, key, value)
        self._save(terms)
        return item

    def lock(self, term: str) -> GlossaryTerm:
        return self.update(term, locked=True, status=GlossaryStatus.LOCKED)

    def confirm(self, term: str) -> GlossaryTerm:
        return self.update(term, status=GlossaryStatus.CONFIRMED)

    def reject(self, term: str) -> GlossaryTerm:
        return self.update(term, status=GlossaryStatus.REJECTED)

