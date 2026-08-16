"""Async replacement for Peer/Peer.py's public API, backed by PeerSession
instead of Connection. Scoped to the commands that have protocol handlers
so far (ping, getFile, pex, update) -- listModified/getHashfield/
setHashfield/findHashIds land as their protocols/*.py handlers do;
request() already returns a clean {"error": "Unknown command: ..."} for
anything not yet registered, so adding them later doesn't require
changing this file's shape.

streamFile (chunked raw-stream transfer) is still deferred per Phase 2's
scoping note in protocols/getfile.py -- getFile here mirrors the original
non-streaming read loop (location/read_bytes/zlib decompression), which is
the part getfile.py actually implements.
"""
import io
import zlib

from .ConnectionPolicy import ConnectionPolicy
from .PeerSession import PeerSession

MAX_READ_SIZE = 512 * 1024


class Peer:
    def __init__(self, peer_id, host, connection_policy: ConnectionPolicy):
        self.peer_id = peer_id
        self.host = host
        self._connection_policy = connection_policy
        self.reputation = 0

    @property
    def _session(self) -> PeerSession:
        return self._connection_policy.getSession(self.peer_id)

    async def request(self, cmd: str, params: dict | None = None) -> dict:
        return await self._session.request(cmd, params)

    async def ping(self) -> bool:
        return await self._session.ping()

    async def getFile(self, site: str, inner_path: str, file_size: int | None = None,
                       pos_from: int = 0, pos_to: int | None = None) -> io.BytesIO:
        read_bytes = min(MAX_READ_SIZE, pos_to - pos_from) if pos_to else MAX_READ_SIZE
        location = pos_from
        buff = io.BytesIO()

        while True:
            res = await self.request("getFile", {
                "site": site,
                "inner_path": inner_path,
                "location": location,
                "read_bytes": read_bytes,
                "file_size": file_size,
                "compression": "zlib",
            })
            if not res or "location" not in res:
                raise ConnectionError("getFile failed: %s" % (res or {}).get("error", "no response"))

            if res.get("compression") == "zlib":
                buff.write(zlib.decompress(res["body"]))
            else:
                buff.write(res["body"])

            if res["location"] == res["size"] or res["location"] == pos_to:
                break
            location = res["location"]
            if pos_to:
                read_bytes = min(MAX_READ_SIZE, pos_to - location)

        buff.seek(0)
        return buff

    async def pex(self, site_address: str, my_peers: list, need_num: int = 5) -> list:
        from .protocols import pex as pex_protocol
        return await pex_protocol.request(self.host, self.peer_id, site_address, my_peers, need_num)

    async def getPiecefields(self, site_address: str) -> dict:
        from .protocols import piecefields
        return await piecefields.request(self.host, self.peer_id, site_address)

    async def pushUpdate(self, site_address: str, inner_path: str, body: bytes) -> dict:
        """Pushes a content.json update to this peer -- see
        protocols/update.py for the receiving side."""
        return await self.request("update", {"site": site_address, "inner_path": inner_path, "body": body})
