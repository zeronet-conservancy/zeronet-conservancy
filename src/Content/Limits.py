"""New-style content storage limits.

WIP
"""

from rich import print

def applyLimitRules(rules):
    print("Rules before limits")
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
