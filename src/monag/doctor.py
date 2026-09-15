"""Report actual dependencies and observation coverage without installing anything."""
import os
from pathlib import Path
import shutil
import sys
from .monitor import command


def diagnose(root):
    git, git_error = command(['git', '--version'])
    own = Path('/proc/self')
    try:
        namespace = os.readlink(own / 'ns/pid')
        process_count = sum(p.name.isdigit() for p in Path('/proc').iterdir())
    except OSError:
        namespace, process_count = 'unavailable', 0
    errors = []
    if git_error:
        errors.append(git_error)
    if not root.is_dir():
        errors.append('workspace root does not exist')
    if not (own / 'stat').exists():
        errors.append('Linux /proc process data is unavailable')
    return {'python': sys.version.split()[0], 'runtime_dependencies': 'rich>=14,<15 (terminal Markdown); PyYAML>=6,<7 (Planfile backlog)',
            'git': git.strip() or None, 'github_cli': shutil.which('gh'),
            'pid_namespace': namespace, 'visible_processes': process_count,
            'uid': os.getuid(), 'root': str(root), 'errors': errors,
            'coverage': ['Only processes visible in this PID namespace can be observed.',
                         'IDE or remote agents need explicit process registration or a future host adapter.',
                         'No prompt, transcript, environment-variable or file-content collection.']}
