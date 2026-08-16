import pathlib
import tempfile

from P2P.UserManager import UserManager
from P2P import compat


class TestP2PUserManager:
    def testSingleUserModeIgnoresMasterAddressAndReturnsFirst(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                manager = UserManager(pathlib.Path(d))
                first = manager.create()
                manager.create()  # A second user exists, but single-user mode never sees it
                return await manager.get("some-other-address"), first.master_address

        resolved, first_address = compat.run(scenario)
        assert resolved.master_address == first_address

    def testMultiuserModeResolvesByMasterAddressAndIsolatesAccounts(self):
        """The core primitive plugins/disabled-Multiuser/UserPlugin.py's
        own get() override provided -- folded into core here (see
        UserManager.py's own module docstring for why a separate plugin
        package isn't earning its complexity for this one branch). The
        cookie-to-websocket-session wiring this needs to actually matter
        (resolving a browser's own master_address from a cookie into a
        specific connection) landed separately -- see
        UiServer.py's own _ensureMultiuserCookie()/UiSession docstrings
        and TestP2PUiMultiuser.py for the end-to-end proof; this file
        stays focused on the primitive itself, standalone."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                manager = UserManager(pathlib.Path(d), multiuser=True)
                alice = manager.create()
                bob = manager.create()
                return (
                    await manager.get(alice.master_address),
                    await manager.get(bob.master_address),
                    await manager.get("1UnknownAddressNeverCreatedXXXXX"),
                    await manager.get(None),
                )

        resolved_alice, resolved_bob, resolved_unknown, resolved_none = compat.run(scenario)
        assert resolved_alice is not None
        assert resolved_bob is not None
        assert resolved_alice.master_address != resolved_bob.master_address
        assert resolved_unknown is None
        assert resolved_none is None

    def testMultiuserAccountsPersistAndReloadByAddress(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                manager = UserManager(data_dir, multiuser=True)
                created = manager.create()
                created.markDirty()
                await created.save()

                reloaded = UserManager(data_dir, multiuser=True)
                await reloaded.load()
                return created.master_address, await reloaded.get(created.master_address)

        master_address, resolved = compat.run(scenario)
        assert resolved is not None
        assert resolved.master_address == master_address
