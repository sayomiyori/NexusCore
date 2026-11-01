"""Fixed local paths for the NexusCore Coordination Hub."""
import os
from pathlib import Path


def live_directory():
    if os.name != 'nt':
        raise OSError('Windows only')
    return Path('D:/NexusCoreCoordination')
