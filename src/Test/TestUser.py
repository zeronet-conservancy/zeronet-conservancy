import pytest

from Crypt import CryptEpix


@pytest.mark.usefixtures("resetSettings")
class TestUser:
    def testAddress(self, user):
        assert user.master_address == "epix16jha5q3qvr7fgldrgem4x5ju8vwd78d3lwawtn"
        address_index = 14199856986777972317416200829214867103927393370315628508069949862373673319704318642080835749710491251822
        assert user.getAddressAuthIndex("epix16jha5q3qvr7fgldrgem4x5ju8vwd78d3lwawtn") == address_index

    # Re-generate privatekey based on address_index
    def testNewSite(self, user):
        address, address_index, site_data = user.getNewSiteData()  # Create a new random site
        assert CryptEpix.hdPrivatekey(user.master_seed, address_index) == site_data["privatekey"]

        user.sites = {}  # Reset user data

        # Site address and auth address is different
        assert user.getSiteData(address)["auth_address"] != address
        # Re-generate auth_privatekey for site
        assert user.getSiteData(address)["auth_privatekey"] == site_data["auth_privatekey"]

    def testMasterIdentityDefault(self, user):
        # By default, getAuthAddress returns master_address (not a derived address)
        test_site_address = "epix1test0000000000000000000000000000000000"
        auth_address = user.getAuthAddress(test_site_address)
        assert auth_address == user.master_address
        auth_privatekey = user.getAuthPrivatekey(test_site_address)
        assert auth_privatekey == user.master_seed
        assert CryptEpix.privatekeyToAddress(auth_privatekey) == auth_address

    def testAddCertMasterAddress(self, user):
        # addCert should work when called with master_address
        user.addCert(user.master_address, "testcert.epix", "xid", "testuser", "testsign")
        cert = user.certs.get("testcert.epix")
        assert cert is not None
        assert cert["auth_address"] == user.master_address
        assert cert["auth_privatekey"] == user.master_seed
        assert CryptEpix.privatekeyToAddress(cert["auth_privatekey"]) == user.master_address
        # Cleanup
        user.deleteCert("testcert.epix")

    def testCert(self, user):
        cert_site_address = "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
        test_site_address = "epix1test0000000000000000000000000000000000"

        # Default auth address is now master_address
        cert_auth_address = user.getAuthAddress(cert_site_address)
        assert cert_auth_address == user.master_address

        # Add cert using master_address
        user.addCert(cert_auth_address, "epixid.epix", "faketype", "fakeuser", "fakesign")
        user.setCert(test_site_address, "epixid.epix")

        # By using certificate the auth address should be same as the certificate provider
        assert user.getAuthAddress(test_site_address) == cert_auth_address
        auth_privatekey = user.getAuthPrivatekey(test_site_address)
        assert CryptEpix.privatekeyToAddress(auth_privatekey) == cert_auth_address

        # Test delete site data
        assert test_site_address in user.sites
        user.deleteSiteData(test_site_address)
        assert test_site_address not in user.sites

        # After deleting site data, auth address returns master (default, no cert active)
        assert user.getAuthAddress(test_site_address) == user.master_address

    def testCertWithDerivedAddress(self, user):
        # Cert with a derived address should work — cert takes precedence over master default
        cert_site_address = "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
        test_site_address = "epix1test2000000000000000000000000000000000"

        # Get derived address from site data
        site_data = user.getSiteData(cert_site_address)
        derived_auth = site_data["auth_address"]
        assert derived_auth != user.master_address

        # Add cert using derived address
        user.addCert(derived_auth, "epixid2.epix", "faketype", "fakeuser2", "fakesign2")
        user.setCert(test_site_address, "epixid2.epix")

        # Cert takes precedence over master default
        assert user.getAuthAddress(test_site_address) == derived_auth

        # Without cert, falls back to master
        user.setCert(test_site_address, None)
        assert user.getAuthAddress(test_site_address) == user.master_address

        # Cleanup
        user.deleteCert("epixid2.epix")
        user.deleteSiteData(test_site_address)
        user.deleteSiteData(cert_site_address)
