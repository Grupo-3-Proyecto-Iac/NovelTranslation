from .models import TranslationRequest


def build_translation_prompt(request: TranslationRequest) -> str:
    terms = "\n".join(f"- {item.term} -> {item.translation or item.term}" for item in request.protected_terms)
    memory = "\n".join(f"- {item.source_text} -> {item.translated_text}" for item in request.translation_memory)
    narrative = "\n".join(f"- {item.text}" for item in request.narrative_context)
    context = request.previous_context or "(none)"
    return f"""You are translating a web novel from English to Spanish.

Rules:
- Translate faithfully; do not summarize, omit, or add explanations.
- Preserve dialogue formatting and paragraph breaks.
- Use natural literary Spanish.
- Preserve protected terms exactly as provided.

Novel: {request.novel_title}
Chapter: {request.chapter_title} ({request.chapter_number})
Previous context:
{context}
Protected terminology:
{terms or '(none)'}
Reusable translation memory:
{memory or '(none)'}
Relevant narrative context:
{narrative or '(none)'}

Text:
{request.source_text}
"""
