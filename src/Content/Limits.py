"""New-style content storage limits. WIP

Currently allows merging limits from subscriptions to sites,
reading both content.json with user limit data from old
moderation style, as well as lists intended specifically
for new style user-based moderation.
"""

from rich import print
from .ContentDb import getContentDb, ContentDb

def applyLimitRules(rules):
    print("Rules before limits")
    if not rules:
        return rules
    print(rules)
    if 'user_address' not in rules:
        # TODO
        return rules
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
    # ??
    res = db.execute(
        'SELECT * FROM size_limit WHERE site_id IN (SELECT site_id FROM site WHERE ?',
        {'address': address}
    )

def updateLimitDataForSite(site):
    """Update limit data for each content.json on given site"""
    # TODO: more effective?
    removeAllSiteLimits(site)
    for inner_path, content in site.content_manager.contents.items():
        updateLimitData(site, inner_path, content)

def removeAllSiteLimits(site):
    """Remove limit data associated with site"""
    cdb = getContentDb()
    cdb.execute('DELETE FROM size_limit WHERE source = ?', (site.address,))

def updateLimitData(site, inner_path, content):
    priority = site.settings.get('use_limit_priority')

    if priority is None:
        removeAllSiteLimits(site)
        return

    cdb = getContentDb()

    # Clean previous entries from this file
    # TODO: make updating more effecient maybe?
    cdb.execute(
        'DELETE FROM size_limit WHERE source = ? AND inner_path = ?',
        (site.address, inner_path,),
    )

    if 'user_limits' in content:
        for target, limit_rule in content['user_limits'].items():
            addLimitRule(
                target,
                site.address,
                inner_path,
                False,
                priority,
                **limit_rule,
            )
    if 'user_contents' not in content:
        return

    permission_rules = content['user_contents'].get('permissions')
    if permission_rules is None:
        return

    for target, rules in permission_rules.items():
        limit_rule = convertRules(rules)
        addLimitRule(
            cdb,
            target,
            site.address,
            inner_path,
            False,
            priority,
            **limit_rule,
        )

def addLimitRule(
        cdb: ContentDb,
        target: str,
        source: str,
        inner_path: str,
        is_private: bool,
        priority: int,
        rule: str,
        value: int
):
    cdb.execute('INSERT INTO size_limit ?', {
        'address': target,
        'source': source,
        'inner_path': inner_path,
        'is_private': is_private,
        'priority': priority,
        'rule': rule,
        'value': value,
    })

def convertRules(rules):
    if not rules or 'max_size' not in rules:
        return {
            'rule': 'limit',
            'value': 0,
        }
    return {
        'rule': 'allow',
        'value': rules['max_size'],
    }
