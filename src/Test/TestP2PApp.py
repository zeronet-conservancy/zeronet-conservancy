import json
import pathlib
import tempfile

import httpx
import trio
import trio_websocket

from libp2p.peer.peerinfo import PeerInfo

from P2P.app import App
from P2P import compat
from Test.TestP2PTor import _startFakeServer


SITE_ADDRESS_1 = "1TestAppSiteAAAAAAAAAAAAAA1"  # 28 chars, valid per SiteManager.isAddress
SITE_ADDRESS_2 = "1TestAppSiteBBBBBBBBBBBBBB2"


class TestP2PApp:
    def testGetOrCreateUserCreatesThenReusesSameUser(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                app = App(pathlib.Path(d), ws_port=None, enable_dht=False)
                first = await app.getOrCreateUser()
                second = await app.getOrCreateUser()
                return first, second

        first, second = compat.run(scenario)
        assert first is second

    def testLoadUsersReadsPersistedUsers(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                app1 = App(data_dir, ws_port=None, enable_dht=False)
                user = await app1.getOrCreateUser()
                await user.save()

                app2 = App(data_dir, ws_port=None, enable_dht=False)
                await app2.loadUsers()
                return user.master_address, app2.user_manager.users

        master_address, users = compat.run(scenario)
        assert master_address in users

    def testAddSiteWiresIntoBothFileServerAndUiServer(self):
        with tempfile.TemporaryDirectory() as d:
            app = App(pathlib.Path(d), ws_port=None, enable_dht=False)
            site = app.addSite(SITE_ADDRESS_1)

            assert app.file_server.sites[SITE_ADDRESS_1] is site
            assert app.ui_server.app.sites[SITE_ADDRESS_1] is site
            assert SITE_ADDRESS_1 in app.announcers
            # UiServer shares SiteManager's own dict, not a copy
            assert app.ui_server.app.sites is app.site_manager.sites

    def testAddSiteRejectsInvalidAddress(self):
        with tempfile.TemporaryDirectory() as d:
            app = App(pathlib.Path(d), ws_port=None, enable_dht=False)
            assert app.addSite("not-a-valid-address") is False

    def testLoadSitesWiresEverythingFromSitesJson(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                data_dir.joinpath("sites.json").write_text(json.dumps({SITE_ADDRESS_1: {"serving": True}}))
                app = App(data_dir, ws_port=None, enable_dht=False)
                await app.loadSites()
                return app.sites, app.file_server.sites, app.announcers

        sites, fs_sites, announcers = compat.run(scenario)
        assert SITE_ADDRESS_1 in sites
        assert SITE_ADDRESS_1 in fs_sites
        assert SITE_ADDRESS_1 in announcers

    def testAddSiteAfterRunStartsAnnounceLoopImmediately(self):
        """Regression test for a real gap: a site added via addSite()
        *after* run()'s nursery has already started (the CLI/UI's normal
        "add a site to an already-running node" path) used to get an
        announcer object with no periodic re-announce ever started for it,
        and no immediate announce either. _wireSite() now self-starts the
        loop via self._nursery when it's already set -- verified here by
        swapping in a fake announce() before the scheduled loop task gets
        its first chance to run (start_soon() doesn't run the task until
        this coroutine's next checkpoint, so the swap is race-free)."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                app = App(
                    pathlib.Path(d), ws_port=None, ui_port=0, enable_dht=False, enable_upnp=False,
                    enable_local_discovery=False, announce_interval=9999,
                )
                with trio.move_on_after(5):
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(app.run)
                        await trio.sleep(0.2)  # Let file_server/ui_server finish binding

                        site = app.addSite(SITE_ADDRESS_1)
                        announce_calls = []

                        async def fake_announce(force=False):
                            announce_calls.append(force)

                        app.announcers[SITE_ADDRESS_1].announce = fake_announce

                        with trio.fail_after(5):
                            while not announce_calls:
                                await trio.sleep(0.05)
                        has_scope_before = SITE_ADDRESS_1 in app._announce_scopes

                        app.deleteSite(SITE_ADDRESS_1)
                        has_scope_after = SITE_ADDRESS_1 in app._announce_scopes

                        nursery.cancel_scope.cancel()
                return announce_calls, has_scope_before, has_scope_after

        announce_calls, has_scope_before, has_scope_after = compat.run(scenario)
        assert announce_calls == [True]  # First loop iteration = the immediate announce
        assert has_scope_before is True
        assert has_scope_after is False  # deleteSite() cancels the loop

    def testDhtBootstrapAllowsFreshNodeToDiscoverPeer(self):
        """Regression test for a real gap: KadDHTDiscovery.add_peer()
        existed to seed the DHT routing table, but nothing in production
        code ever called it -- a fresh node's routing table started empty
        with no way to ever find a first peer via DHT. dht_bootstrap=[...]
        (--dht-bootstrap on the CLI) now seeds it for real via
        App._bootstrapDht(). Node B here never calls host.connect() or
        add_peer() itself anywhere in this test -- only the dht_bootstrap
        config does, proving the CLI-facing flag actually works end to
        end, not just KadDHTDiscovery.add_peer() in isolation (already
        covered manually by TestP2PKadDHT.py)."""
        import hashlib

        site_hash = hashlib.sha1(b"1DhtBootstrapTestSite").digest()

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                app_a = App(pathlib.Path(da), ws_port=None, ui_port=0, enable_upnp=False)

                with trio.move_on_after(10):
                    async with trio.open_nursery() as nursery_a:
                        nursery_a.start_soon(app_a.run)
                        await trio.sleep(0.2)  # Let A's host finish binding

                        addr = app_a.file_server.host.get_addrs()[0]
                        bootstrap_addr = "%s/p2p/%s" % (addr, app_a.file_server.host.peer_id.to_base58())

                        app_b = App(
                            pathlib.Path(db), ws_port=None, ui_port=0, enable_upnp=False,
                            dht_bootstrap=[bootstrap_addr],
                        )
                        async with trio.open_nursery() as nursery_b:
                            nursery_b.start_soon(app_b.run)

                            await app_a.dht_discovery.announce(site_hash)

                            found = []
                            with trio.fail_after(10):
                                while not found:
                                    found = await app_b.dht_discovery.find_peers(site_hash)
                                    if not found:
                                        await trio.sleep(0.2)

                            nursery_b.cancel_scope.cancel()
                        nursery_a.cancel_scope.cancel()
                return app_a.file_server.host.peer_id, [p.peer_id for p in found]

        a_peer_id, found_ids = compat.run(scenario)
        assert a_peer_id in found_ids

    def testRunServesFileAndUiTogether(self):
        """A real end-to-end smoke test of the wired application: one App
        instance actually serving a real site's file over the P2P wire
        protocol, and the same site's real content over its UI HTTP path
        -- both up simultaneously from one app.run() call, which is what
        the standalone entrypoint (`python -m P2P.app`) actually runs."""
        content = b'{"hello": "from the wired app"}'

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                app = App(data_dir, ws_port=None, ui_port=0, enable_dht=False, enable_upnp=False)
                site = app.addSite(SITE_ADDRESS_2)
                await site.storage.write("content.json", content)

                results = {}
                with trio.move_on_after(5):
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(app.run)
                        await trio.sleep(0.2)  # Let file_server/ui_server finish binding

                        # Real P2P file fetch, from a second bare peer
                        with tempfile.TemporaryDirectory() as d2:
                            from P2P.Host import Host
                            from P2P.ConnectionPolicy import ConnectionPolicy
                            from P2P.Peer import Peer

                            client_host = Host(pathlib.Path(d2), ws_port=None)
                            async with client_host.run():
                                await client_host.connect(
                                    PeerInfo(app.file_server.host.peer_id, app.file_server.host.get_addrs())
                                )
                                peer = Peer(app.file_server.host.peer_id, client_host, ConnectionPolicy(client_host))
                                buff = await peer.getFile(SITE_ADDRESS_2, "content.json")
                                results["p2p_content"] = buff.read()

                        # Real UI HTTP fetch, over the same running app
                        ui_base = app.ui_server.bound_addresses[0]
                        async with httpx.AsyncClient() as client:
                            response = await client.get("%s/%s/content.json" % (ui_base, SITE_ADDRESS_2))
                            results["ui_status"] = response.status_code
                            results["ui_content"] = response.content

                        # The periodic save loop already started too --
                        # force one save and check it round-trips for real.
                        await app.site_manager.save()
                        results["saved"] = json.loads((data_dir / "sites.json").read_text())

                        nursery.cancel_scope.cancel()
                return results

        results = compat.run(scenario)
        assert results["p2p_content"] == content
        assert results["ui_status"] == 200
        assert results["ui_content"] == content
        assert SITE_ADDRESS_2 in results["saved"]
        assert results["saved"][SITE_ADDRESS_2]["serving"] is True

    def testRunWithTorEnabledConnectsAndExposesStatusOverServerInfo(self):
        """enable_tor=True against a real fake control-port server (same
        one TestP2PTor.py uses -- no real `tor` binary in this
        environment): app.run() should connect tor_manager, wire it into
        the UI app, and serverInfo should report it over a real
        websocket round trip."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)

                async with trio.open_nursery() as tor_nursery:
                    tor_port = await _startFakeServer(tor_nursery)

                    app = App(
                        data_dir, ws_port=None, ui_port=0, enable_dht=False, enable_upnp=False,
                        enable_tor=True, tor_control_port=tor_port,
                    )
                    results = {}
                    with trio.move_on_after(5):
                        async with trio.open_nursery() as nursery:
                            nursery.start_soon(app.run)
                            await trio.sleep(0.2)  # Let file_server/ui_server bind, and Tor connect

                            results["enabled"] = app.tor_manager.enabled
                            results["status"] = app.tor_manager.status
                            results["same_instance"] = app.ui_server.app.tor_manager is app.tor_manager

                            site = app.addSite(SITE_ADDRESS_1)
                            site.permissions = ["ADMIN"]
                            ui_base = app.ui_server.bound_addresses[0].replace("http://", "ws://")
                            ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (ui_base, site.wrapper_key)
                            async with trio_websocket.open_websocket_url(ws_url) as ws:
                                await ws.send_message(json.dumps({"cmd": "serverInfo", "params": {}, "id": 1}))
                                reply = json.loads(await ws.get_message())
                                results["server_info"] = reply["result"]

                            nursery.cancel_scope.cancel()
                    tor_nursery.cancel_scope.cancel()
                return results

        results = compat.run(scenario)
        assert results["enabled"] is True
        assert results["status"].startswith("Connected")
        assert results["same_instance"] is True
        assert results["server_info"]["tor_enabled"] is True
        assert results["server_info"]["tor_status"].startswith("Connected")
