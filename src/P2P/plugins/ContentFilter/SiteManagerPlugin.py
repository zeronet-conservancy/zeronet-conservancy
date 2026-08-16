"""Trio port of a scoped slice of plugins/ContentFilter/ContentFilterPlugin.py --
site blocking only (siteblockAdd/Remove/List/Get, enforced at
SiteManager.add()). Absolute import for `registerTo` -- P2P.PluginManager's
loadPlugins() imports plugin packages as bare top-level modules, so a
relative import beyond this package's own top level fails; see
P2P/plugins/CryptMessage/commands.py's own docstring, which hit and
documented this same gotcha first.

Mutes are now stored and manageable through muteAdd/muteRemove/muteList,
and enforced at two of the original's own three points: the on-demand
single-file fetch path (this package's own SitePlugin.py, a
registerTo("Site") override of the new Site.needFile() hook) and db
indexing (SiteStoragePlugin.py, a registerTo("SiteStorage") override of
updateDbFile() -- real now that SiteStorage.write()/delete() auto-call
it on every write, see that module's own docstring). Still not enforced:
WorkerManager.syncSite()'s bulk whole-site download loop (bypasses
Site.needFile() entirely -- see WorkerManager.py's own docstring) and a
FileRequest.actionUpdate()-equivalent (no per-file update-notification
protocol exists in this stack at all, only the content.json push
protocols/update.py covers -- see that module's own docstring).
Deliberately not ported: filter-includes (subscribing to another site's
shared block/mute list -- needs mutes to exist first, since an include's
whole point is importing someone else's mute list too). Also not ported:
the original's
address-hashing "ignore_block" trick for privacy-preserving blocklist
sharing -- plain address matching only (see storage.py's own docstring).
The UiRequestPlugin half (actionWrapper's "this site is blocklisted"
interstitial page, actionUiMedia for its assets) is an HTTP route, not a
websocket command -- same category of gap as UiConfig's/UiPluginManager's
own UiRequestPlugin halves, already set aside there.
"""
from P2P.PluginManager import registerTo

from .storage import ContentFilterStorage

filter_storage: ContentFilterStorage | None = None


@registerTo("SiteManager")
class SiteManagerPlugin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        global filter_storage
        filter_storage = ContentFilterStorage(self.data_dir)

    def add(self, address, own=False, ignore_block=False):
        if not ignore_block and filter_storage.isSiteblocked(address):
            return False
        return super().add(address, own=own)
