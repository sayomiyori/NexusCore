"""Scheduled backup entry point with a compact local status record."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
STATUS = Path('D:/NexusCoreCoordinationBackups/backup-status.txt')
message = 'error: backup did not start'

try:
    from coordination_hub.paths import live_directory
    from coordination_hub.persistent import backup

    result = backup(live_directory(), STATUS.parent)
    message = f'ok {result.name}'
except Exception as exc:
    message = f'error {type(exc).__name__}: {str(exc)[:500]}'
    raise
finally:
    with STATUS.open('a', encoding='utf-8') as output:
        output.write(f'{datetime.now(timezone.utc).isoformat()} {message}\n')
