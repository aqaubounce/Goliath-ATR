import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ratings_hub.collector import (
    AcquiredRatingsHubHTML,
    ChallengeResponseError,
    CollectorError,
    acquire_ratings_hub_html,
    describe_source,
    fetch_url,
    is_ratings_hub_html,
    load_webarchive_html,
    load_html_file,
    save_html,
)


VALID_RATINGS_HUB_HTML = """<!doctype html>
<html><head><title>ATR Ratings Hub</title></head><body>
<table><thead><tr>
<th>No. &amp; Horsename</th><th>Official Rating</th>
<th>Last Winning Rating</th><th>Speed</th><th>Form</th>
<th>Scope</th><th>Conditions</th><th>Trainer Attribute</th>
<th>Jockey Attribute</th><th>Attitude</th><th>Form Plus</th>
</tr></thead><tbody><tr><td>1 &amp; Runner</td><td>80</td>
<td>78</td><td>75</td><td>82</td><td>70</td><td>73</td>
<td>66</td><td>68</td><td>72</td><td>85</td></tr></tbody></table>
</body></html>"""

CLIENT_CHALLENGE_HTML = """<!doctype html>
<html><head><title>Client Challenge</title></head><body>
JavaScript is disabled in your browser. Please enable JavaScript to proceed.
</body></html>"""

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CURRENT_WEBARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "ratings_hub"
    / "Ratings Hub | Tips and Analysis | At The Races 3.webarchive"
)


class RatingsHubCollectorTests(unittest.TestCase):
    def test_loads_local_html_file_without_newline_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "saved.html"
            path.write_bytes(b"<html>\r\n<body>Saved</body>\r\n</html>")

            self.assertEqual(
                load_html_file(path), "<html>\r\n<body>Saved</body>\r\n</html>"
            )

    def test_saves_html_and_creates_parent_directories(self) -> None:
        html = "<html>\r\n<body>Exact &amp; unchanged</body>\r\n</html>"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "saved.html"

            saved_path = save_html(html, path)

            self.assertEqual(saved_path, path)
            self.assertEqual(path.read_bytes(), html.encode("utf-8"))

    def test_recognises_ratings_hub_table_using_multiple_markers(self) -> None:
        self.assertTrue(is_ratings_hub_html(VALID_RATINGS_HUB_HTML))

    def test_fetches_genuine_live_ratings_hub_html_unchanged(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = VALID_RATINGS_HUB_HTML.encode("utf-8")

        with patch("src.ratings_hub.collector.urlopen", return_value=response):
            acquired = acquire_ratings_hub_html()

        self.assertEqual(
            acquired,
            AcquiredRatingsHubHTML(
                VALID_RATINGS_HUB_HTML,
                "html",
                "https://www.attheraces.com/tips/atr-tipsters/ratings-hub",
            ),
        )

    def test_rejects_client_challenge_response(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = CLIENT_CHALLENGE_HTML.encode("utf-8")

        with patch("src.ratings_hub.collector.urlopen", return_value=response):
            with self.assertRaisesRegex(CollectorError, "client or security challenge"):
                fetch_url("https://example.test/ratings")

    def test_challenge_without_archive_is_not_bypassed(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = CLIENT_CHALLENGE_HTML.encode("utf-8")

        with patch("src.ratings_hub.collector.urlopen", return_value=response):
            with self.assertRaises(ChallengeResponseError):
                acquire_ratings_hub_html()

    def test_challenge_falls_back_to_synthetic_webarchive_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fallback.webarchive"
            path.write_bytes(plistlib.dumps({
                "WebMainResource": {
                    "WebResourceData": VALID_RATINGS_HUB_HTML.encode("utf-8"),
                    "WebResourceMIMEType": "text/html",
                    "WebResourceTextEncodingName": "UTF-8",
                    "WebResourceURL": "https://www.attheraces.com/tips/atr-tipsters/ratings-hub",
                },
            }))
            with patch(
                "src.ratings_hub.collector.fetch_url",
                side_effect=ChallengeResponseError("client or security challenge"),
            ):
                acquired = acquire_ratings_hub_html(webarchive_path=path)

        self.assertEqual(acquired.source_format, "webarchive")
        self.assertEqual(acquired.html, VALID_RATINGS_HUB_HTML)

    @unittest.skipUnless(CURRENT_WEBARCHIVE.is_file(), "current raw WebArchive is not present")
    def test_challenge_falls_back_to_real_webarchive_main_resource_unchanged(self) -> None:
        raw_archive = CURRENT_WEBARCHIVE.read_bytes()
        resource = plistlib.loads(raw_archive)["WebMainResource"]
        expected_html = resource["WebResourceData"].decode(
            resource["WebResourceTextEncodingName"]
        )
        with patch(
            "src.ratings_hub.collector.fetch_url",
            side_effect=ChallengeResponseError("client or security challenge"),
        ):
            acquired = acquire_ratings_hub_html(webarchive_path=CURRENT_WEBARCHIVE)

        self.assertEqual(acquired.source_format, "webarchive")
        self.assertEqual(acquired.source_url, resource["WebResourceURL"])
        self.assertEqual(acquired.html, expected_html)
        self.assertTrue(is_ratings_hub_html(acquired.html))

    def test_rejects_non_ratings_hub_webarchive_main_resource(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unrelated.webarchive"
            path.write_bytes(plistlib.dumps({
                "WebMainResource": {
                    "WebResourceData": b"<html>unrelated</html>",
                    "WebResourceMIMEType": "text/html",
                    "WebResourceTextEncodingName": "UTF-8",
                    "WebResourceURL": "https://www.attheraces.com/tips/atr-tipsters/ratings-hub",
                },
            }))

            with self.assertRaisesRegex(CollectorError, "does not contain a Ratings Hub table"):
                load_webarchive_html(path)

    def test_rejects_arbitrary_html(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b"<html><body>Unrelated page</body></html>"

        with patch("src.ratings_hub.collector.urlopen", return_value=response):
            with self.assertRaisesRegex(CollectorError, "does not contain a Ratings Hub table"):
                fetch_url("https://example.test/ratings")

    def test_describes_title_counts_and_markers(self) -> None:
        description = describe_source(VALID_RATINGS_HUB_HTML)

        self.assertEqual(description["page_title"], "ATR Ratings Hub")
        self.assertEqual(description["character_count"], len(VALID_RATINGS_HUB_HTML))
        self.assertEqual(description["byte_count"], len(VALID_RATINGS_HUB_HTML.encode("utf-8")))
        self.assertTrue(description["has_ratings_hub_markers"])
        self.assertTrue(description["has_table_markup"])
        self.assertIsNone(description["http_status"])


if __name__ == "__main__":
    unittest.main()