"""A first run against a real model fails in a few predictable ways. Each says what to do."""

from __future__ import annotations

import pytest

from overturn.eval.__main__ import _credentials_hint


class FakeClientError(Exception):
    """Stands in for botocore's ClientError, which is not imported in tests."""


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("An error occurred (UnrecognizedClientException) calling ConverseStream", "credentials"),
        ("An error occurred (AccessDeniedException) calling ConverseStream", "verified"),
        ("An error occurred (ResourceNotFoundException) calling ConverseStream", "region"),
        ("An error occurred (ThrottlingException) calling ConverseStream", "throttling"),
    ],
)
def test_a_setup_failure_is_explained_rather_than_dumped(message, expected):
    hint = _credentials_hint(FakeClientError(message))
    assert hint is not None
    assert expected in hint.lower()
    assert message[:40] in hint  # the original error is still shown, not swallowed


def test_an_unexpected_error_is_not_disguised_as_a_setup_problem():
    assert _credentials_hint(ValueError("something else went wrong")) is None
