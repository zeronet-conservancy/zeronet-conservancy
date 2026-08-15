import json
import pathlib
import tempfile

from P2P.SiteManager import SiteManager
from P2P.plugins.Zeroname.SiteManagerPlugin import SiteManagerPlugin, BIT_RESOLVER
from P2P import compat


# Composed directly via multiple inheritance rather than through the real
# plugin_manager.registerTo()/acceptPlugins() machinery: that machinery
# only takes effect if the plugin module is imported before P2P.SiteManager
# is first decorated (see PluginManager.py's own docstring on this
# ordering requirement) -- by the time this test file runs, other test
# modules have already imported and decorated the real SiteManager class
# without this plugin. This tests the plugin's actual resolution logic
# (which is the real risk), not the production bootstrap-ordering wiring,
# which is separate, already-documented follow-up work.
class ZeronameSiteManager(SiteManagerPlugin, SiteManager):
    pass


class TestP2PPluginsZeroname:
    def testIsDomainRecognizesBitSuffix(self):
        sm = ZeronameSiteManager(pathlib.Path("/tmp"))
        assert compat.run(sm.isDomain, "example.bit") is True

    def testIsDomainFalseForRegularAddress(self):
        sm = ZeronameSiteManager(pathlib.Path("/tmp"))
        assert compat.run(sm.isDomain, "1TestAddressNotADomain12345678") is False

    def testResolveDomainFalseWhenResolverSiteHasNoLocalData(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                sm = ZeronameSiteManager(pathlib.Path(d))
                return await sm.resolveDomain("example.bit")

        # Resolver site (BIT_RESOLVER) gets created locally via need() but
        # has no data/names.json on disk -- resolveBitDomain() finds
        # nothing (falsy), so resolveDomain() falls through to the base
        # class's own stub (always False), matching the original's own
        # `resolveBitDomain(domain) or super().resolveDomain(domain)`.
        assert compat.run(scenario) is False

    def testResolveDomainFindsRealEntryInNamesJson(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                sm = ZeronameSiteManager(pathlib.Path(d))
                resolver_site = sm.add(BIT_RESOLVER)
                await resolver_site.storage.write("content.json", b'{"modified": 123}')
                await resolver_site.content_manager.loadContent("content.json")
                await resolver_site.storage.write(
                    "data/names.json", json.dumps({"example.bit": "1ResolvedAddressAAAAAAAAAAAA"}).encode()
                )
                return await sm.resolveDomain("EXAMPLE.BIT")  # Case-insensitive, matching the original

        assert compat.run(scenario) == "1ResolvedAddressAAAAAAAAAAAA"

    def testResolveDomainCachesUntilResolverContentChanges(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                sm = ZeronameSiteManager(pathlib.Path(d))
                resolver_site = sm.add(BIT_RESOLVER)
                await resolver_site.storage.write("content.json", b'{"modified": 1}')
                await resolver_site.content_manager.loadContent("content.json")
                await resolver_site.storage.write("data/names.json", json.dumps({"a.bit": "1AddrA"}).encode())

                first = await sm.resolveDomain("a.bit")

                # Update names.json on disk but DON'T bump "modified" --
                # cache should still be used, so the stale value returns.
                await resolver_site.storage.write("data/names.json", json.dumps({"a.bit": "1AddrB"}).encode())
                still_cached = await sm.resolveDomain("a.bit")

                # Now bump "modified" -- cache must be invalidated and reloaded.
                await resolver_site.storage.write("content.json", b'{"modified": 2}')
                await resolver_site.content_manager.loadContent("content.json")
                refreshed = await sm.resolveDomain("a.bit")

                return first, still_cached, refreshed

        first, still_cached, refreshed = compat.run(scenario)
        assert first == "1AddrA"
        assert still_cached == "1AddrA"
        assert refreshed == "1AddrB"

    def testResolveDomainFallsThroughToBaseForNonBitDomain(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                sm = ZeronameSiteManager(pathlib.Path(d))
                return await sm.resolveDomain("not-a-bit-domain")

        # Falls through to SiteManager's own base stub (always False/None)
        assert compat.run(scenario) is False
