"""Identity checks. Every repository here is a disposable Git worktree in a temp dir."""
import importlib.util
import os
import subprocess
import tempfile
import time
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
        self.git = fixtures.GIT
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

    def test_crlf_checkout_stays_clean_after_stat_cache_reset(self):
        """A CRLF checkout made with the user's line-ending config must stay clean.

        The verification commands ignore system and user configuration, so once
        Git's index stat cache is invalidated a content-identical CRLF worktree file
        compared against its LF index blob looks modified. Only a real content
        change may still fail verification.
        """
        root = self.nexuscore.root
        worktree = self.nexuscore.worktree('security')
        source = worktree / 'app/main.py'
        home = self.base / 'home'
        home.mkdir()
        user_config = home / '.gitconfig'
        user_config.write_text('[core]\n\tautocrlf = true\n', encoding='ascii')
        environment = {'HOME': str(home), 'USERPROFILE': str(home)}
        with patch.dict(os.environ, environment):
            source.unlink()
            checkout = subprocess.run([self.git, '-C', str(worktree), 'checkout', '-f', '--', '.'],
                                      stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                                      check=False)
            self.assertEqual(checkout.returncode, 0, checkout.stderr)
            self.assertIn(b'\r\n', source.read_bytes())
            os.utime(source, (time.time() + 5, time.time() + 5))
            # Without the effective line-ending configuration the sanitized commands
            # would report the untouched file as modified, which is the reported bug.
            sanitized = {key: value for key, value in os.environ.items()
                         if not key.upper().startswith('GIT_')}
            sanitized.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                              'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'})
            sanitized_status = subprocess.run(
                [self.git, '-C', str(worktree), 'status', '--porcelain=v1', '--untracked-files=all'],
                env=sanitized, stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                check=False)
            self.assertTrue(sanitized_status.stdout)
            self.identity.verify_revision(root, 'security', worktree, 'nexuscore',
                                          self.nexuscore.revision)
            # A caller environment that hides or spoofs Git configuration must not
            # change the value read from the user's own configuration files.
            hostile = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_COUNT': '1',
                       'GIT_CONFIG_KEY_0': 'core.autocrlf', 'GIT_CONFIG_VALUE_0': 'true'}
            with patch.dict(os.environ, hostile):
                self.identity.verify_revision(root, 'security', worktree, 'nexuscore',
                                              self.nexuscore.revision)
            # Git accepts boolean aliases for core.autocrlf; they must normalize too.
            user_config.write_text('[core]\n\tautocrlf = yes\n', encoding='ascii')
            self.identity.verify_revision(root, 'security', worktree, 'nexuscore',
                                          self.nexuscore.revision)
            user_config.write_text('[core]\n\tautocrlf = true\n', encoding='ascii')
            # Real content changes, including trailing-newline edits, still fail.
            source.write_bytes(b'print("synthetic")\r\n\r\n')
            with self.assertRaises(self.identity.IdentityError):
                self.identity.verify_revision(root, 'security', worktree, 'nexuscore',
                                              self.nexuscore.revision)
            source.write_bytes(b'print("synthetic")')
            with self.assertRaises(self.identity.IdentityError):
                self.identity.verify_revision(root, 'security', worktree, 'nexuscore',
                                              self.nexuscore.revision)
            source.write_bytes(b'print("synthetic")\r\n')
            # Without that configuration the same CRLF bytes are a real change, and a
            # caller-supplied override cannot flip the user's value.
            user_config.write_text('[core]\n\tautocrlf = false\n', encoding='ascii')
            with patch.dict(os.environ, hostile), self.assertRaises(self.identity.IdentityError):
                self.identity.verify_revision(root, 'security', worktree, 'nexuscore',
                                              self.nexuscore.revision)
            # An unreadable configuration adds no override, so verification fails closed.
            user_config.write_text('[core\n\tautocrlf = true\n', encoding='ascii')
            with self.assertRaises(self.identity.IdentityError):
                self.identity.verify_revision(root, 'security', worktree, 'nexuscore',
                                              self.nexuscore.revision)

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
