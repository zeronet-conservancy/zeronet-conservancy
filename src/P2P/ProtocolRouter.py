"""Maps a libp2p protocol ID to an async handler and wires it into a Host.

Replaces FileRequest.route()'s single cmd -> action* dispatch table: each
ZeroNet command becomes its own libp2p protocol ID with its own handler
module under protocols/, registered here instead of branched on in one
big connection-level switch.
"""
import logging

from . import wire

logger = logging.getLogger(__name__)


class ProtocolRouter:
    def __init__(self, host):
        self._host = host
        self._handlers = {}

    def register(self, protocol_id, handler):
        """handler: async def handler(params: dict) -> dict, ported from a
        FileRequest.action* method's logic (business logic only, no gevent
        connection plumbing -- that's PeerSession's job from Phase 4 on).
        """
        self._handlers[protocol_id] = handler
        self._host.raw.set_stream_handler(protocol_id, self._make_stream_handler(protocol_id, handler))

    def _make_stream_handler(self, protocol_id, handler):
        async def stream_handler(stream):
            try:
                try:
                    params = await wire.read_msg(stream)
                    result = await handler(params)
                except Exception as err:
                    logger.exception("Protocol handler error for %s", protocol_id)
                    result = {"error": str(err)}
                await wire.respond(stream, result)
            except Exception:
                logger.exception("Stream handling error for %s", protocol_id)
            finally:
                await stream.close()

        return stream_handler


async def call(host, peer_id, protocol_id, params: dict) -> dict:
    """Client side: open a stream to peer_id for protocol_id, send params,
    return the single response message.
    """
    stream = await host.raw.new_stream(peer_id, [protocol_id])
    try:
        return await wire.request(stream, params)
    finally:
        await stream.close()
