"""Record approved source assignments and the tested feed endpoints.

AllSides classifications were reviewed on November 8, 2026 for the original ten
outlets and on November 18, 2026 for later additions. Article and feed hosts
remain separate so feed redirects never authorize unrelated article reads."""

from datetime import date
from urllib.parse import urlsplit
from pydantic import Field, BaseModel

from backend.sources.constants import SOURCE_CONSTANTS
from backend.agents.researcher_findings import SourceGroup


class OutletConfiguration(BaseModel):
    """Own one fixed outlet assignment, exact hosts, and rating provenance."""

    model_config = SOURCE_CONSTANTS.model_config

    outlet_id: str
    display_name: str
    group: SourceGroup
    article_hosts: tuple[str, ...] = Field(min_length=1)
    feed_urls: tuple[str, ...] = Field(min_length=1)
    feed_hosts: tuple[str, ...] = Field(min_length=1)
    classification: str
    classification_url: str
    classification_scope: str = "online news"
    classification_reviewed_on: date = date(2026, 11, 8)


def _configure_outlet(
    outlet_id: str,
    display_name: str,
    group: SourceGroup,
    classification: str,
    profile_slug: str,
    article_hosts: tuple[str, ...],
    feed_urls: tuple[str, ...],
    redirect_hosts: tuple[str, ...] = (),
    reviewed_on: date = date(2026, 11, 8),
) -> OutletConfiguration:
    """Build a fixed record with separate feed host permissions and provenance."""
    return OutletConfiguration(
        outlet_id=outlet_id,
        display_name=display_name,
        group=group,
        article_hosts=article_hosts,
        feed_urls=feed_urls,
        feed_hosts=tuple(dict.fromkeys(
            (*(urlsplit(feed_url).netloc for feed_url in feed_urls), *redirect_hosts),
        )),
        classification=classification,
        classification_url=f"https://www.allsides.com/news-source/{profile_slug}",
        classification_reviewed_on=reviewed_on,
    )


NEW_OUTLET_REVIEWED_ON: date = date(2026, 11, 18)

OUTLETS: tuple[OutletConfiguration, ...] = (
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.NPR.value, "NPR online news", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "npr-media-bias", ("www.npr.org", "npr.org"),
        ("https://feeds.npr.org/1004/rss.xml", "https://feeds.npr.org/1014/rss.xml"),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.NBC.value, "NBC News Digital", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "nbc-news-media-bias", ("www.nbcnews.com", "nbcnews.com"),
        (
            "https://feeds.nbcnews.com/nbcnews/public/world",
            "https://feeds.nbcnews.com/nbcnews/public/politics",
        ),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.HUFFPOST.value, "HuffPost", SOURCE_CONSTANTS.groups.LIBERAL,
        "Left", "huffpost-media-bias", ("www.huffpost.com", "huffpost.com"),
        (
            "https://www.huffpost.com/section/world-news/feed",
            "https://www.huffpost.com/section/politics/feed",
        ),
        ("chaski.huffpost.com",),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.ABC.value, "ABC News online", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "abc-news-media-bias", ("abcnews.go.com", "abcnews.com"),
        (
            "https://abcnews.go.com/abcnews/internationalheadlines",
            "https://abcnews.go.com/abcnews/politicsheadlines",
        ),
        ("abcnews.com",),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.CBS.value, "CBS News online", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "cbs-news-online-media-bias", ("www.cbsnews.com", "cbsnews.com"),
        (
            "https://www.cbsnews.com/latest/rss/world",
            "https://www.cbsnews.com/latest/rss/politics",
        ),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.GUARDIAN.value, "The Guardian", SOURCE_CONSTANTS.groups.LIBERAL,
        "Left", "guardian-media-bias", ("www.theguardian.com", "theguardian.com"),
        (
            "https://www.theguardian.com/us-news/rss",
            "https://www.theguardian.com/us-news/us-politics/rss",
        ),
        reviewed_on=NEW_OUTLET_REVIEWED_ON,
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.SALON.value, "Salon", SOURCE_CONSTANTS.groups.LIBERAL,
        "Left", "salon-media-bias", ("www.salon.com", "salon.com"),
        (
            "https://www.salon.com/feed/",
            "https://www.salon.com/category/politics/feed/",
        ),
        reviewed_on=NEW_OUTLET_REVIEWED_ON,
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.MOTHER_JONES.value, "Mother Jones",
        SOURCE_CONSTANTS.groups.LIBERAL,
        "Left", "mother-jones-media-bias", ("www.motherjones.com", "motherjones.com"),
        (
            "https://www.motherjones.com/feed/",
            "https://www.motherjones.com/politics/feed/",
        ),
        reviewed_on=NEW_OUTLET_REVIEWED_ON,
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.FOX.value, "Fox News Digital", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Right", "fox-news-media-bias", ("www.foxnews.com", "foxnews.com"),
        (
            "https://moxie.foxnews.com/google-publisher/world.xml",
            "https://moxie.foxnews.com/google-publisher/politics.xml",
        ),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.DAILY_CALLER.value, "The Daily Caller", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Lean Right", "daily-caller-media-bias", ("dailycaller.com", "www.dailycaller.com"),
        ("https://dailycaller.com/feed/",),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.BREITBART.value, "Breitbart", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Right", "breitbart-news-media-bias", ("www.breitbart.com", "breitbart.com"),
        ("https://www.breitbart.com/feed/",), ("feeds.feedburner.com",),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.NEW_YORK_POST.value, "New York Post news", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Right", "new-york-post-news-media-bias", ("nypost.com", "www.nypost.com"),
        ("https://nypost.com/world-news/feed/", "https://nypost.com/politics/feed/"),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.EXAMINER.value, "Washington Examiner", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Lean Right", "washington-examiner-media-bias",
        ("www.washingtonexaminer.com", "washingtonexaminer.com"),
        (
            "https://www.washingtonexaminer.com/feed/",
            "https://www.washingtonexaminer.com/category/news/politics/feed/",
        ),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.FREE_BEACON.value, "Washington Free Beacon",
        SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Right", "washington-free-beacon-media-bias", ("freebeacon.com", "www.freebeacon.com"),
        ("https://freebeacon.com/feed/",),
        reviewed_on=NEW_OUTLET_REVIEWED_ON,
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.JUST_THE_NEWS.value, "Just the News",
        SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Lean Right", "just-news-media-bias", ("justthenews.com", "www.justthenews.com"),
        ("https://justthenews.com/rss.xml",),
        reviewed_on=NEW_OUTLET_REVIEWED_ON,
    ),
)
