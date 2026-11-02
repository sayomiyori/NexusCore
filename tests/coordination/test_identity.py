"""Identity checks. Every repository here is a disposable Git worktree in a temp dir."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / 'coordination_hub' / 'identity.py'
FIXTURE = Path(__file__).resolve().parent / 'repository_fixture.py'


def load(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.identity = load('coordination_identity', MODULE)
        fixtures = load('coordination_repository_fixture', FIXTURE)
        self.GitFixture = fixtures.GitFixture
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.nexuscore = fixtures.GitFixture(self.base / 'nexuscore')
        self.authfortress = fixtures.GitFixture(self.base / 'authfortress')
        patcher = patch.dict(self.identity.REPOSITORY_ROOTS, {
            'nexuscore': self.nexuscore.root,
            'authfortress': self.authfortress.root,
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configured_allowlist_is_fixed(self):
        fresh = load('coordination_identity_defaults', MODULE)
        self.assertEqual(set(fresh.REPOSITORY_ROOTS), {'nexuscore', 'authfortress'})
        self.assertEqual(fresh.repository_root('nexuscore'), Path('D:/Programming/NexusCore'))
        self.assertEqual(fresh.repository_root('authfortress'), Path('D:/Programming/AuthFortress'))
        with self.assertRaises(fresh.IdentityError):
            fresh.repository_root('agenthub')

    def test_revision_must_match_checked_out_clean_worktree(self):
        auth_root = self.authfortress.root
        auth_worktree = self.authfortress.worktree('security')
        self.identity.verify_revision(auth_root, 'security', auth_worktree, 'authfortress',
                                      self.authfortress.revision)
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_revision(auth_root, 'security', auth_worktree, 'authfortress', '0' * 40)
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_revision(self.nexuscore.root, 'security', auth_worktree,
                                          'authfortress', self.authfortress.revision)
        with patch.object(self.identity, 'verify_worktree'), \
                patch.object(self.identity, '_git',
                             side_effect=[self.authfortress.revision.encode(), b'?? synthetic.py\n']), \
                self.assertRaises(self.identity.IdentityError):
            self.identity.verify_revision(auth_root, 'security', auth_worktree,
                                          'authfortress', self.authfortress.revision)
        (auth_worktree / 'app/main.py').write_text('print("uncommitted")\n', encoding='utf-8')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_revision(auth_root, 'security', auth_worktree, 'authfortress',
                                          self.authfortress.revision)

    def test_worktree_mapping_and_branch(self):
        root = self.nexuscore.root
        for agent in ('security', 'development', 'codex'):
            self.identity.verify_worktree(root, agent, self.nexuscore.worktree(agent), 'nexuscore')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(root, 'security', self.nexuscore.worktree('development'),
                                          'nexuscore')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(root, 'security', root, 'nexuscore')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(root, 'fake', self.nexuscore.worktree('security'), 'nexuscore')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(root, 'codex', root, 'nexuscore')


if __name__ == '__main__':
    unittest.main()
