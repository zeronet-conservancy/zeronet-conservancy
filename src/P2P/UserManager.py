"""Trio port of User/UserManager.py -- loads/creates User instances
against private_dir/users.json (P2P.User.py's own persistence target).

get() keeps the original's "single user mode" behavior verbatim by
default: it always returns the first loaded user regardless of the
master_address argument, since zeronet-conservancy (like upstream
ZeroNet) has no built-in multi-user login in core -- that was the
Multiuser plugin's job, via a registerTo("UserManager") override of
get() (see plugins/disabled-Multiuser/UserPlugin.py).

The multiuser constructor flag below folds that override into core
instead of a separate plugin package: unlike a real class-decoration
plugin, there's very little TO override once this is a constructor
param -- get()'s single `if self.multiuser` branch is the entire
behavioral difference, once multiuser_local's memory-vs-disk-persistence
split (see below) is simplified away. Matches this migration's own
established pattern of skipping plugin machinery that wouldn't be
carrying its own weight (e.g. SiteManager's own size-limit/isOwn state
living directly on SiteManager rather than a plugin).

Deliberately simplified relative to the original's own multiuser_local
toggle: every user here is always persisted to private_dir/users.json,
never memory-only. The original's memory-only mode exists so a public,
multi-tenant instance doesn't accumulate strangers' identities on disk
forever; that's a real, separate policy decision (expiry? explicit
opt-in persistence?) worth its own pass, not something to fake here by
silently dropping users a caller may still be holding a reference to.
"""
import json
import logging

import trio

from .User import User


class UserManager:
    def __init__(self, private_dir, multiuser: bool = False):
        self.private_dir = private_dir
        self.multiuser = multiuser
        self.users: dict[str, User] = {}
        self.loaded = False
        self.log = logging.getLogger("P2P.UserManager")

    def _usersJsonPath(self):
        return self.private_dir / "users.json"

    async def load(self) -> None:
        try:
            raw = await trio.to_thread.run_sync(self._usersJsonPath().read_text)
            data = json.loads(raw)
        except FileNotFoundError:
            data = {}

        user_found = set()
        for master_address, user_data in data.items():
            user_found.add(master_address)
            if master_address not in self.users:
                self.users[master_address] = User(self._usersJsonPath(), master_address=master_address, data=user_data)

        for master_address in list(self.users):
            if master_address not in user_found:
                del self.users[master_address]
                self.log.debug("Removed user: %s", master_address)

        self.loaded = True

    def create(self, master_address: str | None = None, master_seed: str | None = None) -> User:
        user = User(self._usersJsonPath(), master_address=master_address, master_seed=master_seed)
        self.users[user.master_address] = user
        user.markDirty()
        self.log.debug("Created user: %s", user.master_address)
        return user

    async def list(self) -> dict:
        if not self.users:  # Not loaded yet (or legitimately empty) -- matches the original's own check
            await self.load()
        return self.users

    async def get(self, master_address: str | None = None):
        users = await self.list()
        if self.multiuser:
            return users.get(master_address) if master_address else None
        if users:
            return next(iter(users.values()))  # Single-user mode -- always the first
        return None
