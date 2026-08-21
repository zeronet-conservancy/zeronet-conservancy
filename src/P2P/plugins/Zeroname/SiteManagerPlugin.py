"""Trio port of plugins/Zeroname/SiteManagerPlugin.py -- .bit domain
resolution via a ZeroName-style site's data/names.json, registered
against P2P.SiteManager (not the legacy Site/SiteManager.py). This is
the plugin the P2P.SiteManager module docstring anticipated: isDomain()/
resolveDomain() are real no-op extension points there specifically so a
plugin like this one can override them.

Scope cuts from the original:
  - config.bit_resolver (a legacy global Config default) becomes a plain
    class attribute here (BIT_RESOLVER), same default address, since this
    package has no global Config to read from -- matches every other
    P2P.* port's move away from global Config.
  - No site_zeroname.needFile("data/names.json", priority=10) before
    reading it: P2P.SiteManager has no WorkerManager/FileServer reference
    to drive a download-on-need through (see SiteManager.py's own
    docstring -- add()/need() don't download either, for the same
    reason). Resolution only works if the resolver site's
    data/names.json is already present locally -- e.g. fetched
    separately via Actions.siteDownload()/siteNeedFile(). A resolver
    site that hasn't been fetched yet resolves nothing, rather than
    blocking on a fetch this class has no way to start.
"""
import logging

# Absolute, not relative: loadPlugins() imports this plugin the same way
# the legacy loader imports plugins/* -- as a bare top-level module (e.g.
# "Zeroname"), not as a proper submodule of the P2P.plugins package, since
# it works by sys.path.append(path_plugins) + __import__(dir_name). A
# relative import here would try to climb past that bare module's
# (nonexistent) parent package.
from P2P.PluginManager import registerTo

log = logging.getLogger("P2P.plugins.Zeroname")

BIT_RESOLVER = "1GnACKctkJrGWHTqxk9T9zXo2bLQc2PDnF"
# ZeroID is the historical built-in authorization provider. Keep this
# bootstrap mapping so a fresh node can reach the registration site before
# its ZeroName database has been downloaded.
BOOTSTRAP_DOMAINS = {
    "zeroid.bit": "1iD5ZQJMNXu43w1qLB8sfdHVKppVMduGz",
}


@registerTo("SiteManager")
class SiteManagerPlugin:
    site_zeroname = None
    db_domains: dict = {}
    db_domains_modified = None

    def isBitDomain(self, address: str) -> bool:
        import re
        return bool(re.match(r"(.*?)([A-Za-z0-9_-]+\.bit)$", address))

    async def resolveBitDomain(self, domain: str):
        domain = domain.lower()
        if not self.site_zeroname:
            self.site_zeroname = await self.need(BIT_RESOLVER)
            if not self.site_zeroname:
                return None

        content = self.site_zeroname.content_manager.contents.get("content.json", {})
        site_zeroname_modified = content.get("modified", 0)
        if not self.db_domains or self.db_domains_modified != site_zeroname_modified:
            try:
                self.db_domains = await self.site_zeroname.storage.loadJson("data/names.json")
            except Exception as err:
                log.error("Error loading names.json: %s", err)
                self.db_domains = {}
            log.debug(
                "Domain db with %s entries loaded (modification: %s -> %s)",
                len(self.db_domains), self.db_domains_modified, site_zeroname_modified,
            )
            self.db_domains_modified = site_zeroname_modified

        return self.db_domains.get(domain) or BOOTSTRAP_DOMAINS.get(domain)

    async def resolveDomain(self, domain: str):
        resolved = await self.resolveBitDomain(domain)
        if resolved:
            return resolved
        return await super().resolveDomain(domain)

    async def isDomain(self, address: str) -> bool:
        if self.isBitDomain(address):
            return True
        return await super().isDomain(address)
