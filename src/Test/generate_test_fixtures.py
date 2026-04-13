#!/usr/bin/env python3
"""
Generate test fixture directory with epix bech32 addresses and valid signatures.

Run from EpixNet/src/:
    python3 Test/generate_test_fixtures.py

Produces: Test/testdata/{SITE_ADDRESS}-original/
"""
import sys
import os
import json
import shutil
import hashlib
import time
import types

# ── Bootstrap: stub gevent so we can import CryptEpix without it ──
gevent_mod = types.ModuleType('gevent')
gevent_mod.__path__ = ['_fake_gevent']
gevent_mod.GreenletExit = type('GreenletExit', (BaseException,), {})

class _Fake:
    def __init__(self, *a, **kw): pass
    def __call__(self, *a, **kw): return _Fake()
    def __getattr__(self, name): return _Fake()
    def __bool__(self): return False
    def __iter__(self): return iter([])

for attr in ['spawn', 'sleep', 'joinall', 'killall', 'getcurrent', 'Greenlet']:
    setattr(gevent_mod, attr, _Fake())
sys.modules['gevent'] = gevent_mod
for sub in [
    'event', 'lock', 'pool', 'local', 'queue', 'monkey', 'threading',
    'timeout', 'hub', 'socket', 'select', 'os', 'time', 'ssl',
    'threadpool', 'subprocess', 'fileobject', 'resolver', 'server',
    'pywsgi', 'backdoor', 'baseserver', 'builtins',
    '_threading', '_ffi', '_ssl', '_socket', '_util', '_imap',
    'exceptions', '_hub_local', '_hub_primitives', '_greenlet_primitives',
    '_waiter', 'contextvars', '_semaphore', '_event', '_queue', '_lock',
    'ares',
]:
    m = types.ModuleType(f'gevent.{sub}')
    m.__path__ = []
    for a in ['AsyncResult', 'Semaphore', 'Pool', 'Group', 'Event', 'Queue',
              'Timeout', 'RLock', 'BoundedSemaphore', 'Greenlet',
              'spawn', 'sleep', 'joinall', 'killall', 'getcurrent',
              'patch_all', 'is_module_patched', 'get_original',
              'ThreadPool', 'ThreadPoolExecutor', 'wrap', 'Lock']:
        setattr(m, a, _Fake())
    sys.modules[f'gevent.{sub}'] = m
    setattr(gevent_mod, sub, m)

# Now set up paths
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC_DIR)
sys.path.insert(0, os.path.join(SRC_DIR, 'lib'))

from Crypt.CryptEpix import sign as crypt_sign, privatekeyToAddress

# ═══════════════════════════════════════════════════════════════════
# Address Registry — all test identities
# ═══════════════════════════════════════════════════════════════════

# Known keys (from original ZeroNet test fixtures)
SITE_KEY     = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"
SITE_ADDR    = "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8"

USER_KEY     = "5Kk7FSA63FC2ViKmKLuBxk9gQkaQ5713hKq8LmFAf4cVeXh6K6A"
USER_ADDR    = "epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len"

CERT_ADMIN_KEY  = "5JusJDSjHaMHwUjDT3o6eQ54pA6poo8La5fAgn1wNc3iK59jxjA"
CERT_ADMIN_ADDR = "epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj"

CLONE_KEY    = "5JU2p5h3R7B1WrbaEdEDNZR7YHqRLGcjNcqwqVQzX2H4SuNe2ee"
CLONE_ADDR   = "epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9"

# Generated keys (for roles where old Bitcoin keys are unknown)
OPTIONAL_USER_KEY  = "5KksssvxUSUGud3xGCJmxrY5BfT4Xsis8HzFwZQ6akF9jDhZ62B"
OPTIONAL_USER_ADDR = "epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj"

ARCHIVED_USER_KEY  = "5KHxczYQ7SaKbUNHXVbXaNECwjZFkegC8wy8R3UgAQQ9mWmZBFd"
ARCHIVED_USER_ADDR = "epix1ngcj6lrcc5tj07p9ku4h3xs0c6rpw4fcfw2ygl"

CERT_SIGNER_KEY  = "5JD5KyTKpAzeJDWnPtgzuR2NNWapvZvUL8eD5B6xSCKtVRm2N4y"
CERT_SIGNER_ADDR = "epix1hurv78laj8vke454nef7w80hqwpkfhpdfms44h"

INCLUDE_SIGNER_KEY  = "5KPQNXjHHTNr9HWkk581sFcnLJzKyAAC6jkcmKHBWNyiw5M7HJ2"
INCLUDE_SIGNER_ADDR = "epix1lse5uxxkqz472zvr25y4upc63hwk7ldza54k9j"

USERS_SIGNER_KEY  = "5KNvotpgEUTX5bhMdgaN8MzvpG5ds5w57iyaqKCH1RqFhk44Afu"
USERS_SIGNER_ADDR = "epix1erhadgd54y5f62rqqldaszfagywll8adf4n5z5"

SECURITY_TEST_ADDR = "epix1j94jrkp4q0vrs9xzjrnvdmd3jj27radnhsp9da"

# content-default signer (reuse cert_signer for simplicity — same role in default template)
CONTENT_DEFAULT_KEY  = CERT_SIGNER_KEY
CONTENT_DEFAULT_ADDR = CERT_SIGNER_ADDR

CERT_DOMAIN = "epixid.epix"

# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def sha512sum(filepath):
    """Match CryptHash.sha512sum — returns first 64 hex chars of SHA-512."""
    h = hashlib.sha512()
    with open(filepath, 'rb') as f:
        while True:
            buf = f.read(65536)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()[:64]

def file_size(filepath):
    return os.path.getsize(filepath)

def sign_content(content_dict, privatekey):
    """Sign a content.json dict exactly like ContentManager.sign()."""
    d = dict(content_dict)
    d.pop('signs', None)
    d.pop('sign', None)
    payload = json.dumps(d, sort_keys=True)
    return crypt_sign(payload, privatekey)

def write_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=1, sort_keys=False)
        f.write('\n')

def copy_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)

# ═══════════════════════════════════════════════════════════════════
# Main generator
# ═══════════════════════════════════════════════════════════════════

def generate():
    testdata_dir = os.path.join(SRC_DIR, "Test", "testdata")
    old_dir = os.path.join(testdata_dir, "1TeSTvb4w2PWE81S2rEELgmX2GCCExQGT-original")
    new_dir = os.path.join(testdata_dir, f"{SITE_ADDR}-original")

    if not os.path.isdir(old_dir):
        print(f"ERROR: Old fixture directory not found: {old_dir}")
        sys.exit(1)

    if os.path.isdir(new_dir):
        print(f"Removing existing {new_dir}")
        shutil.rmtree(new_dir)

    os.makedirs(new_dir)
    print(f"Generating fixtures in {new_dir}")

    # ── Copy static files (no address references) ──
    static_files = [
        "css/all.css",
        "js/all.js",
        "index.html",
        "dbschema.json",
        "img/loading.gif",
        "data/data.json",
        "data/optional.txt",
        "data/test_include/data.json",
        "data-default/data.json",
    ]
    # All images
    for img_file in os.listdir(os.path.join(old_dir, "data", "img")):
        static_files.append(f"data/img/{img_file}")

    for f in static_files:
        src = os.path.join(old_dir, f)
        dst = os.path.join(new_dir, f)
        if os.path.isfile(src):
            copy_file(src, dst)
        else:
            print(f"  WARNING: missing {src}")

    # ── Copy user data files ──
    # User 1J6 → USER_ADDR
    user_data_src = os.path.join(old_dir, "data/users/1J6UrZMkarjVg5ax9W4qThir3BFUikbW6C/data.json")
    user_data_dst = os.path.join(new_dir, f"data/users/{USER_ADDR}/data.json")
    copy_file(user_data_src, user_data_dst)

    # User 1Cjf → OPTIONAL_USER_ADDR (has peanut-butter-jelly-time.gif)
    opt_data_src = os.path.join(old_dir, "data/users/1CjfbrbwtP8Y2QjPy12vpTATkUT7oSiPQ9/data.json")
    opt_data_dst = os.path.join(new_dir, f"data/users/{OPTIONAL_USER_ADDR}/data.json")
    copy_file(opt_data_src, opt_data_dst)
    gif_src = os.path.join(old_dir, "data/users/1CjfbrbwtP8Y2QjPy12vpTATkUT7oSiPQ9/peanut-butter-jelly-time.gif")
    gif_dst = os.path.join(new_dir, f"data/users/{OPTIONAL_USER_ADDR}/peanut-butter-jelly-time.gif")
    copy_file(gif_src, gif_dst)

    # User 1C5s → ARCHIVED_USER_ADDR
    arch_data_src = os.path.join(old_dir, "data/users/1C5sgvWaSgfaTpV5kjBCnCiKtENNMYo69q/data.json")
    arch_data_dst = os.path.join(new_dir, f"data/users/{ARCHIVED_USER_ADDR}/data.json")
    copy_file(arch_data_src, arch_data_dst)

    # ── Generate content.json files (bottom-up so hashes are available) ──

    # 1. data/test_include/content.json
    test_include_content = {
        "address": SITE_ADDR,
        "files": {
            "data.json": {
                "sha512": sha512sum(os.path.join(new_dir, "data/test_include/data.json")),
                "size": file_size(os.path.join(new_dir, "data/test_include/data.json"))
            }
        },
        "inner_path": "data/test_include/content.json",
        "modified": 1470340816
    }
    test_include_content["signs"] = {
        SITE_ADDR: sign_content(test_include_content, SITE_KEY)
    }
    write_json(os.path.join(new_dir, "data/test_include/content.json"), test_include_content)
    print("  Created data/test_include/content.json")

    # 2. data/users/{USER_ADDR}/content.json
    user_content = {
        "address": SITE_ADDR,
        "cert_auth_type": "web",
        "cert_sign": crypt_sign(f"{USER_ADDR}#web/toruser", CERT_SIGNER_KEY),
        "cert_user_id": f"toruser@{CERT_DOMAIN}",
        "files": {
            "data.json": {
                "sha512": sha512sum(os.path.join(new_dir, f"data/users/{USER_ADDR}/data.json")),
                "size": file_size(os.path.join(new_dir, f"data/users/{USER_ADDR}/data.json"))
            }
        },
        "inner_path": f"data/users/{USER_ADDR}/content.json",
        "modified": 1470340817
    }
    user_content["signs"] = {
        SITE_ADDR: sign_content(user_content, SITE_KEY)
    }
    write_json(os.path.join(new_dir, f"data/users/{USER_ADDR}/content.json"), user_content)
    print(f"  Created data/users/{USER_ADDR}/content.json")

    # 3. data/users/{OPTIONAL_USER_ADDR}/content.json (with optional files)
    opt_user_content = {
        "address": SITE_ADDR,
        "cert_auth_type": "web",
        "cert_sign": crypt_sign(f"{OPTIONAL_USER_ADDR}#web/toruser", CERT_SIGNER_KEY),
        "cert_user_id": f"toruser@{CERT_DOMAIN}",
        "files": {
            "data.json": {
                "sha512": sha512sum(os.path.join(new_dir, f"data/users/{OPTIONAL_USER_ADDR}/data.json")),
                "size": file_size(os.path.join(new_dir, f"data/users/{OPTIONAL_USER_ADDR}/data.json"))
            }
        },
        "files_optional": {
            "peanut-butter-jelly-time.gif": {
                "sha512": sha512sum(os.path.join(new_dir, f"data/users/{OPTIONAL_USER_ADDR}/peanut-butter-jelly-time.gif")),
                "size": file_size(os.path.join(new_dir, f"data/users/{OPTIONAL_USER_ADDR}/peanut-butter-jelly-time.gif"))
            }
        },
        "inner_path": f"data/users/{OPTIONAL_USER_ADDR}/content.json",
        "modified": 1470340817,
        "optional": ".*\\.(jpg|png|gif)"
    }
    opt_user_content["signs"] = {
        SITE_ADDR: sign_content(opt_user_content, SITE_KEY)
    }
    write_json(os.path.join(new_dir, f"data/users/{OPTIONAL_USER_ADDR}/content.json"), opt_user_content)
    print(f"  Created data/users/{OPTIONAL_USER_ADDR}/content.json")

    # 4. data/users/{ARCHIVED_USER_ADDR}/content.json (self-signed)
    arch_user_content = {
        "cert_auth_type": "web",
        "cert_sign": crypt_sign(f"{ARCHIVED_USER_ADDR}#web/newzeroid", CERT_SIGNER_KEY),
        "cert_user_id": f"newzeroid@{CERT_DOMAIN}",
        "files": {
            "data.json": {
                "sha512": sha512sum(os.path.join(new_dir, f"data/users/{ARCHIVED_USER_ADDR}/data.json")),
                "size": file_size(os.path.join(new_dir, f"data/users/{ARCHIVED_USER_ADDR}/data.json"))
            }
        },
        "modified": 1432554679.913
    }
    # Self-signed: the archived user signs their own content
    arch_user_content["signs"] = {
        ARCHIVED_USER_ADDR: sign_content(arch_user_content, ARCHIVED_USER_KEY)
    }
    write_json(os.path.join(new_dir, f"data/users/{ARCHIVED_USER_ADDR}/content.json"), arch_user_content)
    print(f"  Created data/users/{ARCHIVED_USER_ADDR}/content.json")

    # 5. data/users/content.json (user_contents rules)
    users_content = {
        "address": SITE_ADDR,
        "files": {},
        "ignore": ".*",
        "inner_path": "data/users/content.json",
        "modified": 1470340815,
        "user_contents": {
            "cert_signers": {
                CERT_DOMAIN: [CERT_SIGNER_ADDR]
            },
            "permission_rules": {
                ".*": {
                    "files_allowed": "data.json",
                    "files_allowed_optional": ".*\\.(png|jpg|gif)",
                    "max_size": 10000,
                    "max_size_optional": 10000000,
                    "signers": [CERT_ADMIN_ADDR]
                },
                f"bitid/.*@{CERT_DOMAIN}": {"max_size": 40000},
                f"bitmsg/.*@{CERT_DOMAIN}": {"max_size": 15000}
            },
            "permissions": {
                f"bad@{CERT_DOMAIN}": False,
                f"nofish@{CERT_DOMAIN}": {"max_size": 100000}
            }
        }
    }
    users_content["signs"] = {
        SITE_ADDR: sign_content(users_content, SITE_KEY)
    }
    write_json(os.path.join(new_dir, "data/users/content.json"), users_content)
    print("  Created data/users/content.json")

    # 6. data-default/users/content-default.json
    content_default = {
        "files": {},
        "ignore": ".*",
        "modified": 1432466966,
        "user_contents": {
            "cert_signers": {
                CERT_DOMAIN: [CERT_SIGNER_ADDR]
            },
            "permission_rules": {
                ".*": {
                    "files_allowed": "data.json",
                    "max_size": 10000
                },
                f"bitid/.*@{CERT_DOMAIN}": {"max_size": 40000},
                f"bitmsg/.*@{CERT_DOMAIN}": {"max_size": 15000}
            },
            "permissions": {
                f"banexample@{CERT_DOMAIN}": False,
                f"nofish@{CERT_DOMAIN}": {"max_size": 20000}
            }
        }
    }
    content_default["signs"] = {
        CONTENT_DEFAULT_ADDR: sign_content(content_default, CONTENT_DEFAULT_KEY)
    }
    write_json(os.path.join(new_dir, "data-default/users/content-default.json"), content_default)
    print("  Created data-default/users/content-default.json")

    # 7. Root content.json — hash ALL non-ignored files
    # Ignore pattern from original: ((js|css)/(?!all.(js|css))|data/.*db|data/users/.*/.*|data/test_include/.*)
    # This means: include css/all.css, js/all.js, index.html, dbschema.json, img/*, data/data.json, data/img/*, data-default/*
    # But NOT: individual js/css files, data/users/*, data/test_include/*

    files_dict = {}
    files_optional_dict = {}

    # Files to hash (matching the original fixture)
    regular_files = [
        "css/all.css",
        "data-default/data.json",
        "data-default/users/content-default.json",
        "data/data.json",
        "dbschema.json",
        "img/loading.gif",
        "index.html",
        "js/all.js",
    ]
    # Data images that are regular files
    data_img_regular = [
        "data/img/autoupdate.png",
        "data/img/direct_domains.png",
        "data/img/domain.png",
        "data/img/memory.png",
        "data/img/multiuser.png",
        "data/img/progressbar.png",
        "data/img/slides.png",
        "data/img/slots_memory.png",
        "data/img/trayicon.png",
    ]
    regular_files.extend(data_img_regular)

    for f in sorted(regular_files):
        fpath = os.path.join(new_dir, f)
        if os.path.isfile(fpath):
            files_dict[f] = {
                "sha512": sha512sum(fpath),
                "size": file_size(fpath)
            }

    # Optional files (matching original optional pattern)
    optional_files = [
        "data/img/zeroblog-comments.png",
        "data/img/zeroid.png",
        "data/img/zeroname.png",
        "data/img/zerotalk-mark.png",
        "data/img/zerotalk-upvote.png",
        "data/img/zerotalk.png",
        "data/optional.txt",
    ]
    for f in sorted(optional_files):
        fpath = os.path.join(new_dir, f)
        if os.path.isfile(fpath):
            files_optional_dict[f] = {
                "sha512": sha512sum(fpath),
                "size": file_size(fpath)
            }

    # Build valid_signers for signers_sign
    valid_signers = [SITE_ADDR]
    signers_data = "1:%s" % ",".join(valid_signers)

    root_content = {
        "address": SITE_ADDR,
        "background-color": "white",
        "description": "Blogging platform Demo",
        "domain": "Blog.EpixNetwork.epix",
        "files": files_dict,
        "files_optional": files_optional_dict,
        "ignore": "((js|css)/(?!all.(js|css))|data/.*db|data/users/.*/.*|data/test_include/.*)",
        "includes": {
            "data/test_include/content.json": {
                "added": 1424976057,
                "files_allowed": "data.json",
                "includes_allowed": False,
                "max_size": 20000,
                "signers": [INCLUDE_SIGNER_ADDR, SITE_ADDR],
                "signers_required": 1,
                "user_id": 47,
                "user_name": "test"
            },
            "data/users/content.json": {
                "signers": [USERS_SIGNER_ADDR, SITE_ADDR],
                "signers_required": 1
            }
        },
        "inner_path": "content.json",
        "modified": 1503257990,
        "optional": "(data/img/zero.*|data/optional.*)",
        "signs_required": 1,
        "title": "ZeroBlog",
        "epixnet_version": "0.5.7"
    }

    # Sign signers_sign
    root_content["signers_sign"] = crypt_sign(signers_data, SITE_KEY)

    # Sign the root content
    root_content["signs"] = {
        SITE_ADDR: sign_content(root_content, SITE_KEY)
    }

    write_json(os.path.join(new_dir, "content.json"), root_content)
    print("  Created content.json")

    # ── Summary ──
    print("\n=== Fixture generation complete ===")
    print(f"Directory: {new_dir}")
    print(f"Site address: {SITE_ADDR}")
    print(f"User addresses:")
    print(f"  Test user:     {USER_ADDR}")
    print(f"  Optional user: {OPTIONAL_USER_ADDR}")
    print(f"  Archived user: {ARCHIVED_USER_ADDR}")
    print(f"Signers:")
    print(f"  Cert admin:      {CERT_ADMIN_ADDR}")
    print(f"  Cert signer:     {CERT_SIGNER_ADDR}")
    print(f"  Include signer:  {INCLUDE_SIGNER_ADDR}")
    print(f"  Users signer:    {USERS_SIGNER_ADDR}")
    print(f"  Content default: {CONTENT_DEFAULT_ADDR}")
    print(f"Domain: {CERT_DOMAIN}")

    file_count = sum(len(files) for _, _, files in os.walk(new_dir))
    print(f"Total files: {file_count}")


if __name__ == "__main__":
    generate()
