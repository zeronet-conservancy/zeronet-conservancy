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

currently it supports minimal tracker functionality for riza-mirror
"""

import time
import html
import os
import json
import sys
import itertools

from Plugin import PluginManager
from Config import config
from util import helper, RateLimit
from Debug import Debug
from Db import Db
from User import UserManager

TRACKER_ADDR = '1EQ6gh2eV2crfxEGzmxMk8DHxULuSYyh4N'

@PluginManager.registerTo('UiRequest')
class RizaZero(object):
    # Riza tracker
    @helper.encodeResponse
    def actionRizaTracker0(self):
        site = self.server.sites.get('1EQ6gh2eV2crfxEGzmxMk8DHxULuSYyh4N')
        user = UserManager.user_manager.get()
        if self.env['REQUEST_METHOD'] == 'GET':
            self.sendHeader(200, 'application/json')
            res = site.storage.query('SELECT peerjs_id, timestamp, directory FROM rizatracker_peerjs JOIN json ON rizatracker_peerjs.json_id = json.json_id')
            rows = []
            for row in res:
                r = dict(row)
                r['signed'] = r['directory']
                del r['directory']
                rows.append(r)
            yield json.dumps(rows)
        elif self.env['REQUEST_METHOD'] == 'POST':
            newpeers = self.env['QUERY_STRING']
            peers = []
            for peer in newpeers.split(','):
                res = site.storage.query(f'SELECT peerjs_id, timestamp, directory FROM rizatracker_peerjs JOIN json ON rizatracker_peerjs.json_id = json.json_id WHERE peerjs_id = "{peer}"')
                for x in res:
                    # already exists, we don't care where it lives
                    break
                else:
                    peers.append(peer)
            doAddPeersTo(site, user, peers)
            self.sendHeader(200, 'application/json')
            yield json.dumps({'result':'ok', 'added':peers})
        elif self.env['REQUEST_METHOD'] == 'DELETE':
            delpeers = self.env['QUERY_STRING'].split(',')
            auth = user.getAuthAddress(site.address)
            inner_path = f'data/{auth}/data.json'
            content_path = f'data/{auth}/content.json'
            deleted = []
            if site.storage.isFile(inner_path):
                fc = site.storage.read(inner_path, "r")
                if fc == '':
                    fc = '{}'
                peersTree = json.loads(fc)
                if 'rizatracker_peerjs' not in peersTree:
                    peersTree['rizatracker_peerjs'] = []
                user = UserManager.user_manager.get()
                for peer in delpeers:
                    if peer in [x['peerjs_id'] for x in peersTree['rizatracker_peerjs']]:
                        peersTree['rizatracker_peerjs'] = [x for x in peersTree['rizatracker_peerjs'] if x['peerjs_id'] != peer]
                        deleted.append(peer)
                f = site.storage.open(inner_path, "w")
                json.dump(peersTree, f)
                f.close()
                signAndPublish(user, site, content_path)
            self.sendHeader(200, 'application/json')
            yield json.dumps({'result':'ok', 'deleted':deleted})

def doAddPeersTo(site, user, peers):
    ts = int(time.time())
    xpeers = [{'peerjs_id':x, 'timestamp':ts} for x in peers]
    auth = user.getAuthAddress(site.address)
    inner_path = f'data/{auth}/data.json'
    content_path = f'data/{auth}/content.json'
    if site.storage.isFile(inner_path):
        fc = site.storage.read(inner_path, "r")
        if not fc:
            fc = '{}'
        peersTree = json.loads(fc)
        if 'rizatracker_peerjs' not in peersTree:
            peersTree['rizatracker_peerjs'] = []
        peersTree['rizatracker_peerjs'].extend(xpeers)
    else:
        peersTree = {'rizatracker_peerjs':xpeers}
        dp = site.storage.getPath('/'.join(inner_path.split('/')[:-1]))
        if not os.path.isdir(dp):
            os.mkdir(dp)
    f = site.storage.open(inner_path, "w")
    json.dump(peersTree, f)
    f.close()
    signAndPublish(user, site, content_path)

def signAndPublish(user, site, inner_path):
    succ = None
    privatekey = user.getAuthPrivatekey(site.address)
    try:
        succ = site.content_manager.sign(
            inner_path=inner_path, privatekey=privatekey,
            update_changed_files=True
        )
    except Exception as err:
        logging.error("Sign error: %s" % Debug.formatException(err))
        succ = False
    if succ:
        site.content_manager.loadContent(inner_path, add_bad_files=False)
        event_name = f"publish {site.address} {inner_path}"
        called_instantly = RateLimit.isAllowed(event_name, 30)
        thread = RateLimit.callAsync(event_name, 30,
            lambda: site.publish(inner_path=inner_path))
