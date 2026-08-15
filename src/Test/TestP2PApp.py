import json
import pathlib
import tempfile

import httpx
import trio

from libp2p.peer.peerinfo import PeerInfo

from P2P.app import App, loadSiteAddresses
from P2P import compat


class TestP2PApp:
    def testLoadSiteAddressesReadsSitesJson(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            (data_dir / "sites.json").write_text(json.dumps({"1SiteA": {}, "1SiteB": {}}))
            assert sorted(loadSiteAddresses(data_dir)) == ["1SiteA", "1SiteB"]

    def testLoadSiteAddressesMissingFileReturnsEmpty(self):
        with tempfile.TemporaryDirectory() as d:
            assert loadSiteAddresses(pathlib.Path(d)) == []

    def testAddSiteWiresIntoBothFileServerAndUiServer(self):
        with tempfile.TemporaryDirectory() as d:
            app = App(pathlib.Path(d), ws_port=None, enable_dht=False)
            site = app.addSite("1TestAppSite")

            assert app.file_server.sites["1TestAppSite"] is site
            assert app.ui_server.app.sites["1TestAppSite"] is site
            assert "1TestAppSite" in app.announcers

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
                app = App(data_dir, ws_port=None, ui_port=0, enable_dht=False)
                site = app.addSite("1TestAppSite2")
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
                                buff = await peer.getFile("1TestAppSite2", "content.json")
                                results["p2p_content"] = buff.read()

                        # Real UI HTTP fetch, over the same running app
                        ui_base = app.ui_server.bound_addresses[0]
                        async with httpx.AsyncClient() as client:
                            response = await client.get("%s/1TestAppSite2/content.json" % ui_base)
                            results["ui_status"] = response.status_code
                            results["ui_content"] = response.content

                        nursery.cancel_scope.cancel()
                return results

        results = compat.run(scenario)
        assert results["p2p_content"] == content
        assert results["ui_status"] == 200
        assert results["ui_content"] == content
