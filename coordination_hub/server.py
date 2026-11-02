"""Local stdio adapter for trusted coordination agents."""
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

from identity import (
    REPOSITORY_ROOTS,
    IdentityError,
    repository_root,
    verify_no_links,
    verify_reservation_scope,
    verify_submission,
    verify_worktree,
)
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from store import AGENTS, Store, _path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coordination_hub.paths import live_directory

if len(sys.argv) != 4 or sys.argv[1] not in AGENTS:
    raise SystemExit(2)
identity = sys.argv[1]
database = Path(sys.argv[2]).absolute()
worktree = Path(sys.argv[3])
try:
    verify_worktree(repository_root('nexuscore'), identity, worktree)
except IdentityError:
    raise SystemExit(2) from None
synthetic_database = Path('D:/Programming/NexusCore-coordination-connectivity-test/hub.sqlite3')
allowed_temp = database.is_relative_to(Path(tempfile.gettempdir()).resolve()) and database.name == 'hub.sqlite3'
allowed_synthetic = database == synthetic_database
live_database = live_directory() / 'hub.sqlite3'
allowed_live = database == live_database
if allowed_synthetic:
    try:
        verify_no_links(Path('D:/'), 'Programming/NexusCore-coordination-connectivity-test/hub.sqlite3')
    except IdentityError:
        raise SystemExit(2) from None
if not (allowed_temp or allowed_synthetic or allowed_live):
    raise SystemExit(2)
stack = ExitStack()
if allowed_live:
    from coordination_hub.directory_guard import test_directory_guard
    from coordination_hub.persistent import verify_runtime
    stack.enter_context(test_directory_guard(database.parent))
    verify_runtime(database.parent)
hub = Store(database, existing_only=allowed_live)
server = FastMCP('NexusCore Coordination Hub', instructions=(
    'Use the assigned worktree and branch. Before editing, claim a task and reserve all affected paths; '
    'check existing owners and renew leases before they expire. Reservations are advisory, not filesystem locks. '
    'Reservations are repository-qualified: pass the repository id you are editing, and reserve the worktree '
    'of that repository only. Report progress and heartbeat, communicate conflicts, and submit a clean committed '
    'revision for Codex review when the user authorizes commits. '
    'Do not merge or push until the requested review and user workflow permit it.'
))

def mutate(request_id: str, operation: str, payload: dict, *, preflight=None) -> dict:
    verify_worktree(repository_root('nexuscore'), identity, worktree)
    return hub.mutate(identity, request_id, operation, payload, preflight=preflight)

@server.tool()
def create_task(request_id: str, title: str, description: str) -> dict[str, object]:
    """Create a coordination task."""
    return mutate(request_id, 'create_task', {'title': title, 'description': description})

@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def list_tasks(after: int = 0, limit: int = 50) -> list[dict]:
    """List coordination tasks."""
    verify_worktree(repository_root('nexuscore'), identity, worktree)
    return hub.list_tasks(after, limit)

@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_task(task_id: str, reports_after: int = 0, reports_limit: int = 50) -> dict[str, object]:
    """Read a task and its reports for review."""
    verify_worktree(repository_root('nexuscore'), identity, worktree)
    return hub.get_task(task_id, reports_after, reports_limit)

@server.tool()
def claim_task(request_id: str, task_id: str) -> dict[str, object]:
    """Claim an open task."""
    return mutate(request_id, 'claim_task', {'task_id': task_id})

@server.tool()
def submit_for_review(request_id: str, task_id: str, report: str, repository: str, revision: str) -> dict[str, object]:
    """Submit the owner's task and report to the reviewer."""
    return mutate(request_id, 'submit_for_review', {'task_id': task_id, 'report': report,
                                                     'repository': repository, 'revision': revision},
                  preflight=lambda: verify_submission(identity, repository, revision))

@server.tool()
def review_task(request_id: str, task_id: str, approved: bool, report: str, expected_version: int) -> dict[str, object]:
    """Approve or return a submitted task; only codex may review."""
    return mutate(request_id, 'review_task', {'task_id': task_id, 'approved': approved, 'report': report,
                                              'expected_version': expected_version})

@server.tool()
def send_message(request_id: str, recipient: str, body: str) -> dict[str, object]:
    """Send a message to an agent."""
    return mutate(request_id, 'send_message', {'recipient': recipient, 'body': body})

@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def check_inbox(after: int = 0, limit: int = 50) -> list[dict]:
    """Read this agent's inbox."""
    verify_worktree(repository_root('nexuscore'), identity, worktree)
    return hub.inbox(identity, after, limit)

@server.tool()
def heartbeat(request_id: str, status: str) -> dict[str, object]:
    """Update the current agent's status."""
    return mutate(request_id, 'heartbeat', {'status': status})

@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_agent_status(agent: str) -> dict[str, object]:
    """Read an agent's last reported status."""
    verify_worktree(repository_root('nexuscore'), identity, worktree)
    return hub.get_agent_status(agent)

@server.tool()
def renew_leases(request_id: str, task_id: str, lease_ids: list[str], ttl: int = 900) -> dict[str, object]:
    """Renew unexpired leases owned by this agent."""
    return mutate(request_id, 'renew_leases', {'task_id': task_id, 'lease_ids': lease_ids, 'ttl': ttl})

@server.tool()
def lock_files(request_id: str, task_id: str, paths: list[str], repository: str = 'nexuscore',
               ttl: int = 900) -> dict[str, object]:
    """Acquire advisory leases for repository-relative paths."""
    if repository not in REPOSITORY_ROOTS:
        raise ValueError('Unsupported repository')
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100 or not 60 <= ttl <= 3600:
        raise ValueError('Invalid lease request')
    def check_paths():
        # The caller's own worktree in this repository must exist and be correct.
        root = verify_reservation_scope(identity, repository)
        for path in paths:
            _path(path)
            for agent in AGENTS:
                # A missing worktree of another agent is tolerated; links are never.
                verify_no_links(root, f'.worktrees/{agent}/{path}')
    # Keep the canonical default payload identical to the pre-repository version so
    # a request ID persisted by the previous Hub still replays to its stored result.
    payload = {'task_id': task_id, 'paths': paths, 'ttl': ttl}
    if repository != 'nexuscore':
        payload['repository'] = repository
    return mutate(request_id, 'lock_files', payload, preflight=check_paths)

@server.tool()
def unlock_files(request_id: str, task_id: str, lease_ids: list[str]) -> dict[str, object]:
    """Release this agent's leases."""
    return mutate(request_id, 'unlock_files', {'task_id': task_id, 'lease_ids': lease_ids})

@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_file_owners(paths: list[str], repository: str = 'nexuscore') -> list[dict]:
    """Get active advisory leases for paths."""
    if repository not in REPOSITORY_ROOTS:
        raise ValueError('Unsupported repository')
    verify_worktree(repository_root('nexuscore'), identity, worktree)
    return hub.file_owners(paths, repository)

if __name__ == '__main__':
    try:
        server.run(transport='stdio')
    finally:
        stack.close()
