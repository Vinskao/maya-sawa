"""Conservative text screening. This is a signal, not proof a document is safe."""
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class ReviewResult:
    flagged: bool
    reason: str | None = None


_PATTERNS = [
    re.compile(r'\b(?:ignore|disregard|override|forget)\b.{0,60}\b(?:previous|prior|above|system|developer|instructions?|prompts?)\b', re.I | re.S),
    re.compile(r'\b(?:reveal|print|leak|exfiltrate|send)\b.{0,80}\b(?:system prompt|api key|secret|credential|password)\b', re.I | re.S),
    re.compile(r'(?:忽略|無視|覆盖|覆蓋|忘記).{0,30}(?:指示|指令|提示詞|提示词|規則|规则)', re.S),
    re.compile(r'(?:洩漏|泄露|輸出|输出|傳送|发送).{0,30}(?:系統提示|系统提示|金鑰|密鑰|密钥|密碼|密码|憑證|凭证)', re.S),
    re.compile(r'<\|(?:system|assistant|user|im_start|im_end)\|>', re.I),
]


def review_report_pages(pages: list[str]) -> ReviewResult:
    for page in pages:
        if any(unicodedata.category(ch) == 'Cf' for ch in page):
            return ReviewResult(True, 'invisible_control')
        text = unicodedata.normalize('NFKC', page)
        if any(pattern.search(text) for pattern in _PATTERNS):
            return ReviewResult(True, 'instruction_pattern')
    return ReviewResult(False)
