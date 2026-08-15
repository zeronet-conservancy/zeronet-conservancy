"""Peer exchange protocol handler, port of FileRequest.actionPex/Peer.pex().

Wire format: {"peer_id": str (base58), "ip": str, "port": int} per peer,
not just {"ip", "port"}. This isn't the same simplification as dropping the
old packed-binary address encoding -- it's load-bearing: libp2p's
host.connect() needs a peer_id up front to authenticate the Noise
handshake, it can't dial a bare ip:port the way the old raw-socket
transport could. A peer_id-less exchange format would produce addresses
nothing could actually connect to. (kad-dht doesn't have this problem --
find_providers() already returns full PeerInfo with peer_id baked in.)

Business logic only, like protocols/getfile.py: site/peer bookkeeping
(addPeer, worker_manager.onPeers) lives on the Site object -- Phase 6 is
building that now. known_peers_provider and peer_received_callback are the
injection points, same shape as getfile.py's site_root_resolver.
"""
from libp2p.peer.id import ID

PROTOCOL_ID = "/zeronet/pex/1.0.0"


def _decode_peer_id(raw: str) -> ID | None:
    try:
        return ID.from_base58(raw)
    except Exception:
        return None


def make_handler(known_peers_provider, peer_received_callback):
    """known_peers_provider(site_address, exclude, limit) -> list[{"peer_id", "ip", "port"}]
    peer_received_callback(site_address, peer_id: ID, ip, port) -> None,
    called once per peer the requester told us about (skips entries with an
    unparseable peer_id rather than failing the whole exchange).
    """

    async def handle(params: dict) -> dict:
        site_address = params["site"]
        their_peers = params.get("peers", [])
        need = params.get("need", 5)

        seen_ids = set()
        for peer in their_peers:
            peer_id = _decode_peer_id(peer.get("peer_id", ""))
            if peer_id is None:
                continue
            seen_ids.add(peer_id)
            peer_received_callback(site_address, peer_id, peer["ip"], peer["port"])

        back_peers = known_peers_provider(site_address, seen_ids, need)
        return {"peers": back_peers}

    return handle


async def request(host, peer_id, site_address: str, my_peers: list, need_num: int = 5) -> list:
    """Client side: exchange our known peers for theirs.

    my_peers: list of {"peer_id": str, "ip": str, "port": int}
    """
    from ..ProtocolRouter import call

    response = await call(host, peer_id, PROTOCOL_ID, {
        "site": site_address,
        "peers": my_peers,
        "need": need_num,
    })
    if "error" in response:
        return []
    return response.get("peers", [])
