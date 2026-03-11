import logging
import json
import time

from Config import config
from Plugin import PluginManager

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

allow_reload = False

log = logging.getLogger("ChainAttestationPlugin")

# In-memory cache: keyed by (tld, name), stores {digest, data, timestamp}
_name_cache = {}
# Cached attestation finalization: keyed by digest, stores {finalized, timestamp}
_attestation_cache = {}
# Cached current state digest from chain
_digest_cache = {"digest": None, "height": 0, "timestamp": 0}

# How long to cache attestation finalization status (seconds)
ATTESTATION_CACHE_TTL = 30
# How long to cache the current digest (seconds)
DIGEST_CACHE_TTL = 15


def _fetch_json(url, timeout=10):
    """Fetch JSON from a URL, return parsed dict or None on error."""
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        resp = urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except (URLError, ValueError, IOError) as e:
        log.debug("Chain RPC fetch failed for %s: %s" % (url, e))
        return None


def _get_chain_rpc(chain_att=None):
    """Get the RPC base URL. Priority: per-site content.json > global config > default."""
    if chain_att:
        rpc = chain_att.get("rpc_url", "").rstrip("/")
        if rpc:
            return rpc
    return getattr(config, "chain_rpc_url", "https://api.epix.zone").rstrip("/")


def _fetch_state_digest(rpc_url):
    """Fetch current state digest from chain. Returns {digest, height, num_names} or None."""
    now = time.time()
    if _digest_cache["digest"] and (now - _digest_cache["timestamp"]) < DIGEST_CACHE_TTL:
        return _digest_cache

    data = _fetch_json("%s/xid/v1/state_digest" % rpc_url)
    if data and data.get("digest"):
        _digest_cache["digest"] = data["digest"]
        _digest_cache["height"] = int(data.get("height", 0))
        _digest_cache["num_names"] = int(data.get("num_names", 0))
        _digest_cache["timestamp"] = now
        return _digest_cache
    return None


def _is_digest_finalized(rpc_url, digest):
    """Check if a digest has been finalized (attested by 2/3+ validators)."""
    now = time.time()
    cached = _attestation_cache.get(digest)
    if cached and (now - cached["timestamp"]) < ATTESTATION_CACHE_TTL:
        return cached["finalized"]

    data = _fetch_json("%s/xid/v1/attestations?digest=%s" % (rpc_url, digest))
    if data is not None:
        finalized = bool(data.get("finalized", False))
        _attestation_cache[digest] = {"finalized": finalized, "timestamp": now}
        return finalized

    return False


def _resolve_name(rpc_url, tld, name):
    """Resolve a single name from the chain. Returns record dict or None."""
    data = _fetch_json("%s/xid/v1/resolve/%s/%s" % (rpc_url, tld, name))
    if data and data.get("record"):
        return data["record"]
    return None


def _invalidate_cache_for_digest(new_digest):
    """Clear name cache entries that were cached under a different digest."""
    keys_to_remove = [k for k, v in _name_cache.items() if v.get("digest") != new_digest]
    for k in keys_to_remove:
        del _name_cache[k]


@PluginManager.registerTo("ContentManager")
class ContentManagerPlugin(object):

    def getChainAttestation(self, inner_path, content=None):
        """Check if this content.json uses chain attestation verification.
        Returns chain_attestation config dict or None.

        The root content.json must contain a "chain_attestation" key with:
          - data_dir: prefix path for chain-attested content files
          - rpc_url: (optional) chain REST API URL, defaults to https://api.epix.zone
        """
        root_content = self.contents.get("content.json")
        if not root_content or "chain_attestation" not in root_content:
            return None

        chain_att = root_content["chain_attestation"]
        data_dir = chain_att.get("data_dir", "")

        # Only apply chain attestation to content.json files under the chain data dir
        if not data_dir or not inner_path.startswith(data_dir):
            return None

        return chain_att

    def verifyFile(self, inner_path, file, ignore_same=True):
        """Intercept content.json verification to handle chain attestation.

        Verifies chain-attested content by querying the chain's REST API:
        1. Fetch the current state digest from the chain
        2. Verify the digest is finalized (attested by 2/3+ validators)
        3. Compare the state_digest in the content.json against the chain's digest
        4. If matched and finalized, the content is trusted

        No cryptographic signatures needed — the chain's consensus IS the proof.
        """
        from Content.ContentManager import VerifyError

        if inner_path.endswith("content.json"):
            if type(file) is dict:
                new_content = file
            else:
                pos = file.tell()
                try:
                    new_content = json.load(file)
                except Exception:
                    file.seek(pos)
                    return super(ContentManagerPlugin, self).verifyFile(inner_path, file, ignore_same)
                file.seek(pos)

            chain_attestation = self.getChainAttestation(inner_path, new_content)
            if chain_attestation:
                state_digest = new_content.get("state_digest", "")
                if not state_digest:
                    raise VerifyError("Chain attestation content missing state_digest")

                rpc_url = _get_chain_rpc(chain_attestation)

                # Fetch the current digest from the chain
                chain_digest_info = _fetch_state_digest(rpc_url)
                if not chain_digest_info:
                    raise VerifyError("Chain attestation: could not fetch state digest from chain")

                chain_digest = chain_digest_info["digest"]

                # The content's state_digest must match the chain's current digest
                if state_digest != chain_digest:
                    raise VerifyError(
                        "Chain attestation: content digest %s... does not match chain digest %s..." %
                        (state_digest[:16], chain_digest[:16])
                    )

                # Check that the digest is finalized (2/3+ validators attested)
                if not _is_digest_finalized(rpc_url, chain_digest):
                    raise VerifyError(
                        "Chain attestation: digest %s... not yet finalized" % state_digest[:16]
                    )

                # Digest matches chain and is finalized — invalidate stale cache entries
                _invalidate_cache_for_digest(chain_digest)

                log.debug(
                    "%s: chain attestation verified (digest: %s..., height: %s)" %
                    (inner_path, state_digest[:16], chain_digest_info.get("height", "?"))
                )
                return self.verifyContent(inner_path, new_content)

        return super(ContentManagerPlugin, self).verifyFile(inner_path, file, ignore_same)

    def resolveChainName(self, tld, name):
        """Resolve a name from the chain with lazy caching.

        Returns the name record dict from the chain, or None if not found.
        Results are cached and invalidated when the state digest changes.
        """
        root_content = self.contents.get("content.json")
        if not root_content or "chain_attestation" not in root_content:
            return None

        chain_att = root_content["chain_attestation"]
        rpc_url = _get_chain_rpc(chain_att)

        # Check if digest has changed — if so, invalidate stale cache
        chain_digest_info = _fetch_state_digest(rpc_url)
        if chain_digest_info:
            _invalidate_cache_for_digest(chain_digest_info["digest"])

        # Check cache first
        cache_key = (tld, name)
        cached = _name_cache.get(cache_key)
        if cached:
            return cached.get("data")

        # Cache miss — query the chain
        record = _resolve_name(rpc_url, tld, name)

        # Cache regardless of result (cache misses too, to avoid repeated lookups)
        current_digest = chain_digest_info["digest"] if chain_digest_info else ""
        _name_cache[cache_key] = {
            "digest": current_digest,
            "data": record,
            "timestamp": time.time(),
        }

        return record


@PluginManager.registerTo("ConfigPlugin")
class ConfigPlugin(object):
    def createArguments(self):
        group = self.parser.add_argument_group("Chain Attestation plugin")
        group.add_argument('--chain-rpc-url', help='Epix Chain REST API URL for xID attestation verification',
                           default='https://api.epix.zone', metavar='url')
        group.add_argument('--chain-evm-rpc-url', help='Epix Chain EVM JSON-RPC URL',
                           default='https://evmrpc.epix.zone', metavar='url')
        group.add_argument('--chain-block-explorer-url', help='Epix Chain block explorer URL',
                           default='https://scan.epix.zone', metavar='url')

        return super(ConfigPlugin, self).createArguments()
