"""Exchange native Bigfile piecefields for one site."""

PROTOCOL_ID = "/zeronet/piecefields/1.0.0"


def make_handler(piecefields_provider):
    async def handle(params: dict) -> dict:
        return {"piecefields": await piecefields_provider(params["site"])}
    return handle


async def request(host, peer_id, site_address: str) -> dict:
    from ..ProtocolRouter import call

    response = await call(host, peer_id, PROTOCOL_ID, {"site": site_address})
    if "error" in response:
        return {}
    return response.get("piecefields", {})
