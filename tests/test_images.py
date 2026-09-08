"""AC3 -- HTTP HEAD image verification, site-chrome exclusion, reuse flag."""
from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from gunpla_official_news import images as I


class FakeResponse:
    def __init__(self, status, content_type):
        self.status = status
        self.headers = {"Content-Type": content_type}

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_opener(table, log=None):
    """Return a mock opener plus the request log it appends to."""

    def _open(request: urllib.request.Request):
        assert request.get_method() == "HEAD", "image verification must use HTTP HEAD"
        url = request.full_url
        if log is not None:
            log.append(url)
        if url not in table:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        status, ctype = table[url]
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "error", {}, None)
        return FakeResponse(status, ctype)

    return _open


OK_JPG = "https://en.gundam-official.com/media/kit-01.jpg"
OK_PNG = "https://en.gundam-official.com/media/kit-02.png"
NOT_IMAGE = "https://en.gundam-official.com/media/gallery.html"
GONE = "https://en.gundam-official.com/media/missing.jpg"
CHROME = "https://en.gundam-official.com/media/resized_Rectangle_1180.png"

TABLE = {
    OK_JPG: (200, "image/jpeg"),
    OK_PNG: (200, "image/png"),
    NOT_IMAGE: (200, "text/html; charset=utf-8"),
    GONE: (404, "image/jpeg"),
    CHROME: (200, "image/png"),
}


# ---------------------------------------------------------------------------
# HEAD semantics
# ---------------------------------------------------------------------------


def test_head_uses_the_head_method_and_reports_status_and_type():
    result = I.head(OK_JPG, opener=make_opener(TABLE))
    assert result.status == 200
    assert result.content_type == "image/jpeg"
    assert result.ok is True


def test_verified_only_on_200_plus_image_content_type():
    opener = make_opener(TABLE)
    assert I.verify_image(OK_JPG, opener=opener) is True
    assert I.verify_image(OK_PNG, opener=opener) is True
    # 200 but not an image
    assert I.verify_image(NOT_IMAGE, opener=opener) is False
    # image/* but not 200
    assert I.verify_image(GONE, opener=opener) is False
    # unknown host -> 404
    assert I.verify_image("https://nope.example/media/x.jpg", opener=opener) is False


def test_content_type_parameters_are_tolerated():
    assert I.is_image_content_type("image/jpeg") is True
    assert I.is_image_content_type("IMAGE/PNG; charset=binary") is True
    assert I.is_image_content_type("text/html") is False
    assert I.is_image_content_type("") is False
    # "imagexml" must not squeak through a prefix check
    assert I.is_image_content_type("imagex/weird") is False


def test_network_failure_degrades_instead_of_raising():
    def boom(request):
        raise OSError("connection reset")

    result = I.head(OK_JPG, opener=boom)
    assert result.ok is False
    assert result.status is None
    assert "connection reset" in result.error


def test_default_opener_is_urllib_head_not_a_stub():
    """The production path must be a real HTTP HEAD, not a mock."""
    import inspect

    src = inspect.getsource(I._default_opener)
    assert "urllib.request.urlopen" in src
    req_src = inspect.getsource(I.head)
    assert 'method="HEAD"' in req_src


# ---------------------------------------------------------------------------
# Site chrome
# ---------------------------------------------------------------------------


def test_site_chrome_is_recognised_by_filename():
    assert I.is_site_chrome(CHROME) is True
    assert I.is_site_chrome("https://x.example/a/resized_Rectangle_7.jpg") is True
    assert I.is_site_chrome(OK_JPG) is False
    assert I.is_site_chrome("") is False


def test_site_chrome_is_excluded_without_ever_issuing_a_request():
    log = []
    result = I.verify_images([CHROME, OK_JPG], opener=make_opener(TABLE, log))
    assert result.excluded_chrome == [CHROME]
    assert result.verified == [OK_JPG]
    assert CHROME not in log, "site chrome must be dropped before the HEAD request"


def test_chrome_named_file_is_never_verified_even_if_it_would_200():
    assert I.verify_image(CHROME, opener=make_opener(TABLE)) is False


# ---------------------------------------------------------------------------
# Reuse policy
# ---------------------------------------------------------------------------


def test_reuse_prohibited_notice_is_detected():
    footer = "*Note: Reproduction of content and images is strictly prohibited."
    assert I.has_reuse_prohibited_notice(footer) is True
    # case- and whitespace-insensitive
    assert I.has_reuse_prohibited_notice(
        "reproduction   of content\nand images is  STRICTLY prohibited"
    ) is True
    assert I.has_reuse_prohibited_notice("(c) 2026 Example") is False
    assert I.has_reuse_prohibited_notice("") is False


def test_reuse_not_permitted_is_flagged_on_the_result():
    footer = "Reproduction of content and images is strictly prohibited."
    result = I.verify_images([OK_JPG], page_text=footer, opener=make_opener(TABLE))
    assert result.reuse_not_permitted is True
    assert result.flags == ["reuse_not_permitted"]
    assert I.REUSE_NOT_PERMITTED == "reuse_not_permitted"


def test_verification_success_does_not_imply_reuse_permission():
    """ARCHITECTURE.md section 10: existence != redistribution rights."""
    result = I.verify_images(
        [OK_JPG],
        page_text="Reproduction of content and images is strictly prohibited.",
        opener=make_opener(TABLE),
    )
    assert result.image_checked is True
    assert result.reuse_not_permitted is True


# ---------------------------------------------------------------------------
# Batch behaviour
# ---------------------------------------------------------------------------


def test_image_checked_is_false_when_nothing_verifies():
    result = I.verify_images([GONE, NOT_IMAGE, CHROME], opener=make_opener(TABLE))
    assert result.image_checked is False
    assert result.verified == []
    assert sorted(result.failed) == sorted([GONE, NOT_IMAGE])
    assert result.excluded_chrome == [CHROME]


def test_top_pads_to_three_slots():
    result = I.verify_images([OK_JPG], opener=make_opener(TABLE))
    assert result.top(3) == [OK_JPG, "", ""]


def test_extract_image_urls_keeps_media_paths_in_document_order():
    html = (
        '<img src="%s"><img src="%s">'
        '<img src="https://cdn.example/logo.svg">'
        '<a href="%s">gallery</a><img src="%s">' % (CHROME, OK_JPG, NOT_IMAGE, OK_JPG)
    )
    urls = I.extract_image_urls(html)
    assert urls == [CHROME, OK_JPG, NOT_IMAGE]  # de-duplicated, non-/media/ dropped


@pytest.mark.parametrize("bad", ["", None])
def test_extract_image_urls_handles_empty_input(bad):
    assert I.extract_image_urls(bad) == []
