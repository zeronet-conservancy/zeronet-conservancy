from collections.abc import Iterable

from Config import config

from rich import print

import json
import requests
from lib.canonicjson.Canonicalize import canonicalize

class DbError(Exception):
    """Exceptions related to working with new style DB"""
    pass

def pathToHash(inner_path):
    """Replace 'inner_path' with signature that we're working with internally"""
    if len(inner_path) == 0:
        raise FileNotFoundError("Empty path doesn't point to a valid record")
    if inner_path[0] == '/':
        inner_path = inner_path[1:]
    if '/' in inner_path:
        raise FileNotFoundError(f"Our db <-> fs schema does not allow directories (while processing {inner_path})")
    if not inner_path.endswith('.json'):
        raise FileNotFoundError(f"File {inner_path} isn't json file and thus not found")
    maybe_base32_signature = inner_path.removesuffix('.json')
    # maybe check some more?
    return maybe_base32_signature

def dbQuery(author=None, signature=None):
    """Query DB

    Currently this accesses PostgREST API and returns parsed JSON
    API point can be configured in Config.py
    """
    filter_by = {}
    if author:
        filter_by['author'] = f'eq.{author}'
    if signature:
        filter_by['signature'] = f'eq.{signature}'
    return requests.get(f'{config.postgrest_api}/{config.postgrest_db}', params=filter_by).json()

def dbInsert(author, signature, data):
    """Add data record into db"""
    # check for duplicates maybe
    print(f'>>> dbInsert {data}')
    params = {
        "author": author,
        "signature": signature,
        "data": data
    }
    resp = requests.post(f'{config.postgrest_api}/riza0', json=params)
    print(resp, resp.text)

def contentJsonRead(author):
    obj = requests.get(f'{config.postgrest_api}/contentjson', params={'author': f'eq.{author}'}).json()
    if len(obj) != 1:
        raise DbError(f'Bad content.json! Expecting 1, but got {len(obj)} results')
    return obj[0]['content']

def contentJsonWrite(author: str, content: str):
    print('>>> contentJsonWrite')
    params = {'author': f'eq.{author}'}
    data = {'author': author, 'content': content}
    resp = requests.put(f'{config.postgrest_api}/contentjson', params=params, json=data)
    print(resp, resp.text)

class SiteDbStorage:
    """Alternative way of storing sites, directly in DB

    Instead of storing files, we store json objects, but from the old 0net PoV
    they are files with name derived from signature

    The public API is made compatible with SiteStorage for easier transition,
    subject to change later.
    """
    def __init__(self, site, allow_create=True):
        self.log = site.log
        self.author = site.address
        self.allow_create = allow_create

        # compat
        self.has_db = False

    def deprecated(self, msg):
        """Emits deprecation warning. Can be overridden to throw instead"""
        self.log.warning(msg)

    def getRecord(self, signature):
        self.log.debug(f'access {signature}')
        results = dbQuery(author=self.author, signature=signature)
        if len(results) == 0:
            raise DbError(f'Cannot find {signature} by {self.author}')
        if len(results) > 1:
            raise DbError(f'Too many results when looking for unique record @ {signature}. Is your DB sane?')
        return results[0]

    def hasRecord(self, signature):
        results = dbQuery(author=self.author, signature=signature)
        return len(results) > 0

    #######################################
    ## SiteStorage-compat deprecated API ##
    def getDbFile(self):
        """Compatibility with SiteStorage"""
        self.deprecated('Deprecated SiteStorage compat method called: getDbFile')
        return False

    def closeDb(self):
        """Compatibility with SiteStorage"""
        self.deprecated('Deprecated SiteStorage compat method called: closeDb')

    def rebuildDb(self):
        """Compatibility with SiteStorage"""
        self.deprecated('Deprecated SiteStorage compat method called: rebuildDb')

    def query(self, query, params=None):
        """Compatibility with SiteStorage"""
        self.deprecated('Deprecated SiteStorage compat method called: query')
        raise RuntimeError(".query method shouldn't be used with SiteDbStorage")

    def open(self, inner_path, mode="rb", create_dirs=False, **kwargs):
        """Compatibility with SiteStorage"""
        self.deprecated('Deprecated SiteStorage compat method called: open')
        # we actually should let files be read, but we can skip writes as it seems
        # unused unless file is changed (which we don't support anyway)

        if 'w' in mode:
            raise DbError('SiteDbStorage.open does not support writing!')
        if 'b' in mode:
            cl = io.BytesIO
        else:
            cl = io.StringIO
        return cl(self.read(inner_path, mode))

    def read(self, inner_path, mode="rb"):
        """Open & read the whole file. Compatibility with SiteStorage"""
        self.deprecated('Deprecated SiteStorage compat method called: read')

        if inner_path.removeprefix('/') == 'content.json':
            res = contentJsonRead(self.author)
            if 'b' in mode:
                return res.encode('utf8')
            return res

        obj = self.getRecord(pathToHash(inner_path))['data']
        result = canonicalize(obj)
        if 'b' in mode:
            return result.encode('utf-8')
        return result

    def write(self, inner_path, content):
        """Overwrite 'file' content. Compatibility with SiteStorage"""
        self.deprecated(f'Deprecated SiteStorage compat method called: write {inner_path}')
        if not self.allow_create:
            raise DbError('SiteDbStorage opened read-only, but write() attempted')

        if type(content) == bytes:
            content = content.decode('utf8')
        if inner_path.removeprefix('/') == 'content.json':
            return contentJsonWrite(self.author, content)

        signature = pathToHash(inner_path)
        print(f'got {signature=}')

        try:
            content_body = content.read()
        except AttributeError:
            content_body = content
        data = json.loads(content_body)

        if content_body != canonicalize(data):
            print(content_body)
            print('=====')
            print(canonicalize(data))
            raise DbError('Attempt to write non-canonical JSON')
        # if exists and not same content:
            # raise DbError('Record already exists, but is different. Something is utterly broken here :(')
        dbInsert(self.author, signature, data)

    def delete(self, inner_path):
        """Compatibility with SiteStorage, ignored"""
        self.deprecated('Deprecated SiteStorage compat method called: delete')

    def deleteDir(self, inner_path):
        """Compatibility with SiteStorage, ignored"""
        self.deprecated('Deprecated SiteStorage compat method called: deleteDir')

    def rename(self, inner_path_before, inner_path_after):
        """Compatibility with SiteStorage, ignored"""
        self.deprecated('Deprecated SiteStorage compat method called: rename')

    def walk(self, dir_inner_path: str, ignore=None) -> Iterable[str]:
        """Compatibility with SiteStorage. List files in a directory"""
        self.deprecated('Deprecated SiteStorage compat method called: walk')
        return [f"{x['signature']}.json" for x in dbQuery(author=self.author)] + ['content.json']

    def list(self, dir_inner_path):
        """Compatibility with SiteStorage. List directories, but we have none"""
        self.deprecated('Deprecated SiteStorage compat method called: list')
        return []

    def onUpdated(self, inner_path, file=None):
        """Compatibility with SiteStorage. Ignored"""
        self.deprecated('Deprecated SiteStorage compat method called: onUpdated')

    def loadJson(self, inner_path):
        """Compatibility with SiteStorage. Return JSON object from path"""
        self.deprecated('Deprecated SiteStorage compat method called: loadJson')
        if inner_path.removeprefix('/') == 'content.json':
            return json.loads(contentJsonRead(self.author))

        return self.getRecord(pathToHash(inner_path))['data']

    def writeJson(self, inner_path, data):
        """Compatibility with SiteStorage. Write JSON to path

        Note that it's only ever used in 0net codebase for writing content.json
        so we don't have to implement it for anything else
        """
        self.deprecated('Deprecated SiteStorage compat method called: writeJson')
        if inner_path.removeprefix('/') != 'content.json':
            raise DbError('SiteDbStorage.writeJson is only implemented for writing content.json')
        # it generally doesn't matter to old style 0net sites how content.json is formatted
        # but we'll stick with tradition
        data = helper.jsonDumps(data).encode('utf8')

        contentJsonWrite(self.author, data)

    def getSize(self, inner_path):
        """Compatibility with SiteStorage. Returns size of a record in bytes"""
        self.deprecated('Deprecated SiteStorage compat method called: getSize')
        # TODO: we should probably cache size 'cause it is going to be used in
        # calculating how much space data from a particular author is occupying
        return len(self.read(inner_path))

    def isFile(self, inner_path):
        return inner_path == 'content.json' or self.hasRecord(pathToHash(inner_path))

    def getPath(self, inner_path):
        """Compatibility with SiteStorage. Throws exception as we don't store files"""
        raise RuntimeError('getPath called, but we store in database')

    def getInnerPath(self, path):
        """Compatibility with SiteStorage. Throws exception as we don't store files"""
        raise RuntimeError('getInnerPath called, but we store in database')

    def verifyFiles(self, quick_check=False, add_optional=False, add_changed=True):
        """Compatibility with SiteStorage, ignored"""
        self.deprecated('Deprecated SiteStorage compat method called: verifyFiles')
        return {'bad_files':[]}

    def updateBadFiles(self, quick_check=True):
        """Compatibility with SiteStorage, ignored"""
        self.deprecated('Deprecated SiteStorage compat method called: updateBadFiles')

    def deleteFiles(self):
        """Compatibility with SiteStorage; delete all site data"""
        self.deprecated('Deprecated SiteStorage compat method called: deleteFiles')
        # if self.????
        raise NotImplementedError('???')
