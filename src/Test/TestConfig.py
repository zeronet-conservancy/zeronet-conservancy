import pytest

import Config


@pytest.mark.usefixtures("resetSettings")
class TestConfig:
    def testParse(self):
        # Defaults
        config_test = Config.Config("zeronet.py".split(" "))
        config_test.parse(silent=True, parse_config=False)
        assert not config_test.debug
        assert not config_test.debug_socket

        # Test parse command line with unknown parameters (some_unregistered_option --
        # ui_password used to be the stand-in example here, until it became a real
        # registered flag, --ui-password, for the P2P stack's UiPassword port)
        config_test = Config.Config("zeronet.py --debug --debug_socket --some_unregistered_option hello".split(" "))
        config_test.parse(silent=True, parse_config=False)
        assert config_test.debug
        assert config_test.debug_socket
        with pytest.raises(AttributeError):
            config_test.some_unregistered_option

        # More complex test
        args = "zeronet.py --unknown_arg --debug --debug_socket --ui_restrict 127.0.0.1 1.2.3.4 "
        args += "--another_unknown argument --use_openssl False siteSign address privatekey --inner_path users/content.json"
        config_test = Config.Config(args.split(" "))
        config_test.parse(silent=True, parse_config=False)
        assert config_test.debug
        assert "1.2.3.4" in config_test.ui_restrict
        assert not config_test.use_openssl
        assert config_test.inner_path == "users/content.json"
