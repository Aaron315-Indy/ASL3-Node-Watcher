import unittest
from node_watcher import parse_links, transitions


class WatcherTests(unittest.TestCase):

    def test_parse_links(self):
        output = (
            "520359 1 2 ESTABLISHED\n"
            "662640 1 2 ESTABLISHED\n"
        )
        self.assertEqual(
            parse_links(output, "658860"),
            {"520359", "662640"}
        )

    def test_ignore_local(self):
        output = (
            "658860 1 2 ESTABLISHED\n"
            "520359 1 2 ESTABLISHED\n"
        )
        self.assertEqual(
            parse_links(output, "658860"),
            {"520359"}
        )

    def test_ignore_non_established(self):
        output = (
            "520359 1 2 ESTABLISHED\n"
            "662640 1 2 CONNECTING\n"
        )
        self.assertEqual(
            parse_links(output, "658860"),
            {"520359"}
        )

    def test_multiple_links(self):
        output = (
            "3807988 1 2 ESTABLISHED\n"
            "520359 1 2 ESTABLISHED\n"
            "683810 1 2 ESTABLISHED\n"
        )
        self.assertEqual(
            parse_links(output, "651862"),
            {"3807988", "520359", "683810"}
        )

    def test_transitions(self):
        self.assertEqual(
            transitions({"520359"}, {"662640"}),
            [('connect', '662640'), ('disconnect', '520359')]
        )


if __name__ == "__main__":
    unittest.main()
