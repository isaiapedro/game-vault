import unittest

from src.api.serve import validated_bind_host


class LanBindTests(unittest.TestCase):
    def test_loopback_and_private_lan_addresses_are_allowed(self):
        for address in ("127.0.0.1", "192.168.1.16", "10.0.0.4", "172.16.1.9"):
            self.assertEqual(validated_bind_host(address), address)

    def test_wildcard_public_and_nonliteral_hosts_are_rejected(self):
        for address in ("0.0.0.0", "8.8.8.8", "127.0.0.2", "169.254.1.1",
                        "localhost", "::1", "192.168.1.16:4200"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                validated_bind_host(address)


if __name__ == "__main__":
    unittest.main()
