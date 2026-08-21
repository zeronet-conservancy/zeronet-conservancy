import json
import pathlib
import tempfile

import trio
from libp2p.peer.peerinfo import PeerInfo

from Crypt import CryptAes, CryptBitcoin, CryptEcies
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.FileServer import FileServer
from P2P.Peer import Peer
from P2P.Site import Site
from P2P.WorkerManager import publishGossip, publishUpdate
from P2P import compat


async def _makePrivateEnvelope(site_dir, address, privatekey, recipient_address, signature):
    """Signs+encrypts a small real site for one approved recipient.
    Returns (envelope_body_bytes, content_key)."""
    site = Site(address, pathlib.Path(site_dir))
    await site.storage.write("index.html", b"<h1>secret</h1>")
    recipients = site.content_manager.addRecipientKey({}, recipient_address, signature)
    content_key = CryptAes.newKey()
    await site.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)
    envelope = await site.storage.loadJson("content.json")
    return json.dumps(envelope).encode("utf8"), content_key


class TestP2PPrivateSitePropagation:
    """Real end-to-end proof that private-site envelopes propagate over
    the actual unicast wire protocol (update.py's applyContentUpdate())
    the same way a public site's content.json does, with the recipient/
    bystander split applying on the receiving end -- not just at the
    ContentManager/Site unit level already covered elsewhere."""

    def testRecipientReceivesDecryptedCacheOverUnicastPush(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        recipient_privatekey = CryptBitcoin.newPrivatekey()
        recipient_address = CryptBitcoin.privatekeyToAddress(recipient_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, recipient_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as owner_site_dir, tempfile.TemporaryDirectory() as recipient_site_dir:
                body, content_key = await _makePrivateEnvelope(
                    owner_site_dir, address, privatekey, recipient_address, signature,
                )

                server_owner = FileServer(pathlib.Path(da), ws_port=None)
                server_recipient = FileServer(pathlib.Path(db), ws_port=None)
                recipient_site = Site(address, pathlib.Path(recipient_site_dir))
                recipient_site.private_key = content_key  # already unlocked, e.g. via unlockPrivate()
                server_recipient.addSite(recipient_site)

                async with server_owner.run(), server_recipient.run():
                    await server_owner.host.connect(
                        PeerInfo(server_recipient.host.peer_id, server_recipient.host.get_addrs())
                    )
                    peer = Peer(server_recipient.host.peer_id, server_owner.host, ConnectionPolicy(server_owner.host))
                    reply = await peer.pushUpdate(address, "content.json", body)
                    return reply, recipient_site.content_manager.contents.get("content.json")

        reply, cached = compat.run(scenario)
        assert "ok" in reply
        assert cached.get("privatekey") is None  # decrypted, not the envelope
        # Recorded size is of the ciphertext-at-rest (see ContentManager.sign()'s
        # own docstring on why encryptFiles() runs before hashFiles()), not the
        # original plaintext -- confirms the decrypted cache is otherwise
        # correct/consistent with what sign() actually recorded.
        assert cached["files"]["index.html"]["size"] != len(b"<h1>secret</h1>")
        assert "index.html" in cached["files"]

    def testBystanderCachesEnvelopeWithoutCrashing(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        recipient_privatekey = CryptBitcoin.newPrivatekey()
        recipient_address = CryptBitcoin.privatekeyToAddress(recipient_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, recipient_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as owner_site_dir, tempfile.TemporaryDirectory() as bystander_site_dir:
                body, _content_key = await _makePrivateEnvelope(
                    owner_site_dir, address, privatekey, recipient_address, signature,
                )

                server_owner = FileServer(pathlib.Path(da), ws_port=None)
                server_bystander = FileServer(pathlib.Path(db), ws_port=None)
                bystander_site = Site(address, pathlib.Path(bystander_site_dir))
                # bystander_site.private_key stays None -- no access
                server_bystander.addSite(bystander_site)

                async with server_owner.run(), server_bystander.run():
                    await server_owner.host.connect(
                        PeerInfo(server_bystander.host.peer_id, server_bystander.host.get_addrs())
                    )
                    peer = Peer(server_bystander.host.peer_id, server_owner.host, ConnectionPolicy(server_owner.host))
                    reply = await peer.pushUpdate(address, "content.json", body)
                    cached = bystander_site.content_manager.contents.get("content.json")
                    # Nothing should crash trying to use the still-encrypted cache.
                    file_info = bystander_site.content_manager.getFileInfo("index.html")
                    return reply, cached, file_info

        reply, cached, file_info = compat.run(scenario)
        assert "ok" in reply
        assert cached.get("privatekey") is True  # still the envelope, unusable
        assert file_info is False  # no crash -- just "not found", since files aren't listed in an envelope

    def testPublishUpdateSendsEnvelopeNotPlaintextToBystander(self):
        """Regression test for a real bug caught while writing this file:
        WorkerManager.publishUpdate() used to serialize
        site.content_manager.contents[inner_path] directly -- for a
        private site that's the DECRYPTED plaintext (only the owner,
        who always holds the content key, calls sign()), so the owner's
        own publish would have leaked the plaintext to every peer,
        approved or not. Fixed to read the body straight off disk (the
        real envelope) instead. This exercises the actual publishUpdate()
        function, not a hand-built push -- the other tests in this file
        predate the fix and bypassed it entirely by constructing the
        envelope body themselves."""
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        recipient_privatekey = CryptBitcoin.newPrivatekey()
        recipient_address = CryptBitcoin.privatekeyToAddress(recipient_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, recipient_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as dc, tempfile.TemporaryDirectory() as owner_dir, \
                    tempfile.TemporaryDirectory() as recipient_dir, tempfile.TemporaryDirectory() as bystander_dir:
                site_owner = Site(address, pathlib.Path(owner_dir))
                await site_owner.storage.write("index.html", b"<h1>secret</h1>")
                recipients = site_owner.content_manager.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await site_owner.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)
                site_owner.private_key = content_key

                server_owner = FileServer(pathlib.Path(da), ws_port=None)
                server_owner.addSite(site_owner)
                server_recipient = FileServer(pathlib.Path(db), ws_port=None)
                recipient_site = Site(address, pathlib.Path(recipient_dir))
                recipient_site.private_key = content_key  # already unlocked
                server_recipient.addSite(recipient_site)
                server_bystander = FileServer(pathlib.Path(dc), ws_port=None)
                bystander_site = Site(address, pathlib.Path(bystander_dir))  # never unlocked
                server_bystander.addSite(bystander_site)

                async with server_owner.run(), server_recipient.run(), server_bystander.run():
                    await server_owner.host.connect(
                        PeerInfo(server_recipient.host.peer_id, server_recipient.host.get_addrs())
                    )
                    await server_owner.host.connect(
                        PeerInfo(server_bystander.host.peer_id, server_bystander.host.get_addrs())
                    )
                    peer_to_recipient = Peer(
                        server_recipient.host.peer_id, server_owner.host, ConnectionPolicy(server_owner.host),
                    )
                    peer_to_bystander = Peer(
                        server_bystander.host.peer_id, server_owner.host, ConnectionPolicy(server_owner.host),
                    )

                    published = await publishUpdate(site_owner, [peer_to_recipient, peer_to_bystander])

                    return (
                        published,
                        recipient_site.content_manager.contents.get("content.json"),
                        bystander_site.content_manager.contents.get("content.json"),
                    )

        published, recipient_cached, bystander_cached = compat.run(scenario)
        assert published == 2
        assert recipient_cached.get("privatekey") is None  # decrypted -- had the key
        assert "index.html" in recipient_cached["files"]
        assert bystander_cached.get("privatekey") is True  # still the envelope -- no key
        assert "files" not in bystander_cached  # never saw the plaintext file listing

    def testPublishGossipSendsEnvelopeNotPlaintext(self):
        """Same regression as testPublishUpdateSendsEnvelopeNotPlaintext-
        SendsEnvelopeNotPlaintextToBystander, for the gossipsub publish
        path (WorkerManager.publishGossip()) instead of unicast."""
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        recipient_privatekey = CryptBitcoin.newPrivatekey()
        recipient_address = CryptBitcoin.privatekeyToAddress(recipient_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, recipient_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as owner_dir, tempfile.TemporaryDirectory() as recipient_dir:
                site_owner = Site(address, pathlib.Path(owner_dir))
                await site_owner.storage.write("index.html", b"<h1>secret</h1>")
                recipients = site_owner.content_manager.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await site_owner.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)
                site_owner.private_key = content_key

                site_recipient = Site(address, pathlib.Path(recipient_dir))
                site_recipient.private_key = content_key  # already unlocked

                server_owner = FileServer(pathlib.Path(da), ws_port=None)
                server_owner.addSite(site_owner)
                server_recipient = FileServer(pathlib.Path(db), ws_port=None)
                server_recipient.addSite(site_recipient)

                async with server_owner.run(), server_owner.gossip.run(), \
                        server_recipient.run(), server_recipient.gossip.run():
                    await server_recipient.host.connect(
                        PeerInfo(server_owner.host.peer_id, server_owner.host.get_addrs())
                    )
                    server_owner.gossip.subscribeSite(site_owner)
                    server_recipient.gossip.subscribeSite(site_recipient)

                    with trio.fail_after(15):
                        while not server_owner.gossip._gossipsub.mesh.get(
                            server_owner.gossip.topicFor(address)
                        ):
                            await trio.sleep(0.1)

                    await publishGossip(site_owner, server_owner.gossip)

                    with trio.fail_after(10):
                        while "files" not in site_recipient.content_manager.contents.get("content.json", {}):
                            await trio.sleep(0.1)

                    return site_recipient.content_manager.contents.get("content.json")

        cached = compat.run(scenario)
        assert cached.get("privatekey") is None
        assert "index.html" in cached["files"]
