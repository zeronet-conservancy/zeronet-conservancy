"""Home for trio-native plugins, loaded by P2P.PluginManager against
P2P.* classes (P2P.Site, P2P.SiteManager, P2P.SiteAnnouncer, ...) --
NOT the same plugin ecosystem as the repo-root plugins/ directory, which
is legacy, gevent-era plugins registered against Site/SiteManager/etc via
Plugin.PluginManager and still loaded by the still-live main.py/
Actions.py entrypoint.

The split is deliberate, not incidental: main.py/Actions.py's gevent-era
app and P2P.app's trio-native app are two separate, non-coexisting
processes (see P2P/app.py's own module docstring for why). If a
trio-native plugin port lived in repo-root plugins/ under the same
directory name as the gevent original, loading it under the legacy
PluginManager would import the trio-native rewrite instead -- wrong
classes, wrong async model, breaking the still-live legacy app for a
plugin nothing has actually finished replacing yet. Every plugin here is
therefore a distinct package (P2P/plugins/Foo), independent of whether
repo-root plugins/Foo also exists for the legacy stack -- the two may
happen to share a directory *name* on purpose, to make clear which
plugin they're a port of, but never a directory *path*.
"""
