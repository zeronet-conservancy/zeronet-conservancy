"""Port of FileRequest.actionPing."""
PROTOCOL_ID = "/zeronet/ping/1.0.0"


async def handle(params: dict) -> dict:
    return {"body": b"Pong!"}
