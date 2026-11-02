"""Post text is the analysis verbatim: no summary, no rewrite. Only identification and a length cut are added."""

SITE = 'tymultiverse.cc'
SITE_LINE = '更多請至我的網站：https://tymultiverse.cc/'
MACRO_TITLE = '總經評論｜所有個股分析共用'
LIMITS = {'threads': 500, 'instagram': 2200, 'facebook': None, 'linkedin': 3000}
BOUNDARIES = '\n。！？；'


def _with_identity(source):
    content = source['content'].strip()
    if source['productType'] == 'macro':
        return content if content.startswith(MACRO_TITLE) else f'{MACRO_TITLE}\n\n{content}'
    code = source['code']
    return content if code in content.split('\n', 1)[0] else f'{code}\n\n{content}'


def _fit(text, limit):
    if limit is None or len(text) <= limit:
        return text
    tail = '\n\n' + SITE_LINE
    budget = limit - len(tail)
    cut = text[:budget]
    boundary = max(cut.rfind(mark) for mark in BOUNDARIES)
    if boundary >= budget * 0.6:  # drop only the unfinished sentence, never most of the post
        cut = cut[:boundary + 1]
    cut = cut.rstrip()
    if SITE in cut:
        return cut
    return cut + tail


def build_post(source, platform):
    """The text for one platform: identity prefix when missing, then the front of the analysis within the limit."""
    return _fit(_with_identity(source), LIMITS[platform])
