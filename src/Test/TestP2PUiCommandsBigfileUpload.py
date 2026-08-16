import json
import pathlib
import tempfile

import httpx
import trio_websocket

from P2P.Bigfile import digest_piece, merkle_root
from P2P.SiteManager import SiteManager
from P2P.UserManager import UserManager
from P2P.Ui.UiServer import UiServer
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


class TestP2PUiCommandsBigfileUpload:
    def testUploadSmallSinglePieceFileWritesDirectlyNoContentJsonChange(self):
        data = b"small upload content, fits in one piece"

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                site = site_manager.add("1TestBigfileUploadSmallSA1", own=True)
                site.permissions = ["ADMIN"]
                await site.storage.writeJson("content.json", {"title": "x"})
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        init_reply = await _call(ws, "bigfileUploadInit", {
                            "inner_path": "data/small.bin", "size": len(data),
                        })

                    upload_url = base_url + init_reply["result"]["url"]
                    async with httpx.AsyncClient() as client:
                        upload_reply = await client.post(upload_url, content=data)

                return (
                    init_reply, upload_reply.status_code, upload_reply.json(),
                    await site.storage.read("data/small.bin"),
                    site.content_manager.contents["content.json"].get("files_optional"),
                )

        init_reply, status, body, written, files_optional = compat.run(scenario)
        assert "error" not in init_reply["result"]
        assert status == 200
        assert body["piece_num"] == 1
        assert body["merkle_root"] == merkle_root([digest_piece(data)])
        assert written == data
        assert not files_optional  # No content.json change for a single-piece upload

    def testUploadMultiPieceFileWritesPiecemapAndContentJsonEntry(self):
        from P2P.Bigfile import DEFAULT_PIECE_SIZE
        data = (b"A" * DEFAULT_PIECE_SIZE) + (b"B" * DEFAULT_PIECE_SIZE) + b"C" * 12345

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                site = site_manager.add("1TestBigfileUploadMultiSA1", own=True)
                site.permissions = ["ADMIN"]
                await site.storage.writeJson("content.json", {"title": "x"})
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        init_reply = await _call(ws, "bigfileUploadInit", {
                            "inner_path": "data/big.bin", "size": len(data),
                        })

                    upload_url = base_url + init_reply["result"]["url"]
                    async with httpx.AsyncClient(timeout=30) as client:
                        upload_reply = await client.post(upload_url, content=data)

                content = site.content_manager.contents["content.json"]
                written = await site.storage.read("data/big.bin")
                piecefield = await site.storage.loadPiecefield(upload_reply.json()["merkle_root"], 3)
                return upload_reply.json(), written, content.get("files_optional"), piecefield.complete()

        body, written, files_optional, piecefield_complete = compat.run(scenario)
        assert body["piece_num"] == 3
        assert written == data
        entry = files_optional["data/big.bin"]
        assert entry["size"] == len(data)
        assert entry["piece_size"] == 1024 * 1024
        assert entry["sha512"] == body["merkle_root"]
        assert entry["piecemap"] == "data/big.bin.piecemap.msgpack"
        assert piecefield_complete is True  # Every piece we just uploaded is marked already-downloaded

    def testUploadInitForbiddenForNonOwnedSiteWithoutValidSigner(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                site = site_manager.add("1TestBigfileForbiddenSiteA1", own=False)
                site.permissions = ["ADMIN"]
                await site.storage.writeJson("content.json", {"title": "x", "signers": ["1SomeoneElseAddressXXXXXXX1"]})
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "bigfileUploadInit", {"inner_path": "data/x.bin", "size": 10})

        reply = compat.run(scenario)
        assert "error" in reply["result"]

    def testUploadNonceIsOneTimeUse(self):
        data = b"once only"

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                site = site_manager.add("1TestBigfileNonceReuseSAA1", own=True)
                site.permissions = ["ADMIN"]
                await site.storage.writeJson("content.json", {"title": "x"})
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        init_reply = await _call(ws, "bigfileUploadInit", {
                            "inner_path": "data/once.bin", "size": len(data),
                        })

                    upload_url = base_url + init_reply["result"]["url"]
                    async with httpx.AsyncClient() as client:
                        first = await client.post(upload_url, content=data)
                        second = await client.post(upload_url, content=data)

                return first.status_code, second.status_code

        first_status, second_status = compat.run(scenario)
        assert first_status == 200
        assert second_status == 403

    def testUploadUnknownNonceRejected(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                site = site_manager.add("1TestBigfileUnknownNonceA1")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        return await client.post(
                            "%s/ZeroNet-Internal/BigfileUpload?upload_nonce=nonexistent" % base_url, content=b"x",
                        )

        response = compat.run(scenario)
        assert response.status_code == 403
