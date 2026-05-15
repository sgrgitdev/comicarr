"""
Unit tests for manga search query construction in comicarr/search.py.

Tests cover _build_manga_search_terms() which generates NZB/torrent-provider
query variations for manga chapters and volumes.
"""

from unittest.mock import patch

import pytest


# Patch the logger so _build_manga_search_terms can be imported without
# initializing the full comicarr application.
@pytest.fixture(autouse=True)
def _mock_logger():
    with patch("comicarr.search.logger") as mock_log:
        mock_log.fdebug = lambda *a, **kw: None
        yield mock_log


def _build():
    from comicarr.search import _build_manga_search_terms

    return _build_manga_search_terms


def _local_host_check():
    from comicarr.search import _is_local_indexer_host

    return _is_local_indexer_host


def _comic_bases():
    from comicarr.search import _build_comic_search_bases

    return _build_comic_search_bases


def _collected_searches():
    from comicarr.search import _build_collected_volume_searches

    return _build_collected_volume_searches


def _generate_id():
    from comicarr.search import generate_id

    return generate_id


class TestLocalIndexerHost:
    def test_host_docker_internal_is_local(self):
        is_local = _local_host_check()
        assert is_local("http://host.docker.internal:9696/1/api") is True

    def test_private_lan_host_is_local(self):
        is_local = _local_host_check()
        assert is_local("http://192.168.68.247:9696/1/api") is True

    def test_public_host_is_not_local(self):
        is_local = _local_host_check()
        assert is_local("https://example.com/api") is False


class TestBuildComicSearchBases:
    def test_keeps_original_title_before_article_stripped_fallback(self):
        build = _comic_bases()
        bases = build("The Ultimates", None, "6", "Print")

        assert bases[0] == "the%20ultimates"
        assert "ultimates" in bases

    def test_adds_default_volume_one_variants_for_issue_searches(self):
        build = _comic_bases()
        bases = build("The Ultimates", None, "6", "Print")

        assert "the%20ultimates%20vol%201" in bases
        assert "the%20ultimates%20v1" in bases

    def test_uses_explicit_comic_version_when_present(self):
        build = _comic_bases()
        bases = build("Some Series", "3", "12", "Print")

        assert "some%20series%20vol%203" in bases
        assert "some%20series%20v3" in bases

    def test_does_not_add_comic_volume_variants_for_manga(self):
        build = _comic_bases()
        bases = build("One Piece", None, "1044", "manga")

        assert bases == ["one%20piece"]


class TestBuildCollectedVolumeSearches:
    def test_adds_likely_collected_volume_queries_for_issue_six(self):
        build = _collected_searches()
        searches = build("The Power Fantasy", "6", "Print")

        assert "the%20power%20fantasy%20vol%2002" in searches
        assert "the%20power%20fantasy%20vol%202" in searches
        assert "the%20power%20fantasy%20v02" in searches
        assert "power%20fantasy%20vol%2002" in searches

    def test_skips_manga(self):
        build = _collected_searches()

        assert build("One Piece", "1044", "manga") == []


class TestGenerateProviderId:
    def test_newznab_prowlarr_download_uses_link_token_not_download_path(self):
        generate_id = _generate_id()
        provider = {"type": "newznab"}
        link = (
            "http://host.docker.internal:9696/1/download?"
            "apikey=redacted&link=provider-guid-token&file=The.Ultimates.006"
        )

        assert generate_id(provider, link, "The Ultimates") == "provider-guid-token"

    def test_newznab_prowlarr_download_can_fall_back_to_file_title(self):
        generate_id = _generate_id()
        provider = {"type": "newznab"}
        link = "http://host.docker.internal:9696/1/download?apikey=redacted&file=The.Ultimates.006"

        assert generate_id(provider, link, "The Ultimates") == "The.Ultimates.006"


class TestBuildMangaSearchTermsChapterOnly:
    """When only a chapter number is provided (no volume)."""

    def test_integer_chapter(self):
        build = _build()
        terms = build("One Piece", "1044", None)
        assert '"One Piece" c1044' not in terms  # not quoted — raw name
        assert "One Piece 1044" in terms
        assert "One Piece c1044" in terms
        assert "One Piece chapter 1044" in terms

    def test_single_digit_chapter_is_zero_padded(self):
        build = _build()
        terms = build("Naruto", "5", None)
        assert "Naruto 5" in terms
        assert "Naruto c005" in terms
        assert "Naruto c5" in terms
        assert "Naruto chapter 005" in terms

    def test_two_digit_chapter_is_zero_padded(self):
        build = _build()
        terms = build("Bleach", "42", None)
        assert "Bleach c042" in terms
        assert "Bleach chapter 042" in terms

    def test_three_digit_chapter_no_extra_padding(self):
        build = _build()
        terms = build("Dragon Ball", "100", None)
        assert "Dragon Ball c100" in terms
        assert "Dragon Ball chapter 100" in terms

    def test_decimal_chapter(self):
        build = _build()
        terms = build("Chainsaw Man", "10.5", None)
        # Decimal chapters get formatted as e.g. "0010.5"
        assert any("c" in t and "10.5" in t for t in terms)
        assert any("chapter" in t and "10.5" in t for t in terms)

    def test_no_volume_term_when_volume_is_none(self):
        build = _build()
        terms = build("Naruto", "700", None)
        assert not any("v" in t.split()[-1] for t in terms if "c" not in t.split()[-1])


class TestBuildMangaSearchTermsVolumeOnly:
    """When only a volume number is provided (no chapter)."""

    def test_single_digit_volume(self):
        build = _build()
        terms = build("Bleach", None, "1")
        assert "Bleach v01" in terms

    def test_two_digit_volume(self):
        build = _build()
        terms = build("One Piece", None, "103")
        assert "One Piece v103" in terms

    def test_no_chapter_terms_when_chapter_is_none(self):
        build = _build()
        terms = build("Bleach", None, "5")
        assert not any("chapter" in t for t in terms)
        assert not any(" c0" in t or " c1" in t for t in terms)


class TestBuildMangaSearchTermsCombined:
    """When both chapter and volume are provided."""

    def test_combined_term_is_first(self):
        build = _build()
        terms = build("One Piece", "1044", "103")
        # Combined should be first (most specific)
        assert terms[0] == "One Piece v103c1044"

    def test_all_variations_present(self):
        build = _build()
        terms = build("One Piece", "1044", "103")
        assert "One Piece v103c1044" in terms
        assert "One Piece c1044" in terms
        assert "One Piece chapter 1044" in terms
        assert "One Piece v103" in terms

    def test_combined_zero_padding(self):
        build = _build()
        terms = build("Naruto", "5", "2")
        assert "Naruto v02c005" in terms
        assert "Naruto c005" in terms
        assert "Naruto v02" in terms


class TestBuildMangaSearchTermsEdgeCases:
    """Edge cases and error handling."""

    def test_empty_series_name_returns_empty(self):
        build = _build()
        assert build("", "1", "1") == []

    def test_none_series_name_returns_empty(self):
        build = _build()
        assert build(None, "1", "1") == []

    def test_both_none_returns_empty(self):
        build = _build()
        assert build("Test", None, None) == []

    def test_whitespace_stripped_from_name(self):
        build = _build()
        terms = build("  One Piece  ", "1", None)
        assert "One Piece c001" in terms

    def test_non_numeric_chapter_used_as_string(self):
        build = _build()
        terms = build("Test Series", "Special", None)
        assert any("cSpecial" in t for t in terms)

    def test_non_numeric_volume_used_as_string(self):
        build = _build()
        terms = build("Test Series", None, "TBD")
        assert any("vTBD" in t for t in terms)

    def test_chapter_zero(self):
        build = _build()
        terms = build("Test", "0", None)
        assert "Test c000" in terms
        assert "Test chapter 000" in terms

    def test_large_chapter_number(self):
        build = _build()
        terms = build("Test", "1500", None)
        assert "Test c1500" in terms

    def test_priority_order(self):
        """Combined terms should come before individual terms."""
        build = _build()
        terms = build("Series", "10", "5")
        combined_idx = terms.index("Series v05c010")
        chapter_idx = terms.index("Series c010")
        volume_idx = terms.index("Series v05")
        assert combined_idx < chapter_idx
        assert combined_idx < volume_idx

    def test_colon_title_generates_aliases(self):
        build = _build()
        terms = build("Demon Slayer: Kimetsu no Yaiba", "244", None)
        assert "Demon Slayer: Kimetsu no Yaiba 244" in terms
        assert "Demon Slayer Kimetsu no Yaiba 244" in terms
        assert "Demon Slayer 244" in terms
        assert "Kimetsu no Yaiba 244" in terms
