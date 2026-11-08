"""Fetch bounded public HTTPS documents from explicitly permitted hosts.

Every redirect is validated before connecting. DNS answers must be public, and
the TLS socket connects to a checked IP with the publisher hostname as SNI; this
avoids a second DNS lookup changing the destination after validation."""

import ssl
import time
import socket
import ipaddress
import http.client

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from backend.sources.constants import SOURCE_CONSTANTS, SourceAccessStatus


@dataclass(frozen=True)
class SourceLimits:
    """Bound one source operation; application-wide budgets remain with the caller."""

    timeout_seconds: float = 10.0
    max_response_bytes: int = 2_000_000
    max_redirects: int = 3
    max_retries: int = 1
    minimum_article_words: int = 100
    max_results_per_outlet: int = 10
    max_archive_pages: int = 4
    duplicate_similarity: float = 0.85

    def __post_init__(self) -> None:
        """Reject limits that would disable bounds or create invalid reads."""
        if (
            self.timeout_seconds <= 0 or self.max_response_bytes < 1
            or self.max_redirects < 0 or self.max_retries < 0
            or self.minimum_article_words < 1 or self.max_results_per_outlet < 1
            or self.max_archive_pages < 1 or not 0 < self.duplicate_similarity <= 1
        ):
            raise ValueError("Source limits must be positive; retry counts may be zero.")


@dataclass(frozen=True)
class FetchedDocument:
    """Carry a successful bounded response without retaining a live connection."""

    url: str
    body: bytes
    content_type: str
    status: int = 200


class SourceAccessError(Exception):
    """Carry a safe source failure category and optional publisher HTTP status."""

    def __init__(
        self,
        status: SourceAccessStatus,
        detail: str,
        http_status: int | None = None,
    ) -> None:
        """Store diagnostics that are safe for an agent-visible access outcome."""
        super().__init__(detail)
        self.status: SourceAccessStatus = status
        self.http_status: int | None = http_status


def validate_source_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    """Allow only plain HTTPS URLs on exact configured hosts and the default port."""
    try:
        parsed = urlsplit(url)
        permitted: bool = (
            parsed.scheme == "https" and parsed.hostname in allowed_hosts
            and parsed.port in (None, 443)
            and parsed.username is None and parsed.password is None
            and not any(character.isspace() for character in url)
        )
    except ValueError:
        permitted = False
    if not permitted:
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.ACCESS_DENIED,
            "URL is outside the assigned source hosts or uses an unsafe format.",
        )
    return urlunsplit(parsed._replace(fragment=""))


def fetch_document(
    url: str,
    allowed_hosts: tuple[str, ...],
    limits: SourceLimits,
) -> FetchedDocument:
    """Fetch within one deadline, retrying only transient failures and safe redirects."""
    deadline: float = time.monotonic() + limits.timeout_seconds
    attempt: int
    for attempt in range(limits.max_retries + 1):
        try:
            return _fetch_redirects(url, allowed_hosts, limits, deadline)
        except SourceAccessError as error:
            retryable: bool = error.http_status in (429, 500, 502, 503, 504)
            if not retryable or attempt == limits.max_retries:
                raise
        except (OSError, http.client.HTTPException, TimeoutError):
            if attempt == limits.max_retries:
                break
        if time.monotonic() >= deadline:
            break
    raise SourceAccessError(
        SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
        "Source could not be fetched within its timeout and retry limits.",
    )


def _fetch_redirects(
    url: str,
    allowed_hosts: tuple[str, ...],
    limits: SourceLimits,
    deadline: float,
) -> FetchedDocument:
    """Connect to validated public IPs and check each redirect before following it."""
    current: str = url
    redirect_count: int
    for redirect_count in range(limits.max_redirects + 1):
        current = validate_source_url(current, allowed_hosts)
        parsed = urlsplit(current)
        hostname: str = parsed.hostname or ""
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_global for address in addresses
        ):
            raise SourceAccessError(
                SOURCE_CONSTANTS.access_statuses.ACCESS_DENIED,
                "Source resolves to a non-public network address.",
            )
        remaining: float = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        connection: http.client.HTTPSConnection = http.client.HTTPSConnection(
            hostname, timeout=remaining,
        )
        try:
            raw_socket: socket.socket = socket.create_connection(
                (addresses[0][4][0], 443), timeout=remaining,
            )
            try:
                connection.sock = ssl.create_default_context().wrap_socket(
                    raw_socket, server_hostname=hostname,
                )
            except BaseException:
                raw_socket.close()
                raise
            target: str = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request("GET", target, headers={"User-Agent": "Gerry/0.1"})
            response: http.client.HTTPResponse = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location: str | None = response.getheader("Location")
                if location is None or redirect_count == limits.max_redirects:
                    raise SourceAccessError(
                        SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
                        "Source redirect limit reached or redirect target missing.",
                    )
                current = urljoin(current, location)
                continue
            if response.status >= 400:
                raise SourceAccessError(
                    SOURCE_CONSTANTS.access_statuses.ACCESS_DENIED
                    if response.status in (401, 403) else
                    SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
                    "Publisher returned an unsuccessful HTTP response.",
                    response.status,
                )
            if response.status != 200:
                raise SourceAccessError(
                    SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
                    "Publisher returned an unsupported response.", response.status,
                )
            chunks: list[bytes] = []
            size: int = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk: bytes = response.read1(min(65536, limits.max_response_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limits.max_response_bytes:
                    raise SourceAccessError(
                        SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
                        "Source response exceeded the configured size limit.",
                    )
            return FetchedDocument(
                current, b"".join(chunks),
                response.getheader("Content-Type", ""), response.status,
            )
        finally:
            connection.close()
    raise AssertionError("Redirect loop must return or raise within its bound.")
