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

Applies to both the on-demand single-file fetch (commands.py's fileNeed,
actions.py's siteNeedFile) AND WorkerManager.syncSite()'s own bulk
whole-site download loop -- syncSite() routes every listed file through
site.needFile() now too (see that function's own docstring), catching
and skipping a MutedError the same as any other per-file fetch failure,
rather than aborting the whole sync over one muted author.

Still narrower than the original one way: no FileRequest.actionUpdate()-
equivalent (the original's third enforcement point, refusing a per-file
update NOTIFICATION from a muted author) -- this stack has no per-file
push-notification protocol at all, only the content.json push
protocols/update.py covers (see that module's own docstring); not
applicable until that protocol exists.

The second enforcement point (SiteStorage.updateDbFile(), refusing to
index a muted user's file into the site's sqlite db) is a separate file,
SiteStoragePlugin.py -- SiteStorage.write()/delete() now auto-call
updateDbFile() on every real write (see that module's own docstring), so
that override actually fires now.
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
