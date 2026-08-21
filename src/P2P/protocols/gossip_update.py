"""Gossipsub side of content.json propagation: a topic validator plus a
per-site consumer loop, both sharing update.py's applyContentUpdate() so
gossiped and directly-pushed updates go through identical validation and
write logic -- no duplicated verify/apply code between the two transports.

Unlike update.py's RPC handler, there's no site_resolver here: gossipsub
topics are already per-site (see GossipManager.topicFor()), so
GossipManager knows exactly which site a subscription belongs to at
subscribe time and passes it straight through -- make_validator/consume
just close over that site object.
"""
import json

from . import update


def make_validator(site):
    """Sync validator for Pubsub.set_topic_validator(topic, validator,
    is_async_validator=False). verifyContentJson() is pure CPU/in-memory
    (no I/O, never awaits), so a sync validator is safe and avoids the
    async validator path's own timeout/nursery machinery for no benefit.

    Accept/reject only -- must not write anything; writing happens in
    consume() below, after gossipsub has already accepted and started
    forwarding the message to the mesh. Accepts both a genuine update and
    the benign "already have this, not updated" case: only a real
    validation failure (bad JSON, bad signature, stale/future timestamp,
    ...) should stop propagation. A stale-but-otherwise-valid message
    isn't spam, so it shouldn't be treated as one -- e.g. it could still
    be someone else's first time seeing it.
    """

    def validate(peer_id, msg) -> bool:
        try:
            content = json.loads(msg.data.decode("utf8"))
        except Exception:
            return False
        try:
            site.content_manager.verifyContentJson(content, inner_path="content.json")
        except Exception:
            return False
        return True

    return validate


async def consume(site, subscription, on_applied=None) -> None:
    """Runs for the lifetime of a site's gossipsub subscription (spawned
    by GossipManager._subscribe), applying each message the validator
    already accepted the same way update.py's unicast handler would."""
    async for msg in subscription:
        try:
            await update.applyContentUpdate(site, "content.json", msg.data, on_applied=on_applied)
        except update.ContentUpdateError:
            # The validator already rejected anything invalid before this
            # message was ever delivered here -- a failure at this point
            # means the content changed between validation and delivery
            # (e.g. a race with a concurrent unicast update). Drop it and
            # keep consuming; the mesh will deliver the next real update.
            continue
