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

def write_to(args, target):
    branch = args.branch
    commit = args.commit
    if branch is None or commit is None:
        from src.util import Git
        branch = branch or Git.branch() or 'unknown'
        commit = commit or Git.commit() or 'unknown'
    target.write('\n'.join([
        f"build_type = {args.type!r}",
        f"branch = {branch!r}",
        f"commit = {commit!r}",
        f"version = {args.version!r}",
        f"platform = {args.platform!r}",
    ]))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--type', default='source')
    parser.add_argument('--version')
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
