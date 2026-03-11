import html
import re

import feedparser


def _match(pattern, text):
    """Extract first capture group from pattern, or return empty string on failure."""
    m = re.search(pattern, text)
    return m.group(1) if m else ""


def _img_src(element):
    return _match(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element)


def _img_alt(element):
    return _match(r'<img[^>]+alt=["\"]([^"\"]+)["\"]', element)


def _split_safe(text, sep, index):
    """Split text and return the part at index, or the full text on failure."""
    parts = text.split(sep)
    return parts[index].strip() if len(parts) > index else text.strip()


COMICS = {
    "XKCD": {
        "feed": "https://xkcd.com/atom.xml",
        "element": lambda feed: feed.entries[0].description,
        "url": lambda element: _img_src(element),
        "title": lambda feed: feed.entries[0].title,
        "caption": lambda element: _img_alt(element),
    },
    "Cyanide & Happiness": {
        "feed": "https://explosm-1311.appspot.com/",
        "element": lambda feed: feed.entries[0].description,
        "url": lambda element: _img_src(element),
        "title": lambda feed: _split_safe(feed.entries[0].title, " - ", 1),
        "caption": lambda element: "",
    },
    "Saturday Morning Breakfast Cereal": {
        "feed": "http://www.smbc-comics.com/comic/rss",
        "element": lambda feed: feed.entries[0].description,
        "url": lambda element: _img_src(element),
        "title": lambda feed: _split_safe(feed.entries[0].title, "-", 1),
        "caption": lambda element: _match(r'Hovertext:<br />(.*?)</p>', element),
    },
    "The Perry Bible Fellowship": {
        "feed": "https://pbfcomics.com/feed/",
        "element": lambda feed: feed.entries[0].description,
        "url": lambda element: _img_src(element),
        "title": lambda feed: feed.entries[0].title,
        "caption": lambda element: _img_alt(element),
    },
    "Questionable Content": {
        "feed": "http://www.questionablecontent.net/QCRSS.xml",
        "element": lambda feed: feed.entries[0].description,
        "url": lambda element: _img_src(element),
        "title": lambda feed: feed.entries[0].title,
        "caption": lambda element: "",
    },
    "Poorly Drawn Lines": {
        "feed": "https://poorlydrawnlines.com/feed/",
        "element": lambda feed: feed.entries[0].get('content', [{}])[0].get('value', ''),
        "url": lambda element: _img_src(element),
        "title": lambda feed: feed.entries[0].title,
        "caption": lambda element: "",
    },
    "Dinosaur Comics": {
        "feed": "https://www.qwantz.com/rssfeed.php",
        "element": lambda feed: feed.entries[0].description,
        "url": lambda element: _img_src(element),
        "title": lambda feed: feed.entries[0].title,
        "caption": lambda element: _match(r'title="(.*?)" />', element.replace('\n', '')),
    },
    "webcomic name": {
        "feed": "https://webcomicname.com/rss",
        "element": lambda feed: feed.entries[0].description,
        "url": lambda element: _img_src(element),
        "title": lambda feed: "",
        "caption": lambda element: "",
    },
}


def get_panel(comic_name):
    feed = feedparser.parse(COMICS[comic_name]["feed"])
    try:
        element = COMICS[comic_name]["element"](feed)
    except (IndexError, AttributeError):
        raise RuntimeError("Failed to retrieve latest comic.")

    return {
        "image_url": COMICS[comic_name]["url"](element),
        "title": html.unescape(COMICS[comic_name]["title"](feed)),
        "caption": html.unescape(COMICS[comic_name]["caption"](element)),
    }
