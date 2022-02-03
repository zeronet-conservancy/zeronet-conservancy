##
##  Copyright (c) 2022 caryoscelus
##
##  zeronet-conservancy is free software: you can redistribute it and/or modify it under the
##  terms of the GNU General Public License as published by the Free Software
##  Foundation, either version 3 of the License, or (at your option) any later version.
##
##  zeronet-conservancy is distributed in the hope that it will be useful, but
##  WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
##  FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
##  details.
##
## You should have received a copy of the GNU General Public License along with
## zeronet-conservancy. If not, see <https://www.gnu.org/licenses/>.
##

import re
from Plugin import PluginManager

# based on the code from Multiuser plugin
@PluginManager.registerTo("UiRequest")
class NoNewSites(object):
    def __init__(self, *args, **kwargs):
        return super(NoNewSites, self).__init__(*args, **kwargs)
    def actionWrapper(self, path, extra_headers=None):
        match = re.match("/(media/)?(?P<address>[A-Za-z0-9\._-]+)(?P<inner_path>/.*|$)", path)
        if not match:
            self.sendHeader(500)
            return self.formatError("Plugin error", "No match for address found")

        addr = match.group("address")

        if not self.server.site_manager.get(addr):
            self.sendHeader(404)
            return self.formatError("Not Found", "Adding new sites disabled", details=False)
        return super(NoNewSites, self).actionWrapper(path, extra_headers)

    # def parsePath(self, path):
        # return super(NoNewSites, self).parsePath(path)
