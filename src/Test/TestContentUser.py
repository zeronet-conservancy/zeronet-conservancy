import json
import io

import pytest

from Crypt import CryptEpix
from Content.ContentManager import VerifyError, SignError


@pytest.mark.usefixtures("resetSettings")
class TestContentUser:
    def testSigners(self, site):
        # File info for not existing user file
        file_info = site.content_manager.getFileInfo("data/users/notexist/data.json")
        assert file_info["content_inner_path"] == "data/users/notexist/content.json"
        file_info = site.content_manager.getFileInfo("data/users/notexist/a/b/data.json")
        assert file_info["content_inner_path"] == "data/users/notexist/content.json"
        valid_signers = site.content_manager.getValidSigners("data/users/notexist/content.json")
        assert valid_signers == ["epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj", "notexist", "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8"]

        # File info for exsitsing user file
        valid_signers = site.content_manager.getValidSigners("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json")
        assert 'epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8' in valid_signers  # The site address
        assert 'epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj' in valid_signers  # Admin user defined in data/users/content.json
        assert 'epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len' in valid_signers  # The user itself
        assert len(valid_signers) == 3  # No more valid signers

        # Valid signer for banned user
        user_content = site.storage.loadJson("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json")
        user_content["cert_user_id"] = "bad@epixid.epix"

        valid_signers = site.content_manager.getValidSigners("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_content)
        assert 'epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8' in valid_signers  # The site address
        assert 'epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj' in valid_signers  # Admin user defined in data/users/content.json
        assert 'epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len' not in valid_signers  # The user itself

    def testRules(self, site):
        # We going to manipulate it this test rules based on data/users/content.json
        user_content = site.storage.loadJson("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json")

        # Known user
        user_content["cert_auth_type"] = "web"
        user_content["cert_user_id"] = "nofish@epixid.epix"
        rules = site.content_manager.getRules("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_content)
        assert rules["max_size"] == 100000
        assert "epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len" in rules["signers"]

        # Unknown user
        user_content["cert_auth_type"] = "web"
        user_content["cert_user_id"] = "noone@epixid.epix"
        rules = site.content_manager.getRules("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_content)
        assert rules["max_size"] == 10000
        assert "epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len" in rules["signers"]

        # User with more size limit based on auth type
        user_content["cert_auth_type"] = "bitmsg"
        user_content["cert_user_id"] = "noone@epixid.epix"
        rules = site.content_manager.getRules("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_content)
        assert rules["max_size"] == 15000
        assert "epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len" in rules["signers"]

        # Banned user
        user_content["cert_auth_type"] = "web"
        user_content["cert_user_id"] = "bad@epixid.epix"
        rules = site.content_manager.getRules("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_content)
        assert "epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len" not in rules["signers"]

    def testRulesAddress(self, site):
        user_inner_path = "data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/content.json"
        user_content = site.storage.loadJson(user_inner_path)

        rules = site.content_manager.getRules(user_inner_path, user_content)
        assert rules["max_size"] == 10000
        assert "epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj" in rules["signers"]

        users_content = site.content_manager.contents["data/users/content.json"]

        # Ban user based on address
        users_content["user_contents"]["permissions"]["epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj"] = False
        rules = site.content_manager.getRules(user_inner_path, user_content)
        assert "epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj" not in rules["signers"]

        # Change max allowed size
        users_content["user_contents"]["permissions"]["epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj"] = {"max_size": 20000}
        rules = site.content_manager.getRules(user_inner_path, user_content)
        assert rules["max_size"] == 20000

    def testVerifyAddress(self, site):
        privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"  # For main test site
        test_address = CryptEpix.privatekeyToAddress(privatekey)
        user_inner_path = "data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/content.json"
        data_dict = site.storage.loadJson(user_inner_path)
        users_content = site.content_manager.contents["data/users/content.json"]

        data = io.BytesIO(json.dumps(data_dict).encode())
        assert site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)

        # Test error on 15k data.json
        data_dict["files"]["data.json"]["size"] = 1024 * 15
        del data_dict["signs"]  # Remove signs before signing
        data_dict["signs"] = {
            test_address: CryptEpix.sign(json.dumps(data_dict, sort_keys=True), privatekey)
        }
        data = io.BytesIO(json.dumps(data_dict).encode())
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)
        assert "Include too large" in str(err.value)

        # Give more space based on address
        users_content["user_contents"]["permissions"]["epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj"] = {"max_size": 20000}
        del data_dict["signs"]  # Remove signs before signing
        data_dict["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(data_dict, sort_keys=True), privatekey)
        }
        data = io.BytesIO(json.dumps(data_dict).encode())
        assert site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)

    def testVerify(self, site):
        privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"  # For epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8
        user_inner_path = "data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/content.json"
        data_dict = site.storage.loadJson(user_inner_path)
        users_content = site.content_manager.contents["data/users/content.json"]

        data = io.BytesIO(json.dumps(data_dict).encode())
        assert site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)

        # Test max size exception by setting allowed to 0
        rules = site.content_manager.getRules(user_inner_path, data_dict)
        assert rules["max_size"] == 10000
        assert users_content["user_contents"]["permission_rules"][".*"]["max_size"] == 10000

        users_content["user_contents"]["permission_rules"][".*"]["max_size"] = 0
        rules = site.content_manager.getRules(user_inner_path, data_dict)
        assert rules["max_size"] == 0
        data = io.BytesIO(json.dumps(data_dict).encode())

        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)
        assert "Include too large" in str(err.value)
        users_content["user_contents"]["permission_rules"][".*"]["max_size"] = 10000  # Reset

        # Test max optional size exception
        # 1 MB gif = Allowed
        data_dict["files_optional"]["peanut-butter-jelly-time.gif"]["size"] = 1024 * 1024
        del data_dict["signs"]  # Remove signs before signing
        data_dict["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(data_dict, sort_keys=True), privatekey)
        }
        data = io.BytesIO(json.dumps(data_dict).encode())
        assert site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)

        # 100 MB gif = Not allowed
        data_dict["files_optional"]["peanut-butter-jelly-time.gif"]["size"] = 100 * 1024 * 1024
        del data_dict["signs"]  # Remove signs before signing
        data_dict["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(data_dict, sort_keys=True), privatekey)
        }
        data = io.BytesIO(json.dumps(data_dict).encode())
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)
        assert "Include optional files too large" in str(err.value)
        data_dict["files_optional"]["peanut-butter-jelly-time.gif"]["size"] = 1024 * 1024  # Reset

        # hello.exe = Not allowed
        data_dict["files_optional"]["hello.exe"] = data_dict["files_optional"]["peanut-butter-jelly-time.gif"]
        del data_dict["signs"]  # Remove signs before signing
        data_dict["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(data_dict, sort_keys=True), privatekey)
        }
        data = io.BytesIO(json.dumps(data_dict).encode())
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)
        assert "Optional file not allowed" in str(err.value)
        del data_dict["files_optional"]["hello.exe"]  # Reset

        # Includes not allowed in user content
        data_dict["includes"] = {"other.json": {}}
        del data_dict["signs"]  # Remove signs before signing
        data_dict["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(data_dict, sort_keys=True), privatekey)
        }
        data = io.BytesIO(json.dumps(data_dict).encode())
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(user_inner_path, data, ignore_same=False)
        assert "Includes not allowed" in str(err.value)

    def testCert(self, site):
        # user_addr = "epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len"
        user_priv = "5Kk7FSA63FC2ViKmKLuBxk9gQkaQ5713hKq8LmFAf4cVeXh6K6A"
        # cert_addr = "epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj"
        cert_priv = "5JusJDSjHaMHwUjDT3o6eQ54pA6poo8La5fAgn1wNc3iK59jxjA"

        # Check if the user file is loaded
        assert "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json" in site.content_manager.contents
        user_content = site.content_manager.contents["data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json"]
        rules_content = site.content_manager.contents["data/users/content.json"]

        # Override valid cert signers for the test
        rules_content["user_contents"]["cert_signers"]["epixid.epix"] = [
            "epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj",
            "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
        ]

        # Check valid cert signers
        rules = site.content_manager.getRules("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_content)
        assert rules["cert_signers"] == {"epixid.epix": [
            "epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj",
            "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
        ]}

        # Sign a valid cert
        user_content["cert_sign"] = CryptEpix.sign("epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len#%s/%s" % (
            user_content["cert_auth_type"],
            user_content["cert_user_id"].split("@")[0]
        ), cert_priv)

        # Verify cert
        assert site.content_manager.verifyCert("data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_content)

        # Verify if the cert is valid for other address
        assert not site.content_manager.verifyCert("data/users/badaddress/content.json", user_content)

        # Sign user content
        signed_content = site.content_manager.sign(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_priv, filewrite=False
        )

        # Test user cert
        assert site.content_manager.verifyFile(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
            io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
        )

        # Test banned user
        cert_user_id = user_content["cert_user_id"]  # My username
        site.content_manager.contents["data/users/content.json"]["user_contents"]["permissions"][cert_user_id] = False
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(
                "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
                io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
            )
        assert "Valid signs: 0/1" in str(err.value)
        del site.content_manager.contents["data/users/content.json"]["user_contents"]["permissions"][cert_user_id]  # Reset

        # Test invalid cert
        user_content["cert_sign"] = CryptEpix.sign(
            "badaddress#%s/%s" % (user_content["cert_auth_type"], user_content["cert_user_id"]), cert_priv
        )
        signed_content = site.content_manager.sign(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_priv, filewrite=False
        )
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(
                "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
                io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
            )
        assert "Invalid cert" in str(err.value)

        # Test banned user, signed by the site owner
        user_content["cert_sign"] = CryptEpix.sign("epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len#%s/%s" % (
            user_content["cert_auth_type"],
            user_content["cert_user_id"].split("@")[0]
        ), cert_priv)
        cert_user_id = user_content["cert_user_id"]  # My username
        site.content_manager.contents["data/users/content.json"]["user_contents"]["permissions"][cert_user_id] = False

        site_privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"  # For epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8
        del user_content["signs"]  # Remove signs before signing
        user_content["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(user_content, sort_keys=True), site_privatekey)
        }
        assert site.content_manager.verifyFile(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
            io.BytesIO(json.dumps(user_content).encode()), ignore_same=False
        )

    def testMissingCert(self, site):
        user_priv = "5Kk7FSA63FC2ViKmKLuBxk9gQkaQ5713hKq8LmFAf4cVeXh6K6A"
        cert_priv = "5JusJDSjHaMHwUjDT3o6eQ54pA6poo8La5fAgn1wNc3iK59jxjA"

        user_content = site.content_manager.contents["data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json"]
        rules_content = site.content_manager.contents["data/users/content.json"]

        # Override valid cert signers for the test
        rules_content["user_contents"]["cert_signers"]["epixid.epix"] = [
            "epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj",
            "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
        ]

        # Sign a valid cert
        user_content["cert_sign"] = CryptEpix.sign("epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len#%s/%s" % (
            user_content["cert_auth_type"],
            user_content["cert_user_id"].split("@")[0]
        ), cert_priv)
        signed_content = site.content_manager.sign(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_priv, filewrite=False
        )

        assert site.content_manager.verifyFile(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
            io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
        )

        # Test invalid cert_user_id
        user_content["cert_user_id"] = "nodomain"
        user_content["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(user_content, sort_keys=True), user_priv)
        }
        signed_content = site.content_manager.sign(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_priv, filewrite=False
        )
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(
                "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
                io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
            )
        assert "Invalid domain in cert_user_id" in str(err.value)

        # Test removed cert
        del user_content["cert_user_id"]
        del user_content["cert_auth_type"]
        del user_content["signs"]  # Remove signs before signing
        user_content["signs"] = {
            "epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8": CryptEpix.sign(json.dumps(user_content, sort_keys=True), user_priv)
        }
        signed_content = site.content_manager.sign(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_priv, filewrite=False
        )
        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(
                "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
                io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
            )
        assert "Missing cert_user_id" in str(err.value)


    def testCertSignersPattern(self, site):
        user_priv = "5Kk7FSA63FC2ViKmKLuBxk9gQkaQ5713hKq8LmFAf4cVeXh6K6A"
        cert_priv = "5JusJDSjHaMHwUjDT3o6eQ54pA6poo8La5fAgn1wNc3iK59jxjA"  # For epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj

        user_content = site.content_manager.contents["data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json"]
        rules_content = site.content_manager.contents["data/users/content.json"]

        # Override valid cert signers for the test
        rules_content["user_contents"]["cert_signers_pattern"] = "epix1p9mwm[0-9a-z]"

        # Sign a valid cert
        user_content["cert_user_id"] = "certuser@epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj"
        user_content["cert_sign"] = CryptEpix.sign("epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len#%s/%s" % (
            user_content["cert_auth_type"],
            "certuser"
        ), cert_priv)
        signed_content = site.content_manager.sign(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json", user_priv, filewrite=False
        )

        assert site.content_manager.verifyFile(
            "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
            io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
        )

        # Cert does not matches the pattern
        rules_content["user_contents"]["cert_signers_pattern"] = "epix1p9mwX[0-9a-z]"

        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(
                "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
                io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
            )
        assert "Invalid cert signer: epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj" in str(err.value)

        # Removed cert_signers_pattern
        del rules_content["user_contents"]["cert_signers_pattern"]

        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyFile(
                "data/users/epix1qdjrn09p6m58v4eegjyt32c358rt4u4zy48len/content.json",
                io.BytesIO(json.dumps(signed_content).encode()), ignore_same=False
            )
        assert "Invalid cert signer: epix1p9mwm3cs9eep58wezxm5ygu3x7hceaspv3ddwj" in str(err.value)


    def testNewFile(self, site):
        privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"  # For epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8
        inner_path = "data/users/epix1newuser000000000000000000000000000000/content.json"

        site.storage.writeJson(inner_path, {"test": "data"})
        site.content_manager.sign(inner_path, privatekey)
        assert "test" in site.storage.loadJson(inner_path)

        site.storage.delete(inner_path)

    def testMaxItemsPrune(self, site):
        """Test that sign() auto-prunes data.json arrays exceeding max_items limits"""
        privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"  # For epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8
        user_inner_path = "data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/content.json"
        users_content = site.content_manager.contents["data/users/content.json"]

        # Set max_items rule: only 3 comments allowed
        users_content["user_contents"]["permission_rules"][".*"]["max_items"] = {"comment": 3}

        # Write data.json with 5 comments
        data = {
            "next_comment_id": 6,
            "comment": [
                {"comment_id": i, "body": "msg %d" % i, "post_id": 1, "date_added": 1432491100 + i}
                for i in range(1, 6)
            ]
        }
        site.storage.writeJson("data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/data.json", data)

        # Sign triggers auto-prune before hashing
        site.content_manager.sign(user_inner_path, privatekey)

        # Verify data.json was trimmed to last 3 entries
        pruned_data = site.storage.loadJson("data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/data.json")
        assert len(pruned_data["comment"]) == 3
        # Should keep the last 3 (newest) entries: ids 3, 4, 5
        assert pruned_data["comment"][0]["comment_id"] == 3
        assert pruned_data["comment"][2]["comment_id"] == 5

        # Cleanup
        del users_content["user_contents"]["permission_rules"][".*"]["max_items"]

    def testMaxItemsVerifyReject(self, site):
        """Test that verifyContentInclude rejects content when data.json has too many items"""
        user_inner_path = "data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/content.json"
        users_content = site.content_manager.contents["data/users/content.json"]

        # Set max_items rule
        users_content["user_contents"]["permission_rules"][".*"]["max_items"] = {"comment": 3}

        # Write data.json with 5 comments (exceeds limit)
        data = {
            "next_comment_id": 6,
            "comment": [
                {"comment_id": i, "body": "msg %d" % i, "post_id": 1, "date_added": 1432491100 + i}
                for i in range(1, 6)
            ]
        }
        site.storage.writeJson("data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/data.json", data)

        # Load the user's content.json and call verifyContentInclude directly
        content = site.storage.loadJson(user_inner_path)
        content_size = sum(f["size"] for f in content.get("files", {}).values())
        content_size_optional = sum(f["size"] for f in content.get("files_optional", {}).values())

        with pytest.raises(VerifyError) as err:
            site.content_manager.verifyContentInclude(
                user_inner_path, content, content_size, content_size_optional
            )
        assert "Too many items" in str(err.value)

        # Cleanup
        del users_content["user_contents"]["permission_rules"][".*"]["max_items"]

    def testMaxItemsNoEffect(self, site):
        """Test that max_items has no effect when arrays are under the limit"""
        privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"
        user_inner_path = "data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/content.json"
        users_content = site.content_manager.contents["data/users/content.json"]

        # Set generous max_items rule
        users_content["user_contents"]["permission_rules"][".*"]["max_items"] = {"comment": 100}

        # Write data.json with only 2 comments
        data = {
            "next_comment_id": 3,
            "comment": [
                {"comment_id": 1, "body": "first", "post_id": 1, "date_added": 1432491100},
                {"comment_id": 2, "body": "second", "post_id": 1, "date_added": 1432491200}
            ]
        }
        site.storage.writeJson("data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/data.json", data)

        # Sign — should not prune
        site.content_manager.sign(user_inner_path, privatekey)

        # Verify data unchanged
        result = site.storage.loadJson("data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/data.json")
        assert len(result["comment"]) == 2

        # Cleanup
        del users_content["user_contents"]["permission_rules"][".*"]["max_items"]

    def testMaxItemsMultipleKeys(self, site):
        """Test that max_items prunes multiple array keys independently"""
        privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"
        user_inner_path = "data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/content.json"
        users_content = site.content_manager.contents["data/users/content.json"]

        # Set max_items for two different keys
        users_content["user_contents"]["permission_rules"][".*"]["max_items"] = {
            "comment": 3,
            "comment_vote": 2
        }

        # Write data.json with both arrays exceeding limits
        data = {
            "next_comment_id": 6,
            "comment": [
                {"comment_id": i, "body": "msg %d" % i, "post_id": 1, "date_added": 1432491100 + i}
                for i in range(1, 6)
            ],
            "comment_vote": [
                {"vote_id": i, "comment_id": i, "vote": 1}
                for i in range(1, 5)
            ]
        }
        site.storage.writeJson("data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/data.json", data)

        # Sign triggers auto-prune
        site.content_manager.sign(user_inner_path, privatekey)

        # Verify both arrays were pruned independently
        result = site.storage.loadJson("data/users/epix1xmgvagtwxlz25w867zra4tzucuwxy7jjukpadj/data.json")
        assert len(result["comment"]) == 3
        assert len(result["comment_vote"]) == 2
        # Last 3 comments kept
        assert result["comment"][0]["comment_id"] == 3
        # Last 2 votes kept
        assert result["comment_vote"][0]["vote_id"] == 3

        # Cleanup
        del users_content["user_contents"]["permission_rules"][".*"]["max_items"]
