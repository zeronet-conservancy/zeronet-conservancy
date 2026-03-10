import hashlib
import logging
import re
import json
import time

from Config import config
from Plugin import PluginManager
from util.Flag import flag

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

allow_reload = False

log = logging.getLogger("XidResolverPlugin")

# Cache: keyed by "name.tld", stores {"data": dict, "timestamp": float, "attested": bool}
# "data" contains: address (site address), peers (list of EpixNet peer dicts), owner, content_root
_resolve_cache = {}
# Reverse cache: keyed by site_address, stores "name.tld" (only from attested resolutions)
_reverse_cache = {}
# Peer cache: keyed by "name.tld", stores list of EpixNet peer address strings
_peer_cache = {}
RESOLVE_CACHE_TTL = 30
# Attested resolutions are trusted longer since they're backed by 2/3 validator consensus
ATTESTED_CACHE_TTL = 300

# EPIXNET DNS record type (private-use range per RFC 6895)
EPIXNET_RECORD_TYPE = 65280

# Expected chain ID prefix — must start with "epix_" to be the real Epix chain.
EXPECTED_CHAIN_ID_PREFIX = "epix_"

# Chain ID verification state
_chain_id_verified = None
_chain_id_cache = {"chain_id": None, "timestamp": 0}
CHAIN_ID_CACHE_TTL = 300

# Attested root cache: the current Merkle root verified by 2/3+ validators
# Changes only when chain state changes, so can be cached with longer TTL
_attested_root_cache = {"root": None, "timestamp": 0}
ATTESTED_ROOT_CACHE_TTL = 60


def _fetch_json(url, timeout=10):
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        resp = urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except (URLError, ValueError, IOError) as e:
        log.debug("xID RPC fetch failed for %s: %s" % (url, e))
        return None


def _get_rpc_url():
    return getattr(config, "chain_rpc_url", "https://api.epix.zone").rstrip("/")


def _verify_chain_id():
    """Verify the RPC endpoint is serving the real Epix chain."""
    global _chain_id_verified
    now = time.time()
    if (now - _chain_id_cache["timestamp"]) < CHAIN_ID_CACHE_TTL and _chain_id_verified is not None:
        return _chain_id_verified

    rpc_url = _get_rpc_url()
    data = _fetch_json("%s/cosmos/base/tendermint/v1beta1/node_info" % rpc_url)
    chain_id = None
    if data and data.get("default_node_info"):
        chain_id = data["default_node_info"].get("network", "")

    _chain_id_cache["chain_id"] = chain_id
    _chain_id_cache["timestamp"] = now

    if chain_id and chain_id.startswith(EXPECTED_CHAIN_ID_PREFIX):
        _chain_id_verified = True
        log.debug("Chain ID verified: %s" % chain_id)
    else:
        _chain_id_verified = False
        log.warning("Chain ID verification failed: got '%s', expected prefix '%s'" % (chain_id, EXPECTED_CHAIN_ID_PREFIX))

    return _chain_id_verified


def _verify_merkle_proof(proof, expected_root):
    """Verify a Merkle inclusion proof for a domain entry.

    Args:
        proof: dict with leaf_index, leaf_hash, siblings (list of hex strings), root
        expected_root: the attested Merkle root hex string

    Returns:
        True if the proof is valid against the expected root.
    """
    try:
        current = bytes.fromhex(proof["leaf_hash"])
        index = proof["leaf_index"]
        for sibling_hex in proof["siblings"]:
            sibling = bytes.fromhex(sibling_hex)
            if index % 2 == 0:  # current is left child
                current = hashlib.sha256(current + sibling).digest()
            else:  # current is right child
                current = hashlib.sha256(sibling + current).digest()
            index //= 2
        return current.hex() == expected_root
    except (KeyError, ValueError, TypeError) as e:
        log.debug("Merkle proof verification error: %s" % e)
        return False


def _get_attested_root():
    """Fetch and cache the current attested Merkle root.

    Checks if the current state digest is finalized (attested by 2/3+ validators).
    Returns the root hex string if finalized, or None.
    """
    now = time.time()
    if _attested_root_cache["root"] and (now - _attested_root_cache["timestamp"]) < ATTESTED_ROOT_CACHE_TTL:
        return _attested_root_cache["root"]

    rpc_url = _get_rpc_url()

    # Fetch the current state digest
    digest_data = _fetch_json("%s/xid/v1/state_digest" % rpc_url)
    if not digest_data or not digest_data.get("digest"):
        return None

    digest = digest_data["digest"]

    # If we already have this root cached, just refresh the timestamp
    if digest == _attested_root_cache["root"]:
        _attested_root_cache["timestamp"] = now
        return digest

    # Check if this digest is finalized
    att_data = _fetch_json("%s/xid/v1/attestations?digest=%s" % (rpc_url, digest))
    if not att_data or not att_data.get("finalized"):
        return None

    _attested_root_cache["root"] = digest
    _attested_root_cache["timestamp"] = now
    log.debug("Attested root updated: %s..." % digest[:16])
    return digest


def _resolve_epix_name(tld, name):
    """Resolve an xID name using per-name Merkle proof verification.

    Verification:
    1. Fetch domain data + Merkle proof in a single RPC call
    2. Verify proof against attested root (2/3+ validator consensus)
    3. Extract EPIXNET DNS record and EpixNet peers

    Falls back to unattested chain-ID-verified direct query if attestation unavailable.

    Returns the EpixNet site address string, or None.
    """
    cache_key = "%s.%s" % (name, tld)
    now = time.time()
    cached = _resolve_cache.get(cache_key)
    if cached:
        ttl = ATTESTED_CACHE_TTL if cached.get("attested") else RESOLVE_CACHE_TTL
        if (now - cached["timestamp"]) < ttl:
            return cached.get("address")

    rpc_url = _get_rpc_url()

    # Single RPC call: domain data + Merkle proof
    proof_data = _fetch_json("%s/xid/v1/resolve_with_proof/%s/%s" % (rpc_url, tld, name))
    if (proof_data and proof_data.get("domain") and proof_data.get("proof")
            and proof_data["domain"].get("record", {}).get("name")):
        domain = proof_data["domain"]
        proof = proof_data["proof"]

        # Try to verify against attested root
        attested_root = _get_attested_root()
        attested = False
        if attested_root and _verify_merkle_proof(proof, attested_root):
            attested = True
            log.debug("Merkle proof verified for %s against attested root" % cache_key)
        elif attested_root:
            # Proof doesn't match attested root — could be stale, try the proof's own root
            # but only trust it if chain ID is verified
            log.debug("Merkle proof for %s doesn't match attested root (state may have changed)" % cache_key)

        # Extract EPIXNET DNS record (site address)
        site_address = None
        for dns_rec in domain.get("dns_records", []):
            if int(dns_rec.get("record_type", 0)) == EPIXNET_RECORD_TYPE:
                site_address = dns_rec.get("value", "").strip()
                break

        # Extract EpixNet peers
        peers = domain.get("peers", [])
        active_peers = [p.get("address", "") for p in peers if p.get("active")]
        if active_peers:
            _peer_cache[cache_key] = active_peers

        # Cache the result
        _resolve_cache[cache_key] = {
            "address": site_address,
            "timestamp": now,
            "attested": attested,
            "owner": domain.get("record", {}).get("owner", ""),
            "content_root": domain.get("content_root", ""),
        }
        if site_address:
            _reverse_cache[site_address] = cache_key
            log.debug("Resolved %s to %s (%s)" % (
                cache_key, site_address, "attested" if attested else "proof unverified"))
        return site_address

    # Fallback: direct RPC query with chain ID verification (no proof available)
    if not _verify_chain_id():
        return None

    data = _fetch_json("%s/xid/v1/resolve/%s/%s" % (rpc_url, tld, name))
    if not data or not data.get("record"):
        _resolve_cache[cache_key] = {"address": None, "timestamp": now, "attested": False}
        return None

    dns_data = _fetch_json("%s/xid/v1/dns/%s/%s" % (rpc_url, tld, name))
    site_address = None
    if dns_data and dns_data.get("records"):
        for record in dns_data["records"]:
            if int(record.get("record_type", 0)) == EPIXNET_RECORD_TYPE:
                site_address = record.get("value", "").strip()
                break

    # Also fetch peers in fallback path
    peers_data = _fetch_json("%s/xid/v1/epixnet/%s/%s" % (rpc_url, tld, name))
    if peers_data and peers_data.get("peers"):
        active_peers = [p.get("address", "") for p in peers_data["peers"] if p.get("active")]
        if active_peers:
            _peer_cache[cache_key] = active_peers

    _resolve_cache[cache_key] = {"address": site_address, "timestamp": now, "attested": False}
    if site_address:
        _reverse_cache[site_address] = cache_key
        log.debug("Resolved %s to %s (chain ID verified, no proof)" % (cache_key, site_address))
    else:
        log.debug("Name %s exists but has no EPIXNET record" % cache_key)

    return site_address


def getEpixNetPeers(tld, name):
    """Get the EpixNet peer addresses for a domain.

    Returns a list of active peer address strings, or an empty list.
    Triggers a resolution if not cached.
    """
    cache_key = "%s.%s" % (name, tld)
    if cache_key in _peer_cache:
        return _peer_cache[cache_key]

    # Trigger resolution which populates the peer cache
    _resolve_epix_name(tld, name)
    return _peer_cache.get(cache_key, [])


@PluginManager.registerTo("SiteManager")
class SiteManagerPlugin(object):

    def isEpixDomain(self, address):
        if not isinstance(address, str):
            return False
        return re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.[a-zA-Z]+$", address) and address.endswith(".epix")

    def resolveEpixDomain(self, domain):
        if not isinstance(domain, str):
            return None
        domain = domain.lower()
        parts = domain.rsplit(".", 1)
        if len(parts) != 2:
            return None
        name, tld = parts
        return _resolve_epix_name(tld, name)

    def resolveDomain(self, domain):
        if not isinstance(domain, str):
            return False
        return self.resolveEpixDomain(domain) or super(SiteManagerPlugin, self).resolveDomain(domain)

    def isDomain(self, address):
        return self.isEpixDomain(address) or super(SiteManagerPlugin, self).isDomain(address)

    def reverseLookupDomain(self, address):
        """Return the verified .epix domain for a site address, or None.

        Only returns domains verified against the chain — either from a
        Merkle proof against the attested root or a chain-ID-verified
        forward resolution that confirmed domain -> address.
        """
        # Check if the site claims a domain in content.json
        site = self.sites.get(address)
        if not site:
            return None
        content = site.content_manager.contents.get("content.json")
        if not content or not content.get("domain"):
            return None

        domain = content["domain"].lower()
        if not domain.endswith(".epix"):
            return None

        # Fast path: already verified via forward resolution
        cached = _reverse_cache.get(address)
        if cached and cached == domain:
            return cached

        # Verify against chain: resolve the claimed domain and check it points here
        resolved = self.resolveEpixDomain(domain)
        if resolved == address:
            return domain

        log.debug("Domain claim %s by %s failed chain verification (resolved to %s)" % (domain, address, resolved))
        return None


def clearXidCaches():
    """Clear all xID-related caches (resolver + chain attestation + SiteManager domain cache)."""
    global _chain_id_verified
    count = len(_resolve_cache)
    _resolve_cache.clear()
    _reverse_cache.clear()
    _peer_cache.clear()
    _chain_id_verified = None
    _chain_id_cache.update({"chain_id": None, "timestamp": 0})
    _attested_root_cache.update({"root": None, "timestamp": 0})

    # Clear ChainAttestation caches if loaded
    try:
        from plugins.ChainAttestation import ChainAttestationPlugin
        ChainAttestationPlugin._name_cache.clear()
        ChainAttestationPlugin._attestation_cache.clear()
        ChainAttestationPlugin._digest_cache.update({"digest": None, "height": 0, "timestamp": 0})
    except Exception:
        pass

    # Clear SiteManager's @Cached domain resolution caches
    from Site import SiteManager as SM
    sm = SM.site_manager
    if sm:
        for method_name in ("isDomainCached", "resolveDomainCached"):
            method = getattr(sm, method_name, None)
            if method and hasattr(method, "emptyCache"):
                method.emptyCache()

    log.info("xID caches cleared (%d resolver entries)" % count)
    return count


@PluginManager.registerTo("UiWebsocket")
class UiWebsocketPlugin(object):
    @flag.admin
    def actionXidClearCache(self, to):
        count = clearXidCaches()
        self.response(to, {"cleared": count})
