"""Research records hold Mermaid flowcharts (supply chain, technology). Social posts get them as images: the Mermaid
subset the records use is parsed here, converted to Graphviz DOT, laid out by `dot`, and placed on a 1080x1350 card
(the same size as the summary card, because Instagram crops every carousel image to the first one's ratio)."""
import io
import re
import subprocess

from PIL import Image, ImageDraw

from .card import BG, CARD_SIZE, DIM, FOOTER_URL, WHITE, _font, fit_size

FLOW = re.compile(r'^\s*(flowchart|graph)\s+(TB|TD|BT|LR|RL)\b', re.I)
ARROW = re.compile(r'\s*(-\.->|-->|==>|---)\s*(?:\|([^|]*)\|\s*)?')
NODE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*(?:\[\s*"?(.*?)"?\s*\]|\(\s*"?(.*?)"?\s*\)|\{\s*"?(.*?)"?\s*\})?\s*$')
SUBGRAPH = re.compile(r'^\s*subgraph\s+([A-Za-z0-9_]+)\s*(?:\[\s*"?(.*?)"?\s*\])?\s*$')
IGNORED = ('classDef', 'class ', 'style ', 'linkStyle', 'direction', '%%')
TITLES = {'supplyChain': '供應鏈', 'technology': '技術路線'}


def mermaid_sources(record, prefix=''):
    """Every Mermaid flowchart anywhere in a research record, as (dotted path, source): no field names assumed."""
    found = []
    if isinstance(record, str):
        if FLOW.match(record):
            found.append((prefix, record))
    elif isinstance(record, dict):
        for key, value in record.items():
            found += mermaid_sources(value, f'{prefix}.{key}' if prefix else key)
    elif isinstance(record, list):
        for index, value in enumerate(record):
            found += mermaid_sources(value, f'{prefix}.{index}' if prefix else str(index))
    return found


def parse_flowchart(source):
    lines = source.strip().split('\n')
    head = FLOW.match(lines[0])
    graph = {'direction': 'TB' if head.group(2).upper() == 'TD' else head.group(2).upper(), 'nodes': {}, 'clusters': [],
             'edges': []}
    stack = []

    def node(token):
        match = NODE.match(token)
        if not match:
            raise ValueError(f'Unsupported Mermaid node: {token!r}')
        key = match.group(1)
        label = next((g for g in match.groups()[1:] if g is not None), None)
        if label is not None or key not in graph['nodes']:
            graph['nodes'][key] = label if label is not None else graph['nodes'].get(key, key)
        if stack and key not in stack[-1]['nodes']:
            stack[-1]['nodes'].append(key)
        return key

    for raw in lines[1:]:
        line = raw.strip()
        if not line or line.startswith(IGNORED):
            continue
        if line.startswith('subgraph'):
            match = SUBGRAPH.match(line)
            if match:
                stack.append({'id': match.group(1), 'title': match.group(2) or match.group(1), 'nodes': []})
            else:  # `subgraph 中文標題`: no id, the whole rest is the title
                title = line[len('subgraph'):].strip().strip('"')
                stack.append({'id': f"S{len(graph['clusters']) + len(stack)}", 'title': title, 'nodes': []})
        elif line == 'end':
            if stack:
                graph['clusters'].append(stack.pop())
        else:
            pieces = ARROW.split(line)  # token, arrow, label, token, arrow, label, token ...
            keys = [node(pieces[0])]
            for index in range(1, len(pieces), 3):
                target = node(pieces[index + 2])
                graph['edges'].append((keys[-1], target, (pieces[index + 1] or '').strip(), pieces[index] == '-.->'))
                keys.append(target)
    return graph


def _wrap(label, width=16):
    """Break long labels (CJK counts as two columns) so nodes stay narrow enough for a portrait card."""
    lines, current, used = [], '', 0
    for char in label:
        size = 2 if ord(char) > 0x2E80 else 1
        inside_word = char.isascii() and char.isalnum() and current[-1:].isascii() and current[-1:].isalnum()
        if used + size > width * 2 and current and not inside_word:  # never cut 'S1' into 'S' and '1'
            lines.append(current)
            current, used = '', 0
        current += char
        used += size
    return lines + [current]


def _q(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _label(text, width=16):
    """A quoted DOT label: each wrapped line escaped on its own, then joined with DOT's own break (backslash + n).
    Escaping after joining would turn that break into a visible backslash-n."""
    return '"' + '\\n'.join(line.replace('\\', '\\\\').replace('"', '\\"') for line in _wrap(text, width)) + '"'


def choose_direction(direction, width, height):
    """A wide top-to-bottom drawing (many siblings in one rank) is flipped to left-to-right so it becomes tall and its
    text stays readable once scaled into a portrait card."""
    if direction in ('TB', 'TD', 'BT') and width > height * 1.4:
        return 'LR'
    return direction


def to_dot(source, direction=None):
    graph = parse_flowchart(source)
    font = 'Noto Sans TC'
    out = ['digraph G {', f'  rankdir={direction or graph["direction"]}; bgcolor="#0a0a0b"; pad=0.2; nodesep=0.35; ranksep=0.45;',
           f'  node [shape=box style="rounded,filled" fillcolor="#1c1c20" color="#46464c" fontcolor="#f4f4f4" fontname={_q(font)} fontsize=14 margin="0.18,0.1"];',
           f'  edge [color="#8a8a90" fontcolor="#b4b4b9" fontname={_q(font)} fontsize=11 arrowsize=0.7];']
    clustered = {key for cluster in graph['clusters'] for key in cluster['nodes']}
    for key, label in graph['nodes'].items():
        if key not in clustered:
            out.append(f'  {_q(key)} [label={_label(label)}];')
    for cluster in graph['clusters']:
        out.append(f'  subgraph cluster_{cluster["id"]} {{ label={_label(cluster["title"], 22)}; style="rounded,dashed"; '
                   f'color="#5a5a60"; fontcolor="#d0d0d4"; fontname={_q(font)}; fontsize=13;')
        for key in cluster['nodes']:
            out.append(f'    {_q(key)} [label={_label(graph["nodes"][key])}];')
        out.append('  }')
    for a, b, label, dashed in graph['edges']:
        attrs = [f'label={_label(label, 18)}'] if label else []
        if dashed:
            attrs.append('style=dashed')
        out.append(f'  {_q(a)} -> {_q(b)}' + (f' [{" ".join(attrs)}]' if attrs else '') + ';')
    out.append('}')
    return '\n'.join(out)


def _draw(source, direction=None):
    try:
        done = subprocess.run(['dot', '-Tpng', '-Gdpi=130'], input=to_dot(source, direction).encode(),
                              capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Graphviz unavailable: {type(exc).__name__}') from exc
    if done.returncode != 0:
        raise RuntimeError(f'Graphviz failed: {done.stderr.decode(errors="replace")[:200]}')
    return Image.open(io.BytesIO(done.stdout)).convert('RGB')


def render_diagram_card(title, source):
    """The diagram on a 1080x1350 card with a heading; raises RuntimeError if Graphviz fails."""
    diagram = _draw(source)
    wanted = choose_direction(parse_flowchart(source)['direction'], diagram.width, diagram.height)
    if wanted != parse_flowchart(source)['direction']:
        diagram = _draw(source, wanted)
    image = Image.new('RGB', CARD_SIZE, BG)
    draw = ImageDraw.Draw(image)
    margin = 64
    draw.text((margin, 64), 'BIRCH INVESTMENTS', font=_font('Bold', 34), fill=WHITE)
    title_size = fit_size(title, 52, 28, CARD_SIZE[0] - 2 * margin, lambda text, size: draw.textlength(text, font=_font('Bold', size)))
    draw.text((margin, 118), title, font=_font('Bold', title_size), fill=WHITE)
    top, bottom = 220, CARD_SIZE[1] - 150
    box = (CARD_SIZE[0] - 2 * margin, bottom - top)
    scale = min(box[0] / diagram.width, box[1] / diagram.height, 1.6)
    size = (max(1, int(diagram.width * scale)), max(1, int(diagram.height * scale)))
    diagram = diagram.resize(size, Image.LANCZOS)
    image.paste(diagram, (margin + (box[0] - size[0]) // 2, top + (box[1] - size[1]) // 2))
    draw.text((margin, CARD_SIZE[1] - 100), FOOTER_URL, font=_font('Regular', 34), fill=DIM)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def diagram_title(record, path):
    return f"{record.get('name', '')} · {TITLES.get(path.split('.')[-1], path.split('.')[-1])}".strip(' ·')
