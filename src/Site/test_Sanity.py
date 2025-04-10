"""Test Sanity.py"""

from .Sanity import checkAddress

def test_checkAddressReports():
    res = checkAddress('user@domain').error == 'non-unique'
