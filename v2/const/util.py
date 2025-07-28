from v2.const.const import TERM_COMPONENTS

def is_relevant_article(text: str) -> bool:
    return any(all(term in text for term in group) for group in TERM_COMPONENTS)