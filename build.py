#!/usr/bin/env python3

##  Copyright (c) 2024 caryoscelus
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

"""Simple build/bundle script
"""

import argparse
import os

from src.Config import VERSION


def write_to(args, target):
    branch = args.branch
    commit = args.commit
    if branch is None or commit is None:
        from src.util import Git
        branch = branch or Git.branch() or 'unknown'
        commit = commit or Git.commit(allow_dirty=False) or 'unknown'
    lines = [
        f"build_type = {args.type!r}",
        f"branch = {branch!r}",
        f"commit = {commit!r}",
        f"version = {(args.version or VERSION)!r}",
        f"platform = {args.platform!r}",
    ]
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        import datetime
        build_date = datetime.datetime.fromtimestamp(
            int(source_date_epoch), datetime.timezone.utc
        ).isoformat()
        lines.append(f"build_date = {build_date!r}")
    target.write('\n'.join(lines) + '\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--type', default='source')
    parser.add_argument('--version', help=f'Build version (default: {VERSION})')
    parser.add_argument('--branch')
    parser.add_argument('--commit')
    parser.add_argument('--platform', default='source')
    parser.add_argument('--stdout', action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()
    if args.stdout:
        import sys
        target = sys.stdout
    else:
        target = open('src/Build.py', 'w')
    write_to(args, target)

if __name__ == '__main__':
    main()
