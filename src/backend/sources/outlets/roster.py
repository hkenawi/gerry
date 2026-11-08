"""Record approved source assignments and the tested feed endpoints.

AllSides classifications were reviewed on November 8, 2026. Article and feed
hosts remain separate so feed redirects never authorize unrelated article reads."""

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
    feed_url: str,
    redirect_hosts: tuple[str, ...] = (),
) -> OutletConfiguration:
    """Build a fixed record with separate feed host permissions and provenance."""
    return OutletConfiguration(
        outlet_id=outlet_id,
        display_name=display_name,
        group=group,
        article_hosts=article_hosts,
        feed_urls=(feed_url,),
        feed_hosts=(urlsplit(feed_url).netloc, *redirect_hosts),
        classification=classification,
        classification_url=f"https://www.allsides.com/news-source/{profile_slug}",
    )


OUTLETS: tuple[OutletConfiguration, ...] = (
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.NPR.value, "NPR online news", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "npr-media-bias", ("www.npr.org", "npr.org"),
        "https://feeds.npr.org/1004/rss.xml",
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.NBC.value, "NBC News Digital", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "nbc-news-media-bias", ("www.nbcnews.com", "nbcnews.com"),
        "https://feeds.nbcnews.com/nbcnews/public/world",
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.HUFFPOST.value, "HuffPost", SOURCE_CONSTANTS.groups.LIBERAL,
        "Left", "huffpost-media-bias", ("www.huffpost.com", "huffpost.com"),
        "https://www.huffpost.com/section/world-news/feed",
        ("chaski.huffpost.com",),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.ABC.value, "ABC News online", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "abc-news-media-bias", ("abcnews.go.com", "abcnews.com"),
        "https://abcnews.go.com/abcnews/internationalheadlines",
        ("abcnews.com",),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.CBS.value, "CBS News online", SOURCE_CONSTANTS.groups.LIBERAL,
        "Lean Left", "cbs-news-online-media-bias", ("www.cbsnews.com", "cbsnews.com"),
        "https://www.cbsnews.com/latest/rss/world",
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.FOX.value, "Fox News Digital", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Right", "fox-news-media-bias", ("www.foxnews.com", "foxnews.com"),
        "https://moxie.foxnews.com/google-publisher/world.xml",
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.DAILY_CALLER.value, "The Daily Caller", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Lean Right", "daily-caller-media-bias", ("dailycaller.com", "www.dailycaller.com"),
        "https://dailycaller.com/feed/",
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.BREITBART.value, "Breitbart", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Right", "breitbart-news-media-bias", ("www.breitbart.com", "breitbart.com"),
        "https://www.breitbart.com/feed/", ("feeds.feedburner.com",),
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.NEW_YORK_POST.value, "New York Post news", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Right", "new-york-post-news-media-bias", ("nypost.com", "www.nypost.com"),
        "https://nypost.com/world-news/feed/",
    ),
    _configure_outlet(
        SOURCE_CONSTANTS.outlet_ids.EXAMINER.value, "Washington Examiner", SOURCE_CONSTANTS.groups.CONSERVATIVE,
        "Lean Right", "washington-examiner-media-bias",
        ("www.washingtonexaminer.com", "washingtonexaminer.com"),
        "https://www.washingtonexaminer.com/feed/",
    ),
)
