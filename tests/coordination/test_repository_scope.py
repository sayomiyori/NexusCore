"""Repository-qualified worktree, reservation and review evidence tests.

Every checkout used here is a disposable Git repository created inside a
temporary directory. No configured repository, live database or production
service is read or written.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FIXTURE = Path(__file__).resolve().parent / 'repository_fixture.py'
PACKAGE = Path(__file__).resolve().parents[2] / 'coordination_hub'
IDENTITY = PACKAGE / 'identity.py'
STORE = PACKAGE / 'store.py'


def _fixture():
    import importlib.util
    spec = importlib.util.spec_from_file_location('coordination_repository_fixture', FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(module_name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryScopeTests(unittest.TestCase):
    def setUp(self):
        self.identity = load('coordination_identity_repository', IDENTITY)
        if not Path(self.identity.GIT).exists():
            self.skipTest('Git is not available')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.fixture = _fixture().GitFixture(self.base / 'authfortress', agents=('security', 'codex'))
        patcher = patch.dict(self.identity.REPOSITORY_ROOTS, {'authfortress': self.fixture.root})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configured_worktree_branch_and_clean_revision_pass(self):
        self.assertEqual(self.identity.worktree_for('authfortress', 'security'),
                         self.fixture.root / '.worktrees/security')
        self.identity.verify_submission('security', 'authfortress', self.fixture.revision)
        self.identity.verify_reservation_scope('security', 'authfortress')

    def test_missing_worktree_of_other_agent_does_not_block_owner(self):
        # development has no AuthFortress worktree; security still reserves normally.
        self.identity.verify_reservation_scope('security', 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('development', 'authfortress')

    def test_unregistered_or_missing_worktree_fails_closed(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('development', 'authfortress', self.fixture.revision)

    def test_wrong_revision_and_dirty_worktree_fail_closed(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'authfortress', '0' * 40)
        dirty = self.fixture.root / '.worktrees/security/app/main.py'
        dirty.write_text('print("uncommitted")\n', encoding='utf-8')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'authfortress', self.fixture.revision)

    def test_wrong_branch_fails_closed(self):
        self.fixture.git('worktree', 'add', '.worktrees/development', '-b', 'feature/not-an-agent-branch')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('development', 'authfortress', self.fixture.revision)

    def test_stale_registered_worktree_of_another_agent_does_not_block(self):
        self.fixture.git('worktree', 'add', '.worktrees/development', '-b', 'agent/development')
        self.identity.verify_reservation_scope('security', 'authfortress')
        stale = self.fixture.root / '.worktrees/development'
        shutil.move(str(stale), str(self.base / 'development-moved'))
        self.assertFalse(stale.exists())
        # Git still lists the missing registration of the other agent; the caller
        # that is genuinely registered must not be affected by it.
        self.assertIn('development', self.fixture.git('worktree', 'list', '--porcelain'))
        self.identity.verify_reservation_scope('security', 'authfortress')
        self.identity.verify_submission('security', 'authfortress', self.fixture.revision)
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('development', 'authfortress')

    def test_configured_root_symlink_is_rejected(self):
        alias = self.base / 'authfortress-alias'
        try:
            os.symlink(self.fixture.root, alias, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links are not available for this account')
        patcher = patch.dict(self.identity.REPOSITORY_ROOTS, {'authfortress': alias})
        patcher.start()
        self.addCleanup(patcher.stop)
        # The alias resolves to a perfectly registered repository, so only an
        # unresolved check of the configured root can reject it.
        self.assertEqual(alias.resolve(), self.fixture.root.resolve())
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('security', 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'authfortress', self.fixture.revision)

    def test_main_checkout_and_foreign_paths_are_rejected(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.fixture.root, 'security', self.fixture.root, 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.fixture.root, 'security', self.base / 'security', 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.base, 'security',
                                          self.fixture.root / '.worktrees/security', 'authfortress')

    def test_unlisted_repository_is_rejected(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.worktree_for('unknown', 'security')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'unknown', self.fixture.revision)
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_revision(self.fixture.root, 'security',
                                          self.fixture.root / '.worktrees/security', 'unknown',
                                          self.fixture.revision)

    def test_reservation_preflight_tolerates_missing_dirs_but_rejects_links(self):
        self.identity.verify_no_links(self.fixture.root, '.worktrees/development/app/main.py')
        try:
            os.symlink(self.fixture.root / 'app', self.fixture.root / '.worktrees/security/linked')
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links are not available for this account')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_no_links(self.fixture.root, '.worktrees/security/linked/main.py')

    def test_configured_repositories_are_allowlisted_only(self):
        self.assertEqual(set(self.identity.REPOSITORY_ROOTS), {'nexuscore', 'authfortress'})
        store = load('coordination_store_repository_ids', STORE)
        self.assertTrue(set(self.identity.REPOSITORY_ROOTS) <= store.REPOSITORIES)


class ReviewEvidenceTests(unittest.TestCase):
    def test_submission_evidence_records_the_submitted_repository(self):
        store = load('coordination_store_repository_evidence', STORE)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            task = hub.create_task('codex', 'AuthFortress work', 'Synthetic')['id']
            hub.claim_task('security', task)
            revision = 'f' * 40
            submitted = hub.submit_for_review('security', task, 'Synthetic report',
                                              'authfortress', revision)
            evidence = hub.get_task(task)['reports'][0]
            self.assertEqual((evidence['repository'], evidence['revision']), ('authfortress', revision))
            self.assertEqual(hub.review_task('codex', task, True, 'Reviewed',
                                             submitted['version'])['status'], 'completed')
            self.assertEqual(hub.list_tasks()[0]['owner'], 'security')


if __name__ == '__main__':
    unittest.main()
