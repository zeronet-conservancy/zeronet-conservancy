from . import SiteManagerPlugin  # noqa: F401 -- import side effect registers the SiteManager.add() override
from . import SitePlugin  # noqa: F401 -- import side effect registers the Site.needFile() mute check
from . import SiteStoragePlugin  # noqa: F401 -- import side effect registers the updateDbFile() mute check
from . import commands  # noqa: F401 -- import side effect registers the plugin's commands
