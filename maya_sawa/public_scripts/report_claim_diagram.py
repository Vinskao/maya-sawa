"""Render a Benchmark proposal JSON file as a standalone SVG."""

import argparse
import json
from pathlib import Path
from textwrap import wrap
from xml.sax.saxutils import escape


DIRECTIONS = (
    ("tailwind", "順風", "#166534", "#dcfce7"),
    ("headwind", "逆風", "#9f1239", "#ffe4e6"),
    ("neutral", "中性", "#334155", "#e2e8f0"),
)


def render_claim_diagram(title: str, claims: list[dict], status: str = "待審提案") -> str:
    def label(x: int, y: int, value: str, size: int = 18, color: str = "#172033") -> str:
        clean = "".join(char for char in value if char.isprintable())
        return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{escape(clean)}</text>'

    elements = [label(28, 33, status, 16, "#475569")]
    y = 60
    for line in wrap(title, 38):
        elements.append(label(28, y, line, 22))
        y += 29
    for direction, name, ink, fill in DIRECTIONS:
        items = [claim for claim in claims if claim["direction"] == direction]
        elements.extend([
            f'<rect x="28" y="{y}" width="784" height="38" rx="8" fill="{fill}"/>',
            label(44, y + 25, f"{name}  {len(items)}", color=ink),
        ])
        y += 44
        for claim in items:
            lines = wrap(f"p.{int(claim['page'])}  {claim['claim']}", 39)
            height = 18 + 24 * len(lines)
            elements.extend([
                f'<path d="M48 {y - 6} v20 h16" fill="none" stroke="{ink}" stroke-width="2"/>',
                f'<rect x="64" y="{y}" width="748" height="{height}" rx="8" fill="#f1f5f9"/>',
                *(label(79, y + 26 + 24 * index, line) for index, line in enumerate(lines)),
            ])
            y += height + 6
        y += 12
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="840" height="{y + 12}" viewBox="0 0 840 {y + 12}" '
        'role="img" aria-labelledby="title" xml:space="preserve" '
        'font-family="Noto Sans CJK TC, Microsoft JhengHei, PingFang TC, sans-serif">'
        f'<title>{escape(title)} · {escape(status)}</title>'
        '<rect width="100%" height="100%" rx="16" fill="#fff"/>'
        + "".join(elements) + "</svg>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    claims = json.loads(args.proposal.read_text(encoding="utf-8"))["claims"]
    args.output.write_text(render_claim_diagram(args.title, claims), encoding="utf-8")


if __name__ == "__main__":
    main()
