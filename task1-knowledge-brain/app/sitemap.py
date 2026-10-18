from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from app.config import ARTICLE_PATH_PREFIX, SITEMAP_URL
from app.http_client import PoliteClient

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def is_article_url(url: str) -> bool:
    path = urlparse(url).path
    return path.startswith(ARTICLE_PATH_PREFIX) and not path.endswith("/hit")


def parse_sitemap_xml(xml_text: str) -> list[tuple[str, str | None]]:
    root = ET.fromstring(xml_text)
    articles: list[tuple[str, str | None]] = []
    for node in root.findall("sm:url", NS):
        loc = node.findtext("sm:loc", default="", namespaces=NS).strip()
        lastmod = node.findtext("sm:lastmod", default=None, namespaces=NS)
        if loc and is_article_url(loc):
            articles.append((loc, lastmod.strip() if lastmod else None))
    if not articles:
        # fallback if the feed omits the namespace
        for node in root.findall("url"):
            loc = (node.findtext("loc") or "").strip()
            lastmod = node.findtext("lastmod")
            if loc and is_article_url(loc):
                articles.append((loc, lastmod.strip() if lastmod else None))
    return articles


def fetch_article_urls(client: PoliteClient) -> list[tuple[str, str | None]]:
    response = client.get_text(SITEMAP_URL, polite_gap=False)
    return parse_sitemap_xml(response.text)


def screenshot_preference_score(url: str, image_count: int | None) -> tuple[int, str]:
    """Higher is better. Prefer known screenshot pages, then how-to/image slugs."""
    score = 0
    lower = url.lower()
    if image_count and image_count > 0:
        score += 100 + min(image_count, 25)
    elif image_count == 0:
        score -= 20
    if "screenshot" in lower:
        score += 50
    if "how-to" in lower or "/how-to-" in lower:
        score += 30
    if "image" in lower:
        score += 15
    return score, url
