import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from node_watcher import parse_links, transitions

class WatcherTests(unittest.TestCase):
    def test_transitions(self):
        self.assertEqual(transitions({'520359'}, {'662640'}), [('connect', '662640'), ('disconnect', '520359')])
    def test_parse_links(self):
        self.assertEqual(parse_links('Node: 520359 Connected\n662640 TX\n', '658860'), {'520359','662640'})
    def test_ignore_local(self):
        self.assertEqual(parse_links('658860 Local\n520359 Remote', '658860'), {'520359'})
if __name__ == '__main__': unittest.main()
