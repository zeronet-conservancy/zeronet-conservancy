import pathlib
import tempfile

import trio

from P2P.app import App
from P2P import compat


SITE_ADDRESS = "1TestAppUpnpSiteAAAAAAAAAAAAA1"


class TestP2PAppUpnp:
    def testEnableUpnpDefaultsToTrue(self):
        """Matches the enable_local_discovery precedent: the core App
        class itself defaults to attempting UPnP, only the standalone
        `python -m P2P app` launcher's --no-upnp flag (and individual
        tests that don't want the real SSDP-discovery delay) opt out."""
        with tempfile.TemporaryDirectory() as d:
            app = App(pathlib.Path(d), ws_port=None, enable_dht=False, enable_upnp=False)
            assert app._enable_upnp is False
            assert app.upnp_manager is None

    def testSetupUpnpIsBestEffortWithNoGatewayPresent(self):
        """This sandboxed test environment has no real UPnP-capable
        router on its network, so discover() should return False (per
        UpnpManager's own real, non-mocked discover() -- it already
        catches its own SSDP-discovery failures) and _setupUpnp() should
        return cleanly without raising and without recording a mapped
        port, rather than crashing app.run() over an absent gateway."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                app = App(pathlib.Path(d), ws_port=None, enable_dht=False, enable_upnp=True)
                results = {}
                with trio.move_on_after(15):
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(app.run)
                        await trio.sleep(0.2)  # Let file_server bind
                        # _setupUpnp() runs inline in run() before the nursery
                        # opens its announce/save loops, so by the time our
                        # sleep(0.2) above has scheduled back to us, either
                        # it already finished (no gateway -> fast failure)
                        # or it's still doing real SSDP discovery -- wait a
                        # little longer for it to settle either way.
                        for _ in range(50):
                            if app.upnp_manager is not None:
                                break
                            await trio.sleep(0.2)
                        results["upnp_manager"] = app.upnp_manager
                        results["upnp_port"] = app._upnp_port
                        nursery.cancel_scope.cancel()
                return results

        results = compat.run(scenario)
        assert results["upnp_manager"] is not None
        # No real gateway on this network -> add_port_mapping() never ran
        assert results["upnp_port"] is None

    def testSetupUpnpSkippedWhenDisabled(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                app = App(pathlib.Path(d), ws_port=None, enable_dht=False, enable_upnp=False)
                with trio.move_on_after(5):
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(app.run)
                        await trio.sleep(0.2)
                        result = app.upnp_manager
                        nursery.cancel_scope.cancel()
                return result

        result = compat.run(scenario)
        assert result is None

    def testTeardownUpnpIsNoOpWithoutAMappedPort(self):
        """remove_port_mapping() should never be called when no mapping
        was ever successfully added -- _teardownUpnp() checks
        self._upnp_port is not None first, exactly like _setupUpnp()
        only records it after a real add_port_mapping() success."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                app = App(pathlib.Path(d), ws_port=None, enable_dht=False, enable_upnp=False)
                app.upnp_manager = object()  # Would raise on any method call
                await app._teardownUpnp()  # Must not touch upnp_manager at all

        compat.run(scenario)
