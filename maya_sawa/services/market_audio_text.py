"""Split a report for speech synthesis without dropping source characters."""
import re


def split_speech_text(text: str, limit: int = 1000) -> list[str]:
    if limit <= 0:
        raise ValueError('limit must be positive')
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        window = text[:limit]
        boundaries = [match.end() for match in re.finditer(r'[\n。！？；]|\.(?!\d)', window)]
        # A decimal point at the edge of the window needs the following character.
        if boundaries and boundaries[-1] == limit and window[-1] == '.' and text[limit].isdigit():
            boundaries.pop()
        split_at = boundaries[-1] if boundaries else 0
        # Avoid pathological tiny requests when a paragraph starts with punctuation.
        if split_at < limit // 3:
            split_at = limit
            # Keep a decimal numeral together if the hard cut lands inside it.
            if text[limit - 1] in '.0123456789' and text[limit] in '.0123456789':
                match = re.search(r'\d[\d.]*$', window)
                if match and match.start() > 0:
                    split_at = match.start()
        chunks.append(text[:split_at])
        text = text[split_at:]
    return chunks
