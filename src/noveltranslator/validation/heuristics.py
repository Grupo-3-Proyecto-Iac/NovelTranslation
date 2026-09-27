import re

ENGLISH_COMMON = frozenset("the a an and or but if then he she it they we you your his her their is are was were be been to of in on at for with from into out as that this these those not no do did have has had will would can could should said asked looked walked room".split())


def words(text: str) -> list[str]:
    return re.findall(r"[\w'-]+", text.casefold())


def untranslated_ratio(text: str, excluded: set[str] | None = None) -> float:
    tokens = words(text)
    excluded = {item.casefold() for item in (excluded or set())}
    candidates = [token for token in tokens if token not in excluded]
    if not candidates:
        return 0.0
    return sum(token in ENGLISH_COMMON for token in candidates) / len(candidates)


def has_invalid_unicode(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return any(0xD800 <= ord(char) <= 0xDFFF for char in text)
