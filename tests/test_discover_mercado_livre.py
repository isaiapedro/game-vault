import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from scripts.discover_mercado_livre import discover, write_report


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class MercadoLivreDiscoveryTests(unittest.TestCase):
  def test_candidates_are_unreviewed_and_token_is_not_persisted(self):
    requests = []
    delays = []

    def opener(request, timeout):
        requests.append(request)
        return Response(json.dumps({"results": [{
            "id": "MLB1", "title": "Sample PS3", "price": 50,
            "currency_id": "BRL", "permalink": "https://example.invalid/listing",
            "condition": "used", "seller": {"email": "private@example.invalid"},
        }]}).encode())

    report = discover(["Sample", "Second"], "secret-token", opener=opener, sleeper=delays.append)
    self.assertEqual(len(requests), 2)
    self.assertEqual(requests[0].get_header("Authorization"), "Bearer secret-token")
    self.assertEqual(delays, [1.2])
    self.assertEqual(report["status"], "unreviewed_candidates")
    self.assertTrue(report["entries"][0]["candidates"][0]["platform_mentioned"])
    self.assertNotIn("secret-token", json.dumps(report))
    self.assertNotIn("private@example.invalid", json.dumps(report))


  def test_source_error_is_recorded_without_leaking_body(self):
    def opener(*_args, **_kwargs):
        raise HTTPError("https://example.invalid", 403, "secret body", {}, None)

    report = discover(["Sample"], "secret-token", opener=opener)
    self.assertEqual(report["entries"][0]["error"], "http_403")
    self.assertNotIn("secret body", json.dumps(report))


  def test_report_must_stay_under_local(self):
    with tempfile.TemporaryDirectory() as directory:
      with self.assertRaises(ValueError):
        write_report({"version": 1}, Path(directory) / "report.json")


if __name__ == "__main__":
    unittest.main()
