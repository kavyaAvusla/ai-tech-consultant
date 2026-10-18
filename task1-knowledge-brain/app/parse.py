from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "noscript", "svg"}
TRACKING_HINTS = ("/hit", "spacer.gif", "profile_blank")
BANNER_HINTS = ("marketplacebannertest", "logo.svg", "fav_icon", "/logo/")


@dataclass
class ImageRef:
    url: str
    alt: str
    heading: str


@dataclass
class TextChunk:
    heading: str
    text: str


@dataclass
class ParsedArticle:
    title: str
    canonical_url: str
    text_chunks: list[TextChunk] = field(default_factory=list)
    images: list[ImageRef] = field(default_factory=list)
    body_html: str = ""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_tracking_or_chrome(src: str) -> bool:
    lower = src.lower()
    return any(hint in lower for hint in TRACKING_HINTS + BANNER_HINTS)


def _abs_url(src: str, page_url: str) -> str:
    return urljoin(page_url, src)


def _clean_image_url(url: str) -> str:
    parsed = urlparse(url)
    if "amazonaws.com" in parsed.netloc or "freshdesk.com" in parsed.netloc:
        return url
    return url.split("#")[0]


def parse_article_html(html: str, page_url: str) -> ParsedArticle:
    soup = BeautifulSoup(html, "lxml")
    canonical = ""
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        canonical = link["href"].strip()
    body = soup.select_one("article.article-body") or soup.select_one("#article-body")
    if body is None:
        raise ValueError("article body not found")

    h1 = body.select_one("h1.post-title, h1")
    title = normalize_space(h1.get_text(" ", strip=True) if h1 else "")
    if not title:
        title = normalize_space(soup.title.get_text(" ", strip=True) if soup.title else page_url)

    for junk in body.select(".the-article-link, .copy-link-to-section"):
        junk.decompose()

    heading = title
    buffer: list[str] = []
    text_chunks: list[TextChunk] = []
    images: list[ImageRef] = []
    seen_images: set[str] = set()

    def flush_text() -> None:
        text = normalize_space(" ".join(buffer))
        buffer.clear()
        if text:
            text_chunks.append(TextChunk(heading=heading, text=text))

    def handle_img(tag: Tag) -> None:
        src = tag.get("src") or tag.get("data-src") or ""
        if not src:
            return
        abs_url = _clean_image_url(_abs_url(src, page_url))
        if _is_tracking_or_chrome(abs_url) or abs_url in seen_images:
            return
        if abs_url.startswith("data:"):
            return
        seen_images.add(abs_url)
        alt = normalize_space(tag.get("alt") or "")
        images.append(ImageRef(url=abs_url, alt=alt, heading=heading))

    def walk(node: Tag) -> None:
        nonlocal heading
        for child in node.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    buffer.append(text)
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in SKIP_TAGS:
                continue
            if child.name in HEADINGS:
                flush_text()
                heading = normalize_space(child.get_text(" ", strip=True)) or heading
                continue
            if child.name == "img":
                handle_img(child)
                continue
            if child.name in {"p", "li", "td", "th", "blockquote", "pre", "figcaption"}:
                nested_imgs = list(child.find_all("img"))
                for img in nested_imgs:
                    handle_img(img)
                    img.extract()
                text = normalize_space(child.get_text(" ", strip=True))
                if text:
                    buffer.append(text)
                continue
            walk(child)

    walk(body)
    flush_text()

    body_fingerprint = normalize_space(body.get_text(" ", strip=True))
    body_fingerprint += "\n" + "\n".join(img.url for img in images)

    return ParsedArticle(
        title=title,
        canonical_url=canonical or page_url,
        text_chunks=text_chunks,
        images=images,
        body_html=body_fingerprint,
    )


def page_content_hash(parsed: ParsedArticle) -> str:
    return sha256_text(parsed.body_html)


def chunk_hash(chunk_type: str, heading: str, image_url: str, text_for_text_chunks: str) -> str:
    if chunk_type == "image":
        payload = f"image|{heading}|{image_url}"
    else:
        payload = f"text|{heading}|{text_for_text_chunks}"
    return sha256_text(payload)
