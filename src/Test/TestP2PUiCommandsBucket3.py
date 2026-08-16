import json
import pathlib
import tempfile

import trio
import trio_websocket

from Crypt import CryptBitcoin
from P2P.Ui.UiServer import UiServer
from P2P.Site import Site
from P2P.SiteManager import SiteManager
from P2P.UserManager import UserManager
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    while True:
        response = json.loads(await ws.get_message())
        if response.get("cmd") == "response" and response.get("to") == msg_id:
            return response


class TestP2PUiCommandsSiteSignPublish:
    def testSiteInfoExposesLocalIdentityForSiteApps(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                address = "1TestIdentitySiteAAAAAAAAAAAA"
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]
                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        first = await _call(ws, "siteInfo")
                        second = await _call(ws, "siteInfo", msg_id=2)
                return first, second, user.getSiteData(address, create=False)

        first, second, site_data = compat.run(scenario)
        assert first["result"]["auth_address"] == site_data["auth_address"]
        assert first["result"]["cert_user_id"] is None
        assert first["result"]["privatekey"] is False
        assert second["result"]["auth_address"] == first["result"]["auth_address"]

    def testSiteSignWithExplicitPrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d))
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "siteSign", {"privatekey": privatekey})
                        return reply, site.storage.isFile("content.json")

        reply, has_content = compat.run(scenario)
        assert reply["result"] == "ok"
        assert has_content is True

    def testSiteSignWithoutAdminPermissionErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d))  # No ADMIN permission

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteSign", {"privatekey": privatekey})

        reply = compat.run(scenario)
        assert "permission" in reply["error"]

    def testSiteSignUsesStoredUserPrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()

                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]
                site_data = user.getSiteData(address)
                site_data["privatekey"] = privatekey

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteSign")  # No privatekey param

        reply = compat.run(scenario)
        assert reply["result"] == "ok"

    def testSitePublishSignsAndMarksServing(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d), serving=False)
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "sitePublish", {"privatekey": privatekey})
                        return reply, site.isServing()

        reply, serving = compat.run(scenario)
        assert reply["result"] == "ok"
        assert serving is True

    def testSitePublishPushesToRealSeededPeer(self):
        """Real end-to-end proof that UiApp's file_server wiring works:
        sitePublish over the websocket actually reaches a live peer, not
        just signs locally -- same backdating trick as
        TestP2PActions.py's sitePublish test, to avoid a same-second
        "modified" tie between the peer's initial sign and this one."""
        async def scenario():
            with tempfile.TemporaryDirectory() as dc, tempfile.TemporaryDirectory() as dp, \
                    tempfile.TemporaryDirectory() as client_site_dir, tempfile.TemporaryDirectory() as peer_site_dir:
                from libp2p.peer.peerinfo import PeerInfo
                from P2P.FileServer import FileServer

                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                peer_site = Site(address, pathlib.Path(peer_site_dir))
                await peer_site.content_manager.sign(privatekey)
                old_content = dict(peer_site.content_manager.contents["content.json"])
                old_content["modified"] -= 100
                old_content.pop("signs", None)
                sign_content = json.dumps(old_content, sort_keys=True)
                old_content["signs"] = {address: CryptBitcoin.sign(sign_content, privatekey)}
                await peer_site.storage.writeJson("content.json", old_content)
                peer_site.content_manager.contents["content.json"] = old_content
                peer_server = FileServer(pathlib.Path(dp), ws_port=None)
                peer_server.addSite(peer_site)

                client_site = Site(address, pathlib.Path(client_site_dir))
                client_site.permissions = ["ADMIN"]
                client_p2p_dir = pathlib.Path(dc) / ".p2p"
                client_p2p_dir.mkdir(parents=True, exist_ok=True)
                client_file_server = FileServer(client_p2p_dir, ws_port=None)
                client_file_server.addSite(client_site)

                ui_server = UiServer(sites={address: client_site}, file_server=client_file_server)

                async with peer_server.run(), client_file_server.run(), ui_server.run():
                    await client_file_server.host.connect(
                        PeerInfo(peer_server.host.peer_id, peer_server.host.get_addrs())
                    )
                    peer_tcp_port = peer_server.host.get_addrs()[0].value_for_protocol("tcp")
                    client_site.addPeer(peer_server.host.peer_id, ip="127.0.0.1", port=int(peer_tcp_port), source="test")

                    await client_site.storage.write("new.txt", b"pushed via ui sitePublish")
                    async with trio_websocket.open_websocket_url(_wsUrl(ui_server, client_site)) as ws:
                        reply = await _call(ws, "sitePublish", {"privatekey": privatekey})

                    peer_content = await peer_site.storage.loadJson("content.json")
                    return reply, peer_content

        reply, peer_content = compat.run(scenario)
        assert reply["result"] == "ok"
        assert "new.txt" in peer_content["files"]

    def testSitePublishBroadcastsSiteChangedToJoinedSessions(self):
        """sitePublish's UiApp.broadcast("siteChanged", ...) call should
        push setSiteInfo to every session connected to that site and
        joined to the "siteChanged" channel -- including sessions other
        than the one that issued the publish -- and skip sessions that
        never joined the channel."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d))
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as joined_ws, \
                            trio_websocket.open_websocket_url(_wsUrl(server, site)) as unjoined_ws:
                        await _call(joined_ws, "channelJoin", {"channels": ["siteChanged"]}, msg_id=1)

                        await joined_ws.send_message(json.dumps(
                            {"cmd": "sitePublish", "params": {"privatekey": privatekey}, "id": 2}
                        ))
                        # The push and the response can arrive in either order --
                        # sort the two messages this exchange produces by cmd.
                        messages = [json.loads(await joined_ws.get_message()) for _ in range(2)]
                        publish_reply = next(m for m in messages if m.get("cmd") == "response")
                        push = next(m for m in messages if m.get("cmd") == "setSiteInfo")

                        with trio.move_on_after(0.3) as cancel_scope:
                            await unjoined_ws.get_message()

                        return publish_reply, push, cancel_scope.cancelled_caught

        publish_reply, push, unjoined_timed_out = compat.run(scenario)
        assert publish_reply["result"] == "ok"
        assert push["cmd"] == "setSiteInfo"
        assert push["params"]["serving"] is True  # real formatSiteInfo() output, not a stub
        assert unjoined_timed_out is True  # Never joined the channel -- no push


class TestP2PUiCommandsCerts:
    def testProviderCreateBuildsSignedSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                admin_address = "1TestProviderAdminAAAAAAAAAAAA"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]
                site_manager.loaded = True
                user_manager = UserManager(data_dir)
                user_manager.create()
                server = UiServer(
                    sites=site_manager.sites, site_manager=site_manager,
                    user_manager=user_manager,
                )
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        reply = await _call(ws, "providerCreate", {"domain": "localid.bit"}, msg_id=1)
                provider = site_manager.sites[reply["result"]["address"]]
                content = await provider.storage.loadJson("content.json")
                manifest = await provider.storage.loadJson("provider.json")
                return reply, provider, content, manifest

        reply, provider, content, manifest = compat.run(scenario)
        assert reply["result"]["announced"] is False
        assert reply["result"]["address"] == provider.address
        assert manifest["domain"] == "localid.bit"
        assert manifest["provider_address"] == provider.address
        assert content["provider_domain"] == "localid.bit"
        assert content["signs"]

    def testCertIssueLocalSignsAndSelectsCertificate(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                address = "1TestLocalIssuerSiteAAAAAAAAAAAA"
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]
                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        issued = await _call(ws, "certIssueLocal", {
                            "domain": "zeronet.local", "auth_type": "web", "auth_user_name": "alice",
                        }, msg_id=1)
                        info = await _call(ws, "siteInfo", msg_id=2)
                        return issued, info, user.settings["local_provider_address"]

        issued, info, provider_address = compat.run(scenario)
        assert issued["result"]["provider_address"] == provider_address
        assert info["result"]["cert_user_id"] == "alice@zeronet.local"

    def testCertAddThenCertListShowsSelected(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()

                address = "1TestCertSiteAAAAAAAAAAAAAAA"
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]
                site_data = user.getSiteData(address)  # Generates auth_address/auth_privatekey
                auth_address = site_data["auth_address"]

                issuer_privatekey = CryptBitcoin.newPrivatekey()
                cert_sign = CryptBitcoin.sign("%s#web/alice" % auth_address, issuer_privatekey)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        add_reply = await _call(ws, "certAdd", [
                            "example.bit", "web", "alice", cert_sign,
                        ], msg_id=1)
                        set_reply = await _call(ws, "certSet", {"domain": "example.bit"}, msg_id=2)
                        list_reply = await _call(ws, "certList", msg_id=3)
                        return add_reply, set_reply, list_reply

        add_reply, set_reply, list_reply = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert set_reply["result"] == "ok"
        certs = list_reply["result"]
        assert certs[0]["domain"] == "example.bit"
        assert certs[0]["selected"] is True


class TestP2PUiCommandsSiteManagement:
    def testSiteSetLimitAcceptsSidebarScalarAndPersists20Mb(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                address = "1TestLimitSiteAAAAAAAAAAAAAA1"
                site = site_manager.add(address)
                site.permissions = ["ADMIN"]
                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "siteSetLimit", "20", msg_id=1)
                return reply, site_manager.getSizeLimitOverride(address)

        reply, override = compat.run(scenario)
        assert reply["result"] == "ok"
        assert override == 20.0

    def testSiteSetBigfileLimitAcceptsSidebarScalar(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                address = "1TestBigfileLimitSiteAAAAAAAA1"
                site = site_manager.add(address)
                site.permissions = ["ADMIN"]
                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "siteSetAutodownloadBigfileLimit", "20", msg_id=1)
                return reply, site_manager.getSiteSetting(address, "autodownload_bigfile_size_limit")

        reply, limit = compat.run(scenario)
        assert reply["result"] == "ok"
        assert limit == 20.0

    def testAsProxiesAdminCommandToTargetSiteUsingActingPermissions(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                dashboard_address = "1TestAsDashboardSiteAAAAAAAA1"
                target_address = "1TestAsTargetSiteAAAAAAAAAA1"
                dashboard_site = site_manager.add(dashboard_address)
                dashboard_site.permissions = ["ADMIN"]
                target_site = site_manager.add(target_address)
                target_site.permissions = []
                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, dashboard_site)) as ws:
                        reply = await _call(
                            ws, "as", [target_address, "siteSetLimit", "20"], msg_id=1
                        )
                return reply, site_manager.getSizeLimitOverride(target_address)

        reply, override = compat.run(scenario)
        assert reply["result"] == "ok"
        assert override == 20.0

    def testAsWithoutAdminOnUnrelatedSiteIsDenied(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                acting_address = "1TestAsNonAdminActorAAAAAAA1"
                target_address = "1TestAsNonAdminTargetAAAAA1"
                acting_site = site_manager.add(acting_address)
                acting_site.permissions = []
                site_manager.add(target_address)
                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, acting_site)) as ws:
                        return await _call(ws, "as", [target_address, "siteSetLimit", "20"], msg_id=1)

        reply = compat.run(scenario)
        assert "No permission" in reply["error"]

    def testSiteCloneCreatesFreshSignedSiteWithCopiedFiles(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                source_privatekey = CryptBitcoin.newPrivatekey()
                source_address = CryptBitcoin.privatekeyToAddress(source_privatekey)
                source = site_manager.add(source_address)
                source.permissions = ["ADMIN"]
                await source.storage.write("index.html", b"hello")
                await source.storage.write("js/all.js", b"console.log(1)")
                await source.storage.writeJson("content.json", {"title": "Source"})
                await source.content_manager.loadContent("content.json")
                await source.content_manager.sign(source_privatekey)

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, source)) as ws:
                        reply = await _call(ws, "siteClone", {"address": source_address})
                new_address = reply["result"]["address"]
                cloned = site_manager.sites[new_address]
                return (
                    new_address,
                    source_address,
                    cloned.storage.isFile("index.html"),
                    cloned.storage.isFile("js/all.js"),
                    dict(cloned.content_manager.contents["content.json"]),
                )

        new_address, source_address, has_index, has_js, content = compat.run(scenario)
        assert new_address != source_address
        assert has_index
        assert has_js
        assert content["cloned_from"] == source_address
        assert content["title"] == "mySource"
        assert "index.html" in content["files"]
        assert "signs" in content

    def testSiteCloneWithRootInnerPathStripsPrefix(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                source_privatekey = CryptBitcoin.newPrivatekey()
                source_address = CryptBitcoin.privatekeyToAddress(source_privatekey)
                source = site_manager.add(source_address)
                source.permissions = ["ADMIN"]
                await source.storage.write("template-new/index.html", b"template body")
                await source.storage.write("unrelated.txt", b"not part of the template")
                await source.content_manager.sign(source_privatekey, extend={"title": "Dashboard"})

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, source)) as ws:
                        reply = await _call(
                            ws, "siteClone", {"address": source_address, "root_inner_path": "template-new"}
                        )
                cloned = site_manager.sites[reply["result"]["address"]]
                return (
                    cloned.storage.isFile("index.html"),
                    cloned.storage.isFile("unrelated.txt"),
                    cloned.storage.isFile("template-new/index.html"),
                )

        has_index, has_unrelated, has_nested_template = compat.run(scenario)
        assert has_index
        assert not has_unrelated
        assert not has_nested_template

    def testSiteCloneWithTargetAddressUpgradesExistingSiteInPlace(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user = user_manager.create()

                source_privatekey = CryptBitcoin.newPrivatekey()
                source_address = CryptBitcoin.privatekeyToAddress(source_privatekey)
                source = site_manager.add(source_address)
                source.permissions = ["ADMIN"]
                await source.storage.write("index.html", b"version 2")
                await source.content_manager.sign(source_privatekey, extend={"title": "Source"})

                target_privatekey = CryptBitcoin.newPrivatekey()
                target_address = CryptBitcoin.privatekeyToAddress(target_privatekey)
                target = site_manager.add(target_address, own=True)
                target.permissions = ["ADMIN"]
                await target.storage.write("index.html", b"version 1")
                await target.storage.writeJson("content.json", {"title": "My own title"})
                await target.content_manager.loadContent("content.json")
                await target.content_manager.sign(target_privatekey)
                user.getSiteData(target_address)["privatekey"] = target_privatekey
                await user.save()

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, source)) as ws:
                        reply = await _call(
                            ws, "siteClone", {"address": source_address, "target_address": target_address}
                        )
                cloned_index = await target.storage.read("index.html")
                return reply, target, cloned_index

        reply, target, cloned_index = compat.run(scenario)
        assert reply["result"]["address"] == target.address
        assert cloned_index == b"version 2"
        assert target.content_manager.contents["content.json"]["title"] == "My own title"

    def testSiteAddDeletePauseResumeAndList(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                admin_address = "1TestAdminSiteAAAAAAAAAAAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                target_address = "1TestTargetSiteAAAAAAAAAAAA2"

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        add_reply = await _call(ws, "siteAdd", {"address": target_address}, msg_id=1)
                        pause_reply = await _call(ws, "sitePause", {"address": target_address}, msg_id=2)
                        target_serving_after_pause = site_manager.sites[target_address].isServing()
                        resume_reply = await _call(ws, "siteResume", {"address": target_address}, msg_id=3)
                        target_serving_after_resume = site_manager.sites[target_address].isServing()
                        list_reply = await _call(ws, "siteList", msg_id=4)
                        delete_reply = await _call(ws, "siteDelete", {"address": target_address}, msg_id=5)
                        return (
                            add_reply, pause_reply, target_serving_after_pause,
                            resume_reply, target_serving_after_resume, list_reply, delete_reply,
                            target_address in site_manager.sites,
                        )

        (add_reply, pause_reply, serving_after_pause, resume_reply, serving_after_resume,
         list_reply, delete_reply, still_present) = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert pause_reply["result"] == "Paused"
        assert serving_after_pause is False
        assert resume_reply["result"] == "Resumed"
        assert serving_after_resume is True
        assert len(list_reply["result"]) == 2  # admin site + target site
        assert delete_reply["result"] == "Deleted"
        assert still_present is False

    def testSiteAddWiresAndDeleteUnwiresAppSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.app import App

                app = App(pathlib.Path(d), enable_dht=False)
                admin_address = "1TestLifecycleAdminAAAAAAAAAA1"
                admin_site = app.addSite(admin_address)
                admin_site.permissions = ["ADMIN"]
                target_address = "1TestLifecycleTargetAAAAAAAAA2"
                server = app.ui_server
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        reply = await _call(ws, "siteAdd", {"address": target_address}, msg_id=1)
                        wired_after_add = (
                            target_address in app.file_server.sites and
                            target_address in app.announcers
                        )
                        delete_reply = await _call(ws, "siteDelete", {"address": target_address}, msg_id=2)
                        unwired_after_delete = (
                            target_address not in app.file_server.sites and
                            target_address not in app.announcers
                        )
                        return reply, wired_after_add, delete_reply, unwired_after_delete

        reply, wired, delete_reply, unwired = compat.run(scenario)
        assert reply["result"] == "ok"
        assert wired is True
        assert delete_reply["result"] == "Deleted"
        assert unwired is True

    def testSitePauseAndResumeBroadcastSiteChanged(self):
        """sitePause/siteResume should push setSiteInfo to any session
        connected to the *target* site (not the admin session issuing the
        command) that's joined the siteChanged channel, same wiring as
        sitePublish."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                admin_address = "1TestAdminSite2AAAAAAAAAAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                target_address = "1TestTargetSite2AAAAAAAAAAA2"
                target_site = site_manager.add(target_address)

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as admin_ws, \
                            trio_websocket.open_websocket_url(_wsUrl(server, target_site)) as target_ws:
                        await _call(target_ws, "channelJoin", {"channels": ["siteChanged"]}, msg_id=1)

                        pause_reply = await _call(admin_ws, "sitePause", {"address": target_address}, msg_id=2)
                        pause_push = json.loads(await target_ws.get_message())

                        resume_reply = await _call(admin_ws, "siteResume", {"address": target_address}, msg_id=3)
                        resume_push = json.loads(await target_ws.get_message())

                        return pause_reply, pause_push, resume_reply, resume_push

        pause_reply, pause_push, resume_reply, resume_push = compat.run(scenario)
        assert pause_reply["result"] == "Paused"
        assert pause_push["cmd"] == "setSiteInfo"
        assert pause_push["params"]["serving"] is False
        assert resume_reply["result"] == "Resumed"
        assert resume_push["cmd"] == "setSiteInfo"
        assert resume_push["params"]["serving"] is True

    def testSiteAddWithoutAdminPermissionErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                address = "1TestNonAdminSiteAAAAAAAAAAA"
                site = site_manager.add(address)  # No ADMIN permission

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteAdd", {"address": "1SomeOtherSiteAAAAAAAAAAAAAA"})

        reply = compat.run(scenario)
        assert "permission" in reply["error"]


class TestP2PUiCommandsPermissions:
    def testPermissionAddAndRemove(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestPermSiteAAAAAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        add_reply = await _call(ws, "permissionAdd", {"permission": "NOSANDBOX"}, msg_id=1)
                        after_add = list(site.permissions)
                        remove_reply = await _call(ws, "permissionRemove", {"permission": "NOSANDBOX"}, msg_id=2)
                        after_remove = list(site.permissions)
                        details_reply = await _call(ws, "permissionDetails", {"permission": "ADMIN"}, msg_id=3)
                        return add_reply, after_add, remove_reply, after_remove, details_reply

        add_reply, after_add, remove_reply, after_remove, details_reply = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert "NOSANDBOX" in after_add
        assert remove_reply["result"] == "ok"
        assert "NOSANDBOX" not in after_remove
        assert "administrate" in details_reply["result"]


class TestP2PUiCommandsUserSettings:
    def testUserSiteAndGlobalSettingsRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()

                address = "1TestUserSettingsSiteAAAAAAA"
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        site_set = await _call(ws, "userSetSettings", {"settings": {"theme": "dark"}}, msg_id=1)
                        site_get = await _call(ws, "userGetSettings", msg_id=2)
                        global_set = await _call(ws, "userSetGlobalSettings", {"settings": {"lang": "en"}}, msg_id=3)
                        global_get = await _call(ws, "userGetGlobalSettings", msg_id=4)
                        return site_set, site_get, global_set, global_get

        site_set, site_get, global_set, global_get = compat.run(scenario)
        assert site_set["result"] == "ok"
        assert site_get["result"] == {"theme": "dark"}
        assert global_set["result"] == "ok"
        assert global_get["result"] == {"lang": "en"}


class TestP2PUiCommandsDbQuery:
    def testDbQueryReturnsRealRows(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestDbQuerySiteAAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                schema = {
                    "db_name": "Test", "db_file": "site.db", "version": 1,
                    "maps": {"data\\.json$": {"to_keyvalue": ["title"]}},
                }
                await site.storage.writeJson("dbschema.json", schema)
                await site.storage.writeJson("data.json", {"title": "ws db test"})
                # rebuildDb() walks content_manager.contents for the file
                # list -- doesn't need a *verified* content.json, just one
                # naming the files to import.
                site.content_manager.contents["content.json"] = {"files": {"data.json": {}}}
                await site.storage.rebuildDb(site.content_manager, reason="test setup")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "dbQuery", {"query": "SELECT * FROM keyvalue WHERE key = 'title'"})

        reply = compat.run(scenario)
        assert reply["result"][0]["value"] == "ws db test"

    def testDbQueryWithoutSchemaReturnsError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestDbQueryNoSchemaAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "dbQuery", {"query": "SELECT 1"})

        reply = compat.run(scenario)
        assert "error" in reply["result"]


class TestP2PUiCommandsServerAndAnnouncerInfo:
    def testServerInfoReportsRealFileServerDetails(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as dc, tempfile.TemporaryDirectory() as dp2p:
                from P2P.FileServer import FileServer

                address = "1TestServerInfoSiteAAAAAAAAA"
                site = Site(address, pathlib.Path(dc))
                file_server = FileServer(pathlib.Path(dp2p), ws_port=None)
                file_server.addSite(site)

                server = UiServer(sites={address: site}, file_server=file_server)
                async with file_server.run(), server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "serverInfo")
                        return reply, file_server.host.peer_id.to_base58()

        reply, expected_peer_id = compat.run(scenario)
        result = reply["result"]
        assert result["peer_id"] == expected_peer_id
        assert len(result["addrs"]) > 0
        assert result["sites"] == 1

    def testServerInfoWithoutFileServerOmitsThoseFields(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestServerInfoNoFsSiteAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})  # No file_server
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "serverInfo")

        reply = compat.run(scenario)
        assert "peer_id" not in reply["result"]
        assert "platform" in reply["result"]

    def testAnnouncerInfoReportsRealTrackerStats(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.SiteAnnouncer import SiteAnnouncer

                address = "1TestAnnouncerInfoSiteAAAAAA"
                site = Site(address, pathlib.Path(d))
                announcer = SiteAnnouncer(site, file_server=None)
                announcer.stats.recordRequest("http://tracker.example.com")
                announcer.stats.recordSuccess("http://tracker.example.com")

                server = UiServer(sites={address: site}, announcers={address: announcer})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "announcerInfo")

        reply = compat.run(scenario)
        result = reply["result"]
        assert result["address"] == "1TestAnnouncerInfoSiteAAAAAA"
        assert result["stats"]["http://tracker.example.com"]["num_success"] == 1

    def testAnnouncerInfoWithoutAnnouncerReturnsEmptyStats(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestNoAnnouncerSiteAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})  # No announcers dict
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "announcerInfo")

        reply = compat.run(scenario)
        assert reply["result"]["stats"] == {}


class TestP2PUiCommandsSiteListModifiedFiles:
    def testDetectsSizeChangedFileAndSkipsUnchanged(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestModifiedFilesSiteAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions = ["ADMIN"]

                await site.storage.write("changed.txt", b"original")
                await site.storage.write("unchanged.txt", b"same size")
                content = {
                    "modified": 1,  # Far in the past -- both files' mtimes are "newer"
                    "files": {
                        "changed.txt": {"size": len(b"original")},
                        "unchanged.txt": {"size": len(b"same size")},
                    },
                }
                site.content_manager.contents["content.json"] = content

                # Now actually change changed.txt's size (unchanged.txt stays put)
                await site.storage.write("changed.txt", b"a completely different, longer body")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteListModifiedFiles")

        reply = compat.run(scenario)
        modified = reply["result"]["modified_files"]
        assert "changed.txt" in modified
        assert "unchanged.txt" not in modified

    def testMissingContentJsonReturnsError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestNoContentSiteAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteListModifiedFiles")

        reply = compat.run(scenario)
        assert "error" in reply["result"]
