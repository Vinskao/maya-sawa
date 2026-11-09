"""Podcast RSS for the approved daily market reading (Spotify and other directories poll this feed).

Pure functions only: the router supplies already-approved episodes that have finished audio.
"""
from datetime import datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape

ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'


def describe_sources(sources):
    """Turn internal source references into text a listener can read in show notes."""
    described = []
    for source in sources:
        parts = source.split(':')
        if len(parts) == 3 and parts[0] == 'stock' and parts[2].isdigit():
            described.append(f'TY Multiverse 個股分析 {parts[1]}（第 {parts[2]} 版）')
        elif len(parts) == 3 and parts[0] == 'macro-node' and parts[2].isdigit():
            described.append(f'TY Multiverse 總經分析 {parts[1]}（第 {parts[2]} 版）')
        else:
            described.append(source)
    return described


def _title(episode):
    return episode.get('title') or '每日市場精讀｜' + episode['day'].replace('-', '/')


def _show_notes(episode, disclaimer):
    paragraphs = ''.join('<p>' + escape(part.strip()) + '</p>' for part in episode['content'].split('\n') if part.strip())
    sources = ''.join('<li>' + escape(line) + '</li>' for line in describe_sources(episode['sources']))
    return paragraphs + '<p>來源：</p><ul>' + sources + '</ul><p>' + escape(disclaimer) + '</p>'


def _item(episode, config):
    enclosure_url = f"{config['audioBaseUrl']}/daily/{episode['id']}/{episode['revision']}"
    published = format_datetime(datetime.fromisoformat(episode['createdAt']))
    return (
        '<item>'
        f"<title>{escape(_title(episode))}</title>"
        f"<description>{escape(_show_notes(episode, config['disclaimer']))}</description>"
        f"<link>{escape(config['link'])}</link>"
        f'<guid isPermaLink="false">{escape(episode["id"])}</guid>'
        f'<pubDate>{published}</pubDate>'
        f'<enclosure url="{escape(enclosure_url)}" length="{int(episode["size"])}" type="audio/mpeg"/>'
        '<itunes:explicit>false</itunes:explicit>'
        '</item>'
    )


def build_podcast_rss(episodes, config):
    """Newest first. Episodes without audio bytes are skipped so the feed never lists a broken enclosure."""
    ready = sorted((e for e in episodes if e.get('size')), key=lambda e: e['createdAt'], reverse=True)
    channel = (
        f"<title>{escape(config['title'])}</title>"
        f"<link>{escape(config['link'])}</link>"
        f"<description>{escape(config['description'])}</description>"
        f"<language>{escape(config['language'])}</language>"
        f"<itunes:author>{escape(config['author'])}</itunes:author>"
        '<itunes:explicit>false</itunes:explicit>'
        '<itunes:type>episodic</itunes:type>'
        f'<itunes:owner><itunes:name>{escape(config["ownerName"])}</itunes:name>'
        f'<itunes:email>{escape(config["ownerEmail"])}</itunes:email></itunes:owner>'
        f'<itunes:image href="{escape(config["imageUrl"])}"/>'
        f'<itunes:category text="{escape(config["category"])}">'
        f'<itunes:category text="{escape(config["subcategory"])}"/></itunes:category>'
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<rss version="2.0" xmlns:itunes="{ITUNES_NS}"><channel>'
            + channel + ''.join(_item(e, config) for e in ready) + '</channel></rss>')
