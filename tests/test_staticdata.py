"""
    Tests for the static data endpoints
"""
import json
import unittest
from unittest import mock

from drift.test_helpers.systesthelper import setup_tenant, remove_tenant
from drift.utils import get_config

from driftbase.systesthelper import DriftBaseTestCase


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class CfgTest(DriftBaseTestCase):
    """
    Tests for the /static-data endpoint
    """

    def test_get_static_data(self):
        self.auth()
        endpoint = self.endpoints.get('static_data')
        self.assertIsNotNone(endpoint, "'static_data' endpoint not registered.")

        # Fudge the config a bit
        get_config().tenant["staticdata"] = {
            "repository": "borko-games/the-ossomizer",
            "revision": "refs/heads/developmegood",
        }
        cdn_index_root = "s3://directive-tiers.dg-api.com/static-data/"
        cdn_data_root = "https://static-data.dg-api.com/"
        cdn_list = [("s3", cdn_data_root)]
        get_config().tier["staticdata"] = {
            "index_root": cdn_index_root,
            "cdn_list": cdn_list,
        }

        ref1 = {"commit_id": "abcd", "ref": "refs/heads/developmegood"}
        ref2 = {"commit_id": "c0ffee", "ref": "refs/tags/v0.1.4"}

        with mock.patch('driftbase.api.staticdata.S3Client') as client:
            s3 = client.return_value
            body = mock.Mock()
            s3.get_object.return_value = {"Body": body}
            body.read.return_value = json.dumps({"index": [ref1, ref2]}).encode('utf-8')
            resp = self.get(endpoint).json()

            # There should be at least one entry in the static_data_urls pointing to developmegood
            urls = resp.get("static_data_urls")
            self.assertIsNotNone(urls, "The 'static_data_urls' key is missing")
            self.assertTrue(len(urls) > 0, "There should be at least one entry in 'static_data_urls'.")
            self.assertEqual(urls[0]["cdn_list"][0]["data_root_url"],
                             u"{}{}/data/{}/".format(cdn_data_root, "borko-games/the-ossomizer", "abcd"))
            self.assertEqual(urls[0]["origin"], "Tenant config")
            self.assertEqual(urls[0]["commit_id"], ref1["commit_id"], "I should have gotten the default ref.")

            # Now we test the pin thing, first without the server set to honor it.
            resp = self.get(endpoint + "?static_data_ref=refs/tags/v0.1.4").json()
            # There should be at least one entry in the static_data_urls pointing to developmegood
            urls = resp.get("static_data_urls")
            self.assertIsNotNone(urls, "The 'static_data_urls' key is missing")
            self.assertTrue(len(urls) > 0, "There should be at least one entry in 'static_data_urls'.")
            self.assertEqual(urls[0]["origin"], "Tenant config")
            self.assertEqual(urls[0]["commit_id"], ref1["commit_id"], "I should have gotten the default ref.")

            # Turn on pin feature
            get_config().tenant["staticdata"]["allow_client_pin"] = True
            resp = self.get(endpoint + "?static_data_ref=refs/tags/v0.1.4").json()
            urls = resp.get("static_data_urls")
            self.assertEqual(urls[0]["origin"], "Client pin")
            self.assertEqual(urls[0]["commit_id"], ref2["commit_id"], "I should have gotten the pinned ref.")

            # Test cdn list
            test_root = 'http://test-cdn.com/the/root'
            cdn_list.append(['test-cdn', test_root])
            resp = self.get(endpoint).json()
            urls = resp.get('static_data_urls')
            cdns = {cdn_entry['cdn']: cdn_entry['data_root_url'] for cdn_entry in urls[0]['cdn_list']}
            self.assertIn('test-cdn', cdns)
            self.assertTrue(cdns['test-cdn'].startswith(test_root))
            # Make sure the cdn entry matches the master url
            test_url_tail = cdns['test-cdn'].replace(test_root, '')
            self.assertTrue(urls[0]['data_root_url'].endswith(test_url_tail))


if __name__ == '__main__':
    unittest.main()
