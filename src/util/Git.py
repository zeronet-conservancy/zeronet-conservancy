##  Copyright (c) 2023 caryoscelus
##
##  zeronet-conservancy is free software: you can redistribute it and/or modify it under the
##  terms of the GNU General Public License as published by the Free Software
##  Foundation, either version 3 of the License, or (at your option) any later version.
##
##  zeronet-conservancy is distributed in the hope that it will be useful, but
##  WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
##  FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
##  details.
##
## You should have received a copy of the GNU General Public License along with
## zeronet-conservancy. If not, see <https://www.gnu.org/licenses/>.
##

"""Git-related operations

Currently this is only to retrieve git revision for debug purposes, but later on we might
also want to use it for updates.
"""

import os

from typing import Optional

git = None
_repo = None
_loaded = False


def _load():
    """Lazily import GitPython and resolve the repository.

    Importing GitPython runs `git version` at import time (a mitigation for
    CVE-2024-22190), so avoid triggering it until version info is actually
    requested.
    """
    global git, _repo, _loaded
    if _loaded:
        return
    _loaded = True

    os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")  # Don't warn if git is missing

    try:
        import git as _git
    except ImportError:
        git = None
        return

    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        _repo = _git.Repo(root)
        git = _git
    except Exception:
        git = None
        _repo = None


def commit() -> Optional[str]:
    """Returns git revision, possibly suffixed with -dirty"""
    _load()
    if git is None:
        return None
    try:
        dirty = '-dirty' if _repo.is_dirty() else ''
        return f'{_repo.head.commit}{dirty}'
    except Exception:
        return None


def branch() -> Optional[str]:
    """Returns current git branch if any"""
    _load()
    if git is None:
        return None
    try:
        return str(_repo.active_branch)
    except Exception:
        return None
