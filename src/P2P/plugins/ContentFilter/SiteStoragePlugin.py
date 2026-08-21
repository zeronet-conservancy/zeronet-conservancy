"""Trio port of plugins/ContentFilter/ContentFilterPlugin.py's own
SiteStoragePlugin.updateDbFile() mute check -- the second of the three
per-file enforcement points (see SitePlugin.py's own docstring for the
first, and why the third doesn't apply here). P2P.SiteStorage is
pluggable now (see its own docstring), and write()/delete() now actually
call updateDbFile() on every real write, so a registerTo("SiteStorage")
override here has a live call site to attach to, not just a method that
sits unused.

Same address-extraction regex as SitePlugin.py -- kept as a small local
copy rather than a shared import, matching how the original itself
repeats the same regex literal in both of its own plugin classes rather
than factoring it out.
"""
import re

from P2P.PluginManager import registerTo

from . import SiteManagerPlugin

_ADDRESS_RE = re.compile(r"/(1[A-Za-z0-9]{26,35})/")


@registerTo("SiteStorage")
class SiteStoragePlugin:
    async def updateDbFile(self, inner_path, content: bytes | None = None) -> bool:
        storage = SiteManagerPlugin.filter_storage
        if storage is not None and content is not None:
            for auth_address in _ADDRESS_RE.findall(str(inner_path)):
                if storage.isMuted(auth_address):
                    return False
        return await super().updateDbFile(inner_path, content)
