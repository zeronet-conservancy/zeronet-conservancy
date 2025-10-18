"""Handling of (public) user info records in db
"""

from json.decoder import JSONDecodeError
from .ContentDb import getContentDb

def updateUserData(site, inner_path, content):
    if inner_path != 'profile/content.json':
        return

    cdb = getContentDb()
    try:
        profile = site.storage.loadJson('profile/profile.json')
        username = profile['username']
    except (FileNotFoundError, JSONDecodeError, KeyError):
        # user failed to have a valid profile.., but we still keep or
        # even create record because there's profile/ present
        username = '<unknown>'
    query = '''
        INSERT INTO user ?
        ON CONFLICT(address) DO
            UPDATE SET username=excluded.username
    '''
    cdb.execute(query, {
        'address': site.address,
        'username': username,
    })
