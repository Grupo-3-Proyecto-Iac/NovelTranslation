import re

from noveltranslator.core.models import Chunk


class TextSplitter:
    def __init__(self, max_characters: int = 6000, target_characters: int = 4500, overlap_paragraphs: int = 1) -> None:
        if max_characters < 1 or target_characters < 1 or target_characters > max_characters or overlap_paragraphs < 0:
            raise ValueError("invalid chunking configuration")
        self.max_characters = max_characters
        self.target_characters = target_characters
        self.overlap_paragraphs = overlap_paragraphs

    def split(self, paragraphs: list[str], chapter_number: int) -> list[Chunk]:
        chunks: list[Chunk] = []
        current: list[str] = []
        current_start = 0
        current_length = 0
        for paragraph_index, paragraph in enumerate(paragraphs):
            if len(paragraph) > self.max_characters:
                if current:
                    chunks.append(self._chunk(chapter_number, len(chunks) + 1, current, current_start, paragraph_index))
                    current = []
                    current_length = 0
                pieces = self._split_long_paragraph(paragraph)
                for piece in pieces:
                    chunks.append(Chunk(chapter_number, len(chunks) + 1, piece, paragraph_index, paragraph_index + 1))
                current_start = paragraph_index + 1
                continue
            proposed = current_length + len(paragraph) + (1 if current else 0)
            if current and proposed > self.target_characters:
                chunks.append(self._chunk(chapter_number, len(chunks) + 1, current, current_start, paragraph_index))
                overlap = paragraphs[max(current_start, paragraph_index - self.overlap_paragraphs):paragraph_index]
                current = list(overlap)
                current_start = max(current_start, paragraph_index - self.overlap_paragraphs)
                current_length = sum(len(item) for item in current) + max(0, len(current) - 1)
            if not current:
                current_start = paragraph_index
            current.append(paragraph)
            current_length += len(paragraph) + (1 if len(current) > 1 else 0)
        if current:
            chunks.append(self._chunk(chapter_number, len(chunks) + 1, current, current_start, len(paragraphs)))
        return chunks

    def _split_long_paragraph(self, paragraph: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        pieces: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > self.max_characters:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.extend(sentence[index:index + self.max_characters] for index in range(0, len(sentence), self.max_characters))
            elif current and len(current) + 1 + len(sentence) > self.max_characters:
                pieces.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current)
        return pieces

    @staticmethod
    def _chunk(chapter_number: int, index: int, paragraphs: list[str], start: int, end: int) -> Chunk:
        return Chunk(chapter_number, index, "\n\n".join(paragraphs), start, end)

