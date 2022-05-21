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
import urllib.parse as parse
import requests
import hashlib
import logging

from Plugin import PluginManager
from Config import config
from util import helper, RateLimit
from Debug import Debug
from Db import Db
from User import UserManager

RIZA_ADDR = '1EQ6gh2eV2crfxEGzmxMk8DHxULuSYyh4N'

@PluginManager.registerTo('UiRequest')
class RizaZeroTracker(object):
    @helper.encodeResponse
    def actionRizaTracker0(self):
        """riza tracker"""
        site = self.server.sites.get(RIZA_ADDR)
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

    @helper.encodeResponse
    def actionRizaMirror(self):
        """request or get mirrored data

        /RizaMirror?url=https://example.com&mirror=1
        """
        site = self.server.sites.get(RIZA_ADDR)
        user = UserManager.user_manager.get()
        query = parse.parse_qs(self.env['QUERY_STRING'])
        if 'url' not in query:
            self.sendHeader(400, 'application/json')
            yield json.dumps({'result':'error', 'error':'no url provided'})
            return
        mirror = bool(int(query['mirror'][-1])) if 'mirror' in query else False
        url = parse.quote(query['url'][-1])
        if self.env['REQUEST_METHOD'] == 'GET':
            res = site.storage.query(f'SELECT timestamp, hash, directory FROM rizamirror_map JOIN json ON rizamirror_map.json_id = json.json_id WHERE url = "{url}"')
            rows = []
            for row in res:
                r = dict(row)
                r['signed'] = r['directory']
                del r['directory']
                rows.append(r)
            if mirror:
                # CHECK IF WE WANT TO DO IT
                mr = mirrorUrl(site, parse.unquote(url))
                if mr:
                    shash, auth = mr
                    ts = int(time.time())
                    addUrlHashToDb(site, user, url, shash, ts)
                    rows.append({'timestamp':ts, 'hash':shash, 'signed':auth})
            self.sendHeader(200, 'application/json')
            yield json.dumps(rows)

    @helper.encodeResponse
    def actionRizaGetHash(self):
        site = self.server.sites.get(RIZA_ADDR)
        user = UserManager.user_manager.get()
        query = parse.parse_qs(self.env['QUERY_STRING'])
        shash = query['hash'][-1]
        signed = query['signed'][-1]
        inner_file = f'data/{signed}/{shash}'
        self.sendHeader(200, 'text/html')
        yield site.storage.read(inner_file)

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

def mirrorUrl(site, url):
    # TODO: check if we want/can mirror it
    resp = requests.get(url)
    if resp.status_code == 200:
        text = resp.text.encode('utf-8')
        shash = hashlib.sha256(text).hexdigest()
        user = UserManager.user_manager.get()
        auth = user.getAuthAddress(site.address)
        inner_path = f'data/{auth}/{shash}'
        content_path = f'data/{auth}/content.json'
        site.storage.write(inner_path, text)
        if not site.storage.isFile(content_path):
            site.storage.write(content_path, b"{}")
        r = site.storage.read(content_path)
        if not r:
            r = b"{}"
        content_json = json.loads(r.decode('utf-8'))
        content_json['optional'] = "(?!data.json).*"
        site.storage.write(content_path, json.dumps(content_json).encode('utf-8'))
        signAndPublish(user, site, content_path)
        return (shash, auth)
    return None

def addUrlHashToDb(site, user, url, shash, ts):
    auth = user.getAuthAddress(site.address)
    inner_path = f'data/{auth}/data.json'
    content_path = f'data/{auth}/content.json'
    fc = b''
    if site.storage.isFile(inner_path):
        fc = site.storage.read(inner_path, "r")
    if not fc:
        fc = b'{}'
    jsonTree = json.loads(fc)
    if 'rizamirror_map' not in jsonTree:
        jsonTree['rizamirror_map'] = []
    jsonTree['rizamirror_map'].append({'url':url, 'timestamp':ts, 'hash':shash})
    f = site.storage.open(inner_path, "w")
    json.dump(jsonTree, f)
    f.close()
    signAndPublish(user, site, content_path)
