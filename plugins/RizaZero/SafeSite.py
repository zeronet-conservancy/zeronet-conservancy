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

"""riza-zero is a plugin for compatibility with new network `riza`

this file supports new safe api
"""

import time
import html
import os
import shutil
import subprocess
import json
import sys
import itertools
import urllib.parse as parse
import requests
import hashlib
import logging
import re
from rich import print
from tempfile import TemporaryDirectory

from Plugin import PluginManager
from Config import config
from util import helper, RateLimit
from Debug import Debug
from Db import Db
from User import UserManager

@PluginManager.registerTo('UiRequest')
class RizaZeroSafeSitePlugin:
    def actionWrapper(self, path, extra_headers=None):
        match = re.match(r'/safe/([a-zA-Z0-9]*)(/?.*?)$', path)
        if not match:
            return super().actionWrapper(path, extra_headers)

        addr, inner_path = match.groups()
        if self.env['REQUEST_METHOD'] == 'GET':
            query = self.env['QUERY_STRING']
            print(addr, inner_path, query)

            site = self.server.site_manager.need(addr)
            if not site:
                self.sendHeader(404, 'text/html')
                return iter([b'no such site'])
            print(site)
            if not site.needFile('safe.json'):
                self.sendHeader(404, 'text/html')
                return iter([
                   b'this site has no support for new safer protocol'])

            with open(f'{config.data_dir}/{addr}/safe.json') as f:
                sf = json.load(f)
            if 'version' not in sf or sf['version'] != 0:
                self.sendHeader(500, 'text/html')
                return iter([b'version not supported'])

            service = sf.get('service', 'haskell')
            # TODO: def include .lhs but also see if extension is
            # a good way to treat this long-term
            if service == 'haskell':
                if inner_path.endswith('.hs'):
                    print('happy haskell!')
                    with TemporaryDirectory() as tmpdir:
                        hspth = f'{config.start_dir}/plugins/RizaZero/hs'
                        tmphs = f'{tmpdir}/hs'

                        shutil.copytree(hspth, tmphs)
                        fpath = f'{config.data_dir}/{addr}/{inner_path}'

                        os.mkdir(f'{tmpdir}/hs/distrusted')

                        ftgt = f'{tmpdir}/hs/distrusted/App.hs'

                        shutil.copy2(fpath, ftgt)
                        proc = subprocess.Popen(
                            ['cabal', '-v0', 'run'], 
                            cwd=tmphs,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
                        res = proc.wait()
                        if res != 0:
                            err = proc.stderr.read()
                            print(err.decode('utf-8'))
                            self.sendHeader(500, 'text/html')
                            return iter([b'bad cabal run'])
                        else:
                            resp = proc.stdout.read()
                            self.sendHeader(200, 'text/html')
                            return iter([resp])
            print(f'unknown service {service} or file {inner_path}')
            self.sendHeader(500, 'text/html')
            return iter([b'unknown service or file\n'])

#    def actionUiMedia(self, path, *args, **kwargs):
#        return super().actionUiMedia(path, *args, **kwargs)
#    def error404(self, path=''):
#        return super().error404(self, path)
