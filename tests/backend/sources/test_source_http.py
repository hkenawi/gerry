"""Verify source-fetch restrictions at the external network boundary.

Socket and TLS fakes replace external I/O while real host, address, redirect,
response-size, and retry policies are exercised without internet access."""

import pytest
import socket

from unittest.mock import Mock, patch

from backend.sources.access.http import (
    SourceLimits,
    SourceAccessError,
    fetch_document,
    validate_source_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.npr.org/story",
        "https://www.npr.org.evil.example/story",
        "https://www.npr.org@127.0.0.1/story",
        "https://www.npr.org:8443/story",
        "https://user:password@www.npr.org/story",
        "https://127.0.0.1/story",
    ],
)
def test_only_exact_assigned_https_hosts_are_permitted(url: str) -> None:
    """Reject host tricks, credentials, cleartext, IP literals, and custom ports."""
    with pytest.raises(SourceAccessError):
        validate_source_url(url, ("www.npr.org",))


def test_publication_host_resolving_to_private_ip_is_rejected() -> None:
    """Reject private destinations before any socket connection is attempted."""
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    with patch("socket.getaddrinfo", return_value=addresses):
        with patch("socket.create_connection") as connect:
            with pytest.raises(SourceAccessError):
                fetch_document("https://www.npr.org/story", ("www.npr.org",), SourceLimits())
            connect.assert_not_called()


def test_redirect_to_an_unapproved_host_is_never_connected() -> None:
    """Validate a publisher redirect before opening a socket to its destination."""
    response: Mock = Mock()
    response.status = 302
    response.getheader.return_value = "https://127.0.0.1/private"
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with (
        patch("socket.getaddrinfo", return_value=addresses),
        patch("socket.create_connection"),
        patch("ssl.create_default_context"),
        patch("http.client.HTTPSConnection") as connection,
    ):
        connection.return_value.getresponse.return_value = response
        with pytest.raises(SourceAccessError):
            fetch_document("https://www.npr.org/story", ("www.npr.org",), SourceLimits())
        assert connection.call_count == 1


def test_response_size_limit_is_enforced_while_reading() -> None:
    """Stop a source response that exceeds the byte ceiling before extraction."""
    response: Mock = Mock()
    response.status = 200
    response.read1.return_value = b"oversized"
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with (
        patch("socket.getaddrinfo", return_value=addresses),
        patch("socket.create_connection"),
        patch("ssl.create_default_context"),
        patch("http.client.HTTPSConnection") as connection,
    ):
        connection.return_value.getresponse.return_value = response
        with pytest.raises(SourceAccessError):
            fetch_document(
                "https://www.npr.org/story", ("www.npr.org",),
                SourceLimits(max_response_bytes=8),
            )


def test_transient_failure_is_retried_within_the_same_fetch_operation() -> None:
    """Recover a transient publisher failure without unbounded retries."""
    unavailable: Mock = Mock()
    unavailable.status = 503
    success: Mock = Mock()
    success.status = 200
    success.read1.side_effect = [b"body", b""]
    success.getheader.return_value = "text/html"
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with (
        patch("socket.getaddrinfo", return_value=addresses),
        patch("socket.create_connection"),
        patch("ssl.create_default_context"),
        patch("http.client.HTTPSConnection") as connection,
    ):
        connection.return_value.getresponse.side_effect = [unavailable, success]
        result = fetch_document(
            "https://www.npr.org/story", ("www.npr.org",), SourceLimits(),
        )
    assert result.body == b"body"
    assert connection.call_count == 2
