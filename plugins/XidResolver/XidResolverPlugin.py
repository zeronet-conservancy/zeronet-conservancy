import logging
import json
import re
import time

from Config import config
from Plugin import PluginManager

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

allow_reload = False

log = logging.getLogger("XidResolverPlugin")

# In-memory cache: peer_address -> {name, tld, owner, active, revoked_at, cached_at}
_peer_cache = {}

# How long to cache positive results (seconds)
PEER_CACHE_TTL = 300  # 5 minutes
# How long to cache negative (not found) results
NEGATIVE_CACHE_TTL = 60  # 1 minute


def _get_rpc_url():
    """Get the xID REST API base URL."""
    return getattr(config, "xid_rpc_url", "https://api.testnet.epix.zone").rstrip("/")


def _fetch_json(url, timeout=10):
    """Fetch JSON from a URL, return parsed dict or None on error."""
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        resp = urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except (URLError, ValueError, IOError) as e:
        log.debug("xID RPC fetch failed for %s: %s" % (url, e))
        return None


def resolve_peer_xid(peer_address):
    """Resolve an EpixNet peer address to its xID name.

    Returns dict with {name, tld, owner, active, revoked_at} or None if not found.
    Results are cached with TTL to avoid repeated API calls.
    """
    now = time.time()

    # Check cache
    cached = _peer_cache.get(peer_address)
    if cached:
        ttl = PEER_CACHE_TTL if cached.get("name") else NEGATIVE_CACHE_TTL
        if (now - cached["cached_at"]) < ttl:
            if cached.get("name"):
                return {
                    "name": cached["name"],
                    "tld": cached["tld"],
                    "owner": cached["owner"],
                    "active": cached["active"],
                    "revoked_at": cached["revoked_at"],
                }
            return None

    # Cache miss — query the chain
    rpc_url = _get_rpc_url()
    data = _fetch_json("%s/xid/v1/reverse_peer/%s" % (rpc_url, peer_address))

    if data and data.get("name_record"):
        record = data["name_record"]
        peer_info = data.get("peer", {})
        entry = {
            "name": record.get("name", ""),
            "tld": record.get("tld", ""),
            "owner": record.get("owner", ""),
            "active": peer_info.get("active", True),
            "revoked_at": int(peer_info.get("revoked_at", 0)),
            "cached_at": now,
        }
        _peer_cache[peer_address] = entry
        return {
            "name": entry["name"],
            "tld": entry["tld"],
            "owner": entry["owner"],
            "active": entry["active"],
            "revoked_at": entry["revoked_at"],
        }
    else:
        # Negative cache
        _peer_cache[peer_address] = {"name": None, "cached_at": now}
        return None


def invalidate_peer_cache(peer_address=None):
    """Invalidate cache for a specific peer or all peers."""
    if peer_address:
        _peer_cache.pop(peer_address, None)
    else:
        _peer_cache.clear()


@PluginManager.registerTo("ContentManager")
class ContentManagerPlugin(object):

    def sign(self, inner_path="content.json", privatekey=None, filewrite=True,
             update_changed_files=False, extend=None, remove_missing_optional=False):
        """Check peer revocation status before signing user content.

        Old messages from revoked peers remain valid — we only block NEW signing.
        """
        from Content.ContentManager import SignError

        # Only check for user content directories (e.g. data/users/<address>/content.json)
        if "users/" in inner_path:
            match = re.search(r"users/([A-Za-z0-9]+)/", inner_path)
            if match:
                user_address = match.group(1)
                xid_info = resolve_peer_xid(user_address)
                if xid_info and not xid_info["active"]:
                    raise SignError(
                        "Your xID peer key has been revoked (revoked at block %s). "
                        "You cannot post new content with a revoked key." % xid_info["revoked_at"]
                    )

        return super(ContentManagerPlugin, self).sign(
            inner_path, privatekey, filewrite,
            update_changed_files, extend, remove_missing_optional
        )


@PluginManager.registerTo("UiWebsocket")
class UiWebsocketPlugin(object):

    def actionXidResolve(self, to, peer_address):
        """Resolve an EpixNet peer address to its xID name.

        If the address matches the current user's site auth_address, also tries
        the user's other known addresses (master + all site auth_addresses).
        Returns {name, tld, owner, active, revoked_at} or null.
        """
        # Try the passed-in address first
        result = resolve_peer_xid(peer_address)
        if result:
            self.response(to, result)
            return

        # If the address is the current user's auth for this site, try other addresses
        if hasattr(self, "user") and self.user:
            current_auth = self.user.getAuthAddress(self.site.address, create=False)
            if peer_address == current_auth:
                # Try master_address and all other site auth_addresses
                tried = {peer_address}
                master = getattr(self.user, "master_address", None)
                if master and master not in tried:
                    tried.add(master)
                    result = resolve_peer_xid(master)
                    if result:
                        self.response(to, result)
                        return
                for site_data in self.user.sites.values():
                    auth = site_data.get("auth_address")
                    if auth and auth not in tried:
                        tried.add(auth)
                        result = resolve_peer_xid(auth)
                        if result:
                            self.response(to, result)
                            return

        self.response(to, None)

    def actionXidResolveBatch(self, to, peer_addresses):
        """Batch resolve multiple peer addresses to xID names.

        Takes a list of peer addresses (max 50), returns a dict of address -> result.
        """
        if not isinstance(peer_addresses, list):
            return self.response(to, {"error": "peer_addresses must be a list"})

        results = {}
        for addr in peer_addresses[:50]:
            results[addr] = resolve_peer_xid(addr)
        self.response(to, results)

    def actionXidInvalidateCache(self, to, peer_address=None):
        """Invalidate the xID peer cache (for a specific address or all)."""
        invalidate_peer_cache(peer_address)
        self.response(to, "ok")


@PluginManager.registerTo("ConfigPlugin")
class ConfigPlugin(object):
    def createArguments(self):
        group = self.parser.add_argument_group("xID Resolver plugin")
        group.add_argument(
            '--xid-rpc-url',
            help='Epix Chain REST API URL for xID peer resolution',
            default='https://api.testnet.epix.zone',
            metavar='url'
        )
        return super(ConfigPlugin, self).createArguments()
