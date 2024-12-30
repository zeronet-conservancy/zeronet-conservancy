"""New-style content storage limits.

WIP
"""

from rich import print
from .ContentDb import getContentDb

def applyLimitRules(rules):
    print("Rules before limits")
    print(rules)
    cdb = getContentDb()
    limits = cdb.getSizeLimitRulesFor(rules['user_address'])
    print(limits)
    max_size = rules['max_size']
    for limit in limits:
        if limit['rule'] == 'allow':
            max_size = max(limit['value'], max_size)
        elif limit['rule'] == 'limit':
            max_size = min(limit['value'], max_size)
    print("After limits")
    rules['max_size'] = max_size
    print(rules)
    return rules

def canPost(user_address):
    # TODO
    return True

def getSiteLimit(address):
    res = db.execute(
        'SELECT * FROM size_limit WHERE site_id IN (SELECT site_id FROM site WHERE ?',
        {'address': address}
    )
