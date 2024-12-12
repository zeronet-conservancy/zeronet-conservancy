import pytest
import json
from Config import config
from User import UserManager

@pytest.mark.usefixtures("resetSettings")
@pytest.mark.usefixtures("resetTempSettings")
class TestMultiuser:
    def testMemorySave(self, user):
        # It should not write users to disk
        users_json = config.private_dir / 'users.json'
        users_before = users_json.open().read()
        user = UserManager.user_manager.create()
        user.save()
        assert users_json.open().read() == users_before
