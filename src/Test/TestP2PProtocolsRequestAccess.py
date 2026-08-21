import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from Crypt import CryptBitcoin, CryptEcies
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.FileServer import FileServer
from P2P.Peer import Peer
from P2P.Site import Site
from P2P.SiteManager import SiteManager
from P2P import compat


class TestP2PRequestAccessProtocol:
    """Real end-to-end proof that a private-site access request delivered
    over protocols/request_access.py's wire push (Peer.requestAccess())
    lands in the owner's own SiteManager settings as a pending request --
    the delivery half of the "no out-of-band relay" design, sibling to
    protocols/update.py's own unicast-push coverage in TestP2PUpdate.py."""

    def testRequestAccessStoresPendingRequestOnOwnerNode(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        requester_privatekey = CryptBitcoin.newPrivatekey()
        requester_address = CryptBitcoin.privatekeyToAddress(requester_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, requester_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as owner_site_dir, tempfile.TemporaryDirectory() as owner_users_dir:
                site_owner = Site(address, pathlib.Path(owner_site_dir))
                server_owner = FileServer(pathlib.Path(da), ws_port=None)
                server_owner.addSite(site_owner)
                site_manager = SiteManager(pathlib.Path(owner_users_dir))
                site_manager.add(address, own=True)
                server_owner.site_manager = site_manager

                host_requester = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_owner.run(), host_requester.run():
                    await host_requester.connect(PeerInfo(server_owner.host.peer_id, server_owner.host.get_addrs()))
                    peer = Peer(server_owner.host.peer_id, host_requester, ConnectionPolicy(host_requester))
                    reply = await peer.requestAccess(address, requester_address, signature)
                    pending = site_manager.getSiteSetting(address, "private_pending_requests", {})
                    return reply, pending

        reply, pending = compat.run(scenario)
        assert "error" not in reply
        assert reply["stored_by_owner"] is True
        assert requester_address in pending
        assert pending[requester_address]["signature"] == signature

    def testRequestAccessRelaysWhenNodeDoesNotOwnSite(self):
        """A serving-but-not-owning node (FileServer always wires a real
        RequestAccessRelay in -- see FileServer.py's own comment) accepts
        and holds the request instead of rejecting it, so it can be
        carried onward and re-offered to other peers later (Worker
        Manager.forwardPendingAccessRequests(), exercised end-to-end in
        testForwardPendingAccessRequestsDeliversToOwner below) -- the
        "owner is offline right now" half of this protocol's design."""
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        requester_privatekey = CryptBitcoin.newPrivatekey()
        requester_address = CryptBitcoin.privatekeyToAddress(requester_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, requester_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as owner_site_dir, tempfile.TemporaryDirectory() as owner_users_dir:
                # Serving the site (e.g. relaying it) without owning it --
                # site_manager has no own=True entry for this address.
                site = Site(address, pathlib.Path(owner_site_dir))
                server = FileServer(pathlib.Path(da), ws_port=None)
                server.addSite(site)
                server.site_manager = SiteManager(pathlib.Path(owner_users_dir))

                host_requester = FileServer(pathlib.Path(db), ws_port=None).host

                async with server.run(), host_requester.run():
                    await host_requester.connect(PeerInfo(server.host.peer_id, server.host.get_addrs()))
                    peer = Peer(server.host.peer_id, host_requester, ConnectionPolicy(host_requester))
                    reply = await peer.requestAccess(address, requester_address, signature)
                    relayed = server.request_access_relay.getAll(address)
                    return reply, relayed

        reply, relayed = compat.run(scenario)
        assert "error" not in reply
        assert reply["stored_by_owner"] is False
        assert relayed[requester_address]["signature"] == signature

    def testRequestAccessHandlerRejectsWithNoRelayConfigured(self):
        """Unit-level coverage of make_handler()'s own fallback reject
        path, for a hypothetical caller that wires site_manager but not a
        relay -- FileServer itself always wires both together in
        production (see FileServer.py's own comment), so this bypasses
        FileServer/the real wire entirely to exercise the branch
        directly."""
        from P2P.protocols import request_access

        address = "1TestSiteAddrAAAAAAAAAAAAAAAA"
        requester_privatekey = CryptBitcoin.newPrivatekey()
        requester_address = CryptBitcoin.privatekeyToAddress(requester_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, requester_privatekey)

        class _FakeSite:
            def __init__(self, addr):
                self.address = addr

        class _NotOwnerSiteManager:
            def isOwn(self, addr):
                return False

        handler = request_access.make_handler(
            lambda addr: _FakeSite(addr) if addr == address else None,
            lambda: _NotOwnerSiteManager(),
        )

        async def scenario():
            return await handler({"site": address, "auth_address": requester_address, "signature": signature})

        reply = compat.run(scenario)
        assert reply["error"] == "Not the owner of this site"

    def testForwardPendingAccessRequestsDeliversToOwner(self):
        """End-to-end: a request lands on a bystander (not the owner) via
        the wire protocol, gets held in that node's RequestAccessRelay,
        and WorkerManager.forwardPendingAccessRequests() re-pushes it to
        the real owner's node -- which stores it durably and drops the
        bystander's now-redundant copy, closing the loop this whole
        design exists for."""
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        requester_privatekey = CryptBitcoin.newPrivatekey()
        requester_address = CryptBitcoin.privatekeyToAddress(requester_privatekey)
        _, signature = CryptEcies.signAccessRequest(address, requester_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as dc, tempfile.TemporaryDirectory() as dd, \
                    tempfile.TemporaryDirectory() as owner_site_dir, tempfile.TemporaryDirectory() as bystander_site_dir, \
                    tempfile.TemporaryDirectory() as owner_users_dir:
                from P2P.WorkerManager import forwardPendingAccessRequests

                site_owner = Site(address, pathlib.Path(owner_site_dir))
                server_owner = FileServer(pathlib.Path(da), ws_port=None)
                server_owner.addSite(site_owner)
                owner_site_manager = SiteManager(pathlib.Path(owner_users_dir))
                owner_site_manager.add(address, own=True)
                server_owner.site_manager = owner_site_manager

                # Bystander: serves the same site, doesn't own it.
                site_bystander = Site(address, pathlib.Path(bystander_site_dir))
                server_bystander = FileServer(pathlib.Path(db), ws_port=None)
                server_bystander.addSite(site_bystander)
                server_bystander.site_manager = SiteManager(pathlib.Path(dc))

                host_requester = FileServer(pathlib.Path(dd), ws_port=None).host

                async with server_owner.run(), server_bystander.run(), host_requester.run():
                    # 1. Requester -> bystander (owner not connected/known yet)
                    await host_requester.connect(
                        PeerInfo(server_bystander.host.peer_id, server_bystander.host.get_addrs())
                    )
                    peer_bystander = Peer(
                        server_bystander.host.peer_id, host_requester, ConnectionPolicy(host_requester),
                    )
                    first_reply = await peer_bystander.requestAccess(address, requester_address, signature)

                    # 2. Bystander later connects to the real owner and
                    # forwards whatever it's holding.
                    await server_bystander.host.connect(
                        PeerInfo(server_owner.host.peer_id, server_owner.host.get_addrs())
                    )
                    peer_owner = Peer(
                        server_owner.host.peer_id, server_bystander.host, server_bystander.connection_policy,
                    )
                    forwarded = await forwardPendingAccessRequests(
                        site_bystander, [peer_owner], server_bystander.request_access_relay,
                    )

                    owner_pending = owner_site_manager.getSiteSetting(address, "private_pending_requests", {})
                    bystander_relay_after = server_bystander.request_access_relay.getAll(address)
                    return first_reply, forwarded, owner_pending, bystander_relay_after

        first_reply, forwarded, owner_pending, bystander_relay_after = compat.run(scenario)
        assert first_reply["stored_by_owner"] is False
        assert forwarded == 1
        assert owner_pending[requester_address]["signature"] == signature
        assert bystander_relay_after == {}  # dropped once confirmed delivered to the owner

    def testRequestAccessRejectsMismatchedSignature(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        requester_privatekey = CryptBitcoin.newPrivatekey()
        requester_address = CryptBitcoin.privatekeyToAddress(requester_privatekey)
        other_privatekey = CryptBitcoin.newPrivatekey()
        # Signature is real, but produced by a DIFFERENT key than the
        # claimed requester_address.
        _, wrong_signature = CryptEcies.signAccessRequest(address, other_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as owner_site_dir, tempfile.TemporaryDirectory() as owner_users_dir:
                site_owner = Site(address, pathlib.Path(owner_site_dir))
                server_owner = FileServer(pathlib.Path(da), ws_port=None)
                server_owner.addSite(site_owner)
                site_manager = SiteManager(pathlib.Path(owner_users_dir))
                site_manager.add(address, own=True)
                server_owner.site_manager = site_manager

                host_requester = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_owner.run(), host_requester.run():
                    await host_requester.connect(PeerInfo(server_owner.host.peer_id, server_owner.host.get_addrs()))
                    peer = Peer(server_owner.host.peer_id, host_requester, ConnectionPolicy(host_requester))
                    reply = await peer.requestAccess(address, requester_address, wrong_signature)
                    pending = site_manager.getSiteSetting(address, "private_pending_requests", {})
                    return reply, pending

        reply, pending = compat.run(scenario)
        assert "error" in reply
        assert pending == {}

    def testRequestAccessRejectsUnknownSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                server_owner = FileServer(pathlib.Path(da), ws_port=None)  # No sites added
                server_owner.site_manager = SiteManager(pathlib.Path(da) / "users")
                host_requester = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_owner.run(), host_requester.run():
                    await host_requester.connect(PeerInfo(server_owner.host.peer_id, server_owner.host.get_addrs()))
                    peer = Peer(server_owner.host.peer_id, host_requester, ConnectionPolicy(host_requester))
                    return await peer.requestAccess("1UnknownSiteAddressAAAAAAAAA", "1SomeRequesterAAAAAAAAAAAAA", "sig")

        reply = compat.run(scenario)
        assert reply["error"] == "Unknown site"
