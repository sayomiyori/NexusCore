import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'coordination_hub' / 'identity.py'

class PathTests(unittest.TestCase):
    def test_refuses_hard_links(self):
        spec = importlib.util.spec_from_file_location('coordination_identity_hardlink', MODULE)
        identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(identity)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'root'
            root.mkdir()
            original = root / 'original.txt'
            original.write_text('synthetic', encoding='utf-8')
            os.link(original, root / 'alias.txt')
            with self.assertRaises(identity.IdentityError):
                identity.verify_no_links(root, 'original.txt')
            with self.assertRaises(identity.IdentityError):
                identity.verify_no_links(root, 'alias.txt')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction test')
    def test_refuses_real_windows_junction(self):
        spec = importlib.util.spec_from_file_location('coordination_identity_junction', MODULE)
        identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(identity)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'root'
            target = Path(folder) / 'target'
            root.mkdir()
            target.mkdir()
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(root / 'junction'), str(target)],
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            with self.assertRaises(identity.IdentityError):
                identity.verify_no_links(root, 'junction/example.txt')

    def test_refuses_symbolic_link_in_existing_parent(self):
        spec = importlib.util.spec_from_file_location('coordination_identity_paths', MODULE)
        identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(identity)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'root'
            target = Path(folder) / 'target'
            root.mkdir()
            target.mkdir()
            try:
                os.symlink(target, root / 'linked', target_is_directory=True)
            except OSError as exc:
                self.skipTest(f'Symlink creation unavailable: {exc.winerror}')
            with self.assertRaises(identity.IdentityError):
                identity.verify_no_links(root, 'linked/file.py')
            identity.verify_no_links(root, 'new/file.py')

if __name__ == '__main__':
    unittest.main()
