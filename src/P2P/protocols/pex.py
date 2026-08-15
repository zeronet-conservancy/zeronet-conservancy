"""Peer exchange protocol handler, port of FileRequest.actionPex/Peer.pex().

Wire format simplified for the clean-break protocol: a plain list of
{"ip": str, "port": int} dicts instead of the old packed-binary-address
encoding (helper.packPeers/unpackAddress), which existed to keep the old
msgpack payload compact -- not needed here, and structured data is easier
to extend (e.g. an "onion" field) later than a fixed binary layout.

Business logic only, like protocols/getfile.py: site/peer bookkeeping
(addPeer, worker_manager.onPeers) lives on the gevent Site object that
doesn't exist in this package until Phase 6 -- known_peers_provider and
peer_received_callback are the injection points for that, same shape as
getfile.py's site_root_resolver.
"""
PROTOCOL_ID = "/zeronet/pex/1.0.0"


def make_handler(known_peers_provider, peer_received_callback):
    """known_peers_provider(site_address, exclude, limit) -> list[{"ip", "port"}]
    peer_received_callback(site_address, ip, port) -> None, called once per
    peer the requester told us about.
    """

    async def handle(params: dict) -> dict:
        site_address = params["site"]
        their_peers = params.get("peers", [])
        need = params.get("need", 5)

        for peer in their_peers:
            peer_received_callback(site_address, peer["ip"], peer["port"])

        exclude = {(peer["ip"], peer["port"]) for peer in their_peers}
        back_peers = known_peers_provider(site_address, exclude, need)
        return {"peers": back_peers}

    return handle


async def request(host, peer_id, site_address: str, my_peers: list, need_num: int = 5) -> list:
    """Client side: exchange our known peers for theirs."""
    from ..ProtocolRouter import call

    response = await call(host, peer_id, PROTOCOL_ID, {
        "site": site_address,
        "peers": my_peers,
        "need": need_num,
    })
    if "error" in response:
        return []
    return response.get("peers", [])
