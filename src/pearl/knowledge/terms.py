import re
_STOPWORDS = frozenset({'about', 'after', 'also', 'another', 'because', 'been', 'before', 'being', 'between', 'both', 'does', 'each', 'from', 'have', 'here', 'into', 'more', 'must', 'only', 'over', 'same', 'should', 'some', 'than', 'that', 'their', 'them', 'then', 'there', 'these', 'they', 'this', 'those', 'used', 'using', 'what', 'when', 'where', 'which', 'while', 'with', 'would', 'your'})

def _terms(text: str) -> set[str]:
    tokens = {token for token in re.split('[^a-z0-9]+', str(text).casefold()) if len(token) > 3}
    return tokens - _STOPWORDS
_NON_NEUTRAL = re.compile('\\b(?:v\\d{2,}|S(?:-[CE])?\\d+|scenario[_ -]?\\d+|ground[_ -]?truth|hidden[_ -]?answer)\\b', re.I)
