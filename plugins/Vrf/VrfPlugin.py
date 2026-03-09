import hashlib
import json
import ssl
import time
import urllib.request

from Config import config
from Plugin import PluginManager

# Beacon cache: height -> {beacon_hex, proposer, timestamp, cached_at}
_beacon_cache = {}
BEACON_CACHE_TTL = 300  # 5 min (beacons are immutable once produced)

# Latest beacon cache
_latest_beacon_cache = {"data": None, "cached_at": 0}
LATEST_BEACON_CACHE_TTL = 6  # 6 sec (new beacon every block)


def _get_rpc_url():
    """Get the chain REST API base URL for VRF queries."""
    return getattr(config, "chain_rpc_url", "https://api.epix.zone").rstrip("/")


def _fetch_json(url, timeout=10):
    """Fetch JSON from a URL."""
    ssl_ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        import logging
        logging.getLogger("VrfPlugin").error("Fetch %s failed: %s", url, e)
        return None


def _fetch_beacon(height):
    """Fetch the random beacon for a specific block height."""
    now = time.time()

    # Check cache
    cached = _beacon_cache.get(height)
    if cached and (now - cached["cached_at"]) < BEACON_CACHE_TTL:
        return cached

    rpc_url = _get_rpc_url()
    data = _fetch_json("%s/vrf/v1/beacon/%d" % (rpc_url, height))
    if not data or "beacon" not in data:
        return None

    beacon_data = data["beacon"]
    result = {
        "height": int(beacon_data.get("height", height)),
        "beacon": beacon_data.get("beacon", ""),
        "proposer": beacon_data.get("proposer", ""),
        "timestamp": int(beacon_data.get("timestamp", 0)),
        "cached_at": now,
    }

    _beacon_cache[height] = result
    return result


def _fetch_latest_beacon():
    """Fetch the most recent random beacon."""
    global _latest_beacon_cache
    now = time.time()

    # Check cache
    if _latest_beacon_cache["data"] and (now - _latest_beacon_cache["cached_at"]) < LATEST_BEACON_CACHE_TTL:
        return _latest_beacon_cache["data"]

    rpc_url = _get_rpc_url()
    data = _fetch_json("%s/vrf/v1/beacon/latest" % rpc_url)
    if not data or "beacon" not in data:
        return None

    beacon_data = data["beacon"]
    result = {
        "height": int(beacon_data.get("height", 0)),
        "beacon": beacon_data.get("beacon", ""),
        "proposer": beacon_data.get("proposer", ""),
        "timestamp": int(beacon_data.get("timestamp", 0)),
    }

    # Also populate the per-height cache
    _beacon_cache[result["height"]] = dict(result, cached_at=now)

    _latest_beacon_cache = {"data": result, "cached_at": now}
    return result


def _derive_random_values(beacon_hex, seed, count):
    """Derive N deterministic random values from a beacon + seed.

    Each value = SHA256(beacon || seed || index) as 64-char hex.
    Deterministic: same beacon + seed + index always produces same output.
    """
    values = []
    for i in range(count):
        h = hashlib.sha256()
        h.update(beacon_hex.encode("utf-8"))
        h.update(seed.encode("utf-8"))
        h.update(str(i).encode("utf-8"))
        values.append(h.hexdigest())
    return values


@PluginManager.registerTo("UiWebsocket")
class UiWebsocketPlugin(object):

    def actionVrfGetBeacon(self, to, block_height):
        """Get the random beacon for a specific block height.

        Returns: {height, beacon, proposer, timestamp} or error
        """
        try:
            block_height = int(block_height)
        except (TypeError, ValueError):
            self.response(to, {"error": "Invalid block_height"})
            return

        if block_height <= 0:
            self.response(to, {"error": "block_height must be positive"})
            return

        result = _fetch_beacon(block_height)
        if not result:
            self.response(to, {"error": "Beacon not found for height %d" % block_height})
            return

        self.response(to, {
            "height": result["height"],
            "beacon": result["beacon"],
            "proposer": result["proposer"],
            "timestamp": result["timestamp"],
        })

    def actionVrfLatestBeacon(self, to):
        """Get the most recent random beacon.

        Returns: {height, beacon, proposer, timestamp} or error
        """
        result = _fetch_latest_beacon()
        if not result:
            self.response(to, {"error": "Failed to fetch latest beacon"})
            return

        self.response(to, {
            "height": result["height"],
            "beacon": result["beacon"],
            "proposer": result["proposer"],
            "timestamp": result["timestamp"],
        })

    def actionVrfDeriveRandom(self, to, block_height=0, seed="", count=1):
        """Derive deterministic random values from a beacon + seed.

        Args:
            block_height: Block height to use (0 = latest beacon)
            seed: Application-specific seed string (e.g. "my-raffle-2026")
            count: Number of random values to derive (1-100)

        Returns: {height, beacon, values: [hex strings]} or error
        """
        try:
            block_height = int(block_height)
            count = int(count)
        except (TypeError, ValueError):
            self.response(to, {"error": "Invalid parameters"})
            return

        if count < 1 or count > 100:
            self.response(to, {"error": "count must be between 1 and 100"})
            return

        # Fetch beacon
        if block_height <= 0:
            result = _fetch_latest_beacon()
        else:
            result = _fetch_beacon(block_height)

        if not result:
            self.response(to, {"error": "Beacon not found"})
            return

        beacon_hex = result["beacon"]
        if not beacon_hex:
            self.response(to, {"error": "Empty beacon"})
            return

        values = _derive_random_values(beacon_hex, str(seed), count)

        self.response(to, {
            "height": result["height"],
            "beacon": beacon_hex,
            "values": values,
        })

    def actionVrfMultiBlockBeacon(self, to, end_height, blocks=25):
        """Get a combined beacon from N consecutive blocks.

        Hashes together beacons from end_height-blocks+1 through end_height,
        so every block proposer in the range contributes entropy. To manipulate
        the result, ALL proposers across all N blocks would need to collude.

        Args:
            end_height: Last block height in the range
            blocks: Number of consecutive blocks to combine (1-256, default 25)

        Returns: {end_height, blocks, beacon} or error
        """
        try:
            end_height = int(end_height)
            blocks = int(blocks)
        except (TypeError, ValueError):
            self.response(to, {"error": "Invalid parameters"})
            return

        if blocks < 1 or blocks > 256:
            self.response(to, {"error": "blocks must be between 1 and 256"})
            return
        if end_height < blocks:
            self.response(to, {"error": "end_height must be >= blocks"})
            return

        start_height = end_height - blocks + 1

        # Fetch and hash all beacons in the range
        h = hashlib.sha256()
        for height in range(start_height, end_height + 1):
            result = _fetch_beacon(height)
            if not result or not result.get("beacon"):
                self.response(to, {"error": "Beacon not found for height %d" % height})
                return
            h.update(result["beacon"].encode("utf-8"))

        self.response(to, {
            "end_height": end_height,
            "blocks": blocks,
            "beacon": h.hexdigest(),
        })

    def actionVrfInvalidateCache(self, to):
        """Clear all VRF beacon caches."""
        global _latest_beacon_cache
        _beacon_cache.clear()
        _latest_beacon_cache = {"data": None, "cached_at": 0}
        self.response(to, "ok")

