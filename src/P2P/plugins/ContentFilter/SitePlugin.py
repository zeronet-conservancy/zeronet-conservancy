"""Trio port of plugins/ContentFilter/ContentFilterPlugin.py's own
SitePlugin.needFile() mute check -- the first of the three per-file
enforcement points that module's own SiteManagerPlugin.py docstring
listed as blocked ("none of P2P.SiteStorage/P2P.Site/the update protocol
handler are @acceptPlugins yet"). Site.py is pluggable now (see its own
docstring), with needFile() as the real hook this attaches to.

Same address-extraction regex as the original: any bitcoin-style address
segment in the inner_path (e.g. "1AuthorAddress.../data.json") is checked
against the mute list, matching the original's own "mutes apply to any
per-user path, not just known content-index files" behavior.

Narrower than the original two ways:
  - Only Site.needFile() -- the on-demand single-file fetch a user
    actually hits clicking into one page/post. WorkerManager.syncSite()'s
    bulk whole-site download loop bypasses this (see WorkerManager.py's
    own docstring); a real, separate gap, not fixed here.
  - No SiteStorage.updateDbFile() override (the original's second
    enforcement point, refusing to index a muted user's file into the
    site's sqlite db) or a FileRequest.actionUpdate()-equivalent (the
    third, refusing a per-file update notification from a muted author).
    SiteStorage IS pluggable now too, but nothing calls updateDbFile() on
    the write path yet for an override to matter (see that module's own
    docstring); wiring both is real, separate follow-up once there's an
    actual caller to attach to.
"""
import re

from P2P.PluginManager import registerTo

from . import SiteManagerPlugin

_ADDRESS_RE = re.compile(r"/(1[A-Za-z0-9]{26,35})/")


class MutedError(Exception):
    pass


@registerTo("Site")
class SitePlugin:
    async def needFile(self, inner_path, peers, priority=0, timeout=60):
        storage = SiteManagerPlugin.filter_storage
        if storage is not None:
            for auth_address in _ADDRESS_RE.findall(inner_path):
                if storage.isMuted(auth_address):
                    raise MutedError("Mute match: %s, ignoring %s" % (auth_address, inner_path))
        return await super().needFile(inner_path, peers, priority=priority, timeout=timeout)
