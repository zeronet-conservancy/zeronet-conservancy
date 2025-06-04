"""Test Sanity.py"""

from .Sanity import checkAddress, replaceAddressesIn

def test_checkAddressReports():
    res = checkAddress('user@domain').error == 'non-unique'

sample = {
    "address": "12345",
    "files": {},
    "ignore": ".*",
    "inner_path": "data/users/content.json",
    "modified": 12345,
    "user_contents": {
        "cert_signers": {
            "zeroid.bit": ["1iD5ZQJMNXu43w1qLB8sfdHVKppVMduGz"],
            "nocert": []
        },
        "permission_rules": {
            ".*": {
                "files_allowed": "data.json",
                "max_size": 20000
            },
        },
        "permissions": {
            "bad@zeroid.bit": False,
            "nofish@zeroid.bit": {"max_size": 100000}
        }
    }
}

def test_replaceAddressesIn():
    replaced_bad = replaceAddressesIn(sample, {'bad@zeroid.bit': 'pubkey'})
    assert replaced_bad['user_contents']['permissions']['pubkey'] == False
    assert replaced_bad['address'] == sample['address']
    assert replaced_bad['user_contents']['permissions']['nofish@zeroid.bit']['max_size'] == 100000
    replaced_fish = replaceAddressesIn(sample, {'nofish@zeroid.bit': 'pubkey2'})
    assert replaced_bad['user_contents']['permissions']['pubkey'] == False
    assert replaced_fish['user_contents']['permissions']['pubkey2']['max_size'] == 100000
