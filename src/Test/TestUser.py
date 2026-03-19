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

    def testAuthAddress(self, user):
        # Without cert, getAuthAddress returns per-site BIP32 derived address
        test_site_address = "epix1test0000000000000000000000000000000000"
        auth_address = user.getAuthAddress(test_site_address)
        # Should be a derived address, not the master address
        assert auth_address != user.master_address
        assert auth_address == user.getSiteData(test_site_address)["auth_address"]
        # Private key matches
        auth_privatekey = user.getAuthPrivatekey(test_site_address)
        assert CryptEpix.privatekeyToAddress(auth_privatekey) == auth_address

    def testCert(self, user):
        cert_site_address = "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
        test_site_address = "epix1test0000000000000000000000000000000000"

        # Get derived auth address for the cert site
        cert_auth_address = user.getSiteData(cert_site_address)["auth_address"]
        assert cert_auth_address != user.master_address  # Should be derived

        # Add cert using derived address
        user.addCert(cert_auth_address, "epixid.epix", "faketype", "fakeuser", "fakesign")
        user.setCert(test_site_address, "epixid.epix")

        # With cert active, auth address should be the cert's auth address
        assert user.getAuthAddress(test_site_address) == cert_auth_address
        auth_privatekey = user.getAuthPrivatekey(test_site_address)
        assert CryptEpix.privatekeyToAddress(auth_privatekey) == cert_auth_address

        # Test delete site data
        assert test_site_address in user.sites
        user.deleteSiteData(test_site_address)
        assert test_site_address not in user.sites

        # After deleting site data, auth address returns a new derived address (no cert)
        new_auth = user.getAuthAddress(test_site_address)
        assert new_auth != cert_auth_address or new_auth == user.getSiteData(test_site_address)["auth_address"]

    def testCertGlobal(self, user):
        # setCertGlobal should activate cert on all existing sites
        site_a = "epix1testa000000000000000000000000000000000"
        site_b = "epix1testb000000000000000000000000000000000"

        # Create site data for both sites
        user.getSiteData(site_a)
        user.getSiteData(site_b)

        # Get derived address for site_a and create a cert
        auth_addr = user.getSiteData(site_a)["auth_address"]
        user.addCert(auth_addr, "test.epix", "xid", "testuser", "testsign")

        # Activate globally
        user.setCertGlobal("test.epix")

        # Both sites should have the cert active
        assert user.getCert(site_a) is not None
        assert user.getCert(site_b) is not None
        assert user.getAuthAddress(site_a) == auth_addr
        assert user.getAuthAddress(site_b) == auth_addr

        # Deactivate globally
        user.setCertGlobal(None)
        assert user.getCert(site_a) is None
        assert user.getCert(site_b) is None

        # Auth addresses should revert to per-site derived
        assert user.getAuthAddress(site_a) != user.getAuthAddress(site_b)

        # Cleanup
        user.deleteCert("test.epix")
        user.deleteSiteData(site_a)
        user.deleteSiteData(site_b)

    def testCertAutoActivateNewSite(self, user):
        # When a cert is active globally, new sites should auto-get it
        site_a = "epix1testa000000000000000000000000000000000"

        # Create site data and cert, activate globally
        user.getSiteData(site_a)
        auth_addr = user.getSiteData(site_a)["auth_address"]
        user.addCert(auth_addr, "test.epix", "xid", "testuser", "testsign")
        user.setCertGlobal("test.epix")

        # Now visit a new site — cert should auto-activate
        site_b = "epix1testb000000000000000000000000000000000"
        assert site_b not in user.sites
        new_site_data = user.getSiteData(site_b)
        assert new_site_data.get("cert") == "test.epix"
        assert user.getAuthAddress(site_b) == auth_addr

        # Cleanup
        user.setCertGlobal(None)
        user.deleteCert("test.epix")
        user.deleteSiteData(site_a)
        user.deleteSiteData(site_b)

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

    def testCertWithDerivedAddress(self, user):
        # Cert with a derived address should work — cert takes precedence
        cert_site_address = "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
        test_site_address = "epix1test2000000000000000000000000000000000"

        # Get derived address from site data
        site_data = user.getSiteData(cert_site_address)
        derived_auth = site_data["auth_address"]
        assert derived_auth != user.master_address

        # Add cert using derived address
        user.addCert(derived_auth, "epixid2.epix", "faketype", "fakeuser2", "fakesign2")
        user.setCert(test_site_address, "epixid2.epix")

        # Cert takes precedence over derived default
        assert user.getAuthAddress(test_site_address) == derived_auth

        # Without cert, falls back to per-site derived address
        user.setCert(test_site_address, None)
        test_derived = user.getSiteData(test_site_address)["auth_address"]
        assert user.getAuthAddress(test_site_address) == test_derived

        # Cleanup
        user.deleteCert("epixid2.epix")
        user.deleteSiteData(test_site_address)
        user.deleteSiteData(cert_site_address)
