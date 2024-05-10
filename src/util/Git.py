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

global git

try:
    import git
except ImportError:
    git = None
else:
    try:
        global _repo
        up = os.path.dirname
        root = up(up(up(__file__)))
        print(root)
        _repo = git.Repo(root)
    except Exception as exc:
        print("Caught exception while trying to detect git repo.")
        traceback.print_exc()
        git = None

def _gitted(f):
    if git:
        return f
    else:
        return lambda *args, **kwargs: None

@_gitted
def commit() -> Optional[str]:
    """Returns git revision, possibly suffixed with -dirty"""
    dirty = '-dirty' if _repo.is_dirty() else ''
    return f'{_repo.head.commit}{dirty}'

@_gitted
def branch() -> Optional[str]:
    """Returns current git branch if any"""
    try:
        return str(_repo.active_branch)
    except TypeError:
        return None
