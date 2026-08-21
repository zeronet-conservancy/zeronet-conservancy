"""Trio/Starlette port of plugins/disabled-UiPassword/UiPasswordPlugin.py
-- a single shared password gating the whole web UI, cookie-session-based.
Off by default in the legacy stack too (plugin_info.json's own
"default": "disabled"), so this is opt-in here as well: UiApp only wires
any of this in when constructed with a non-empty ui_password.

Real, not faked, but two legacy pieces are deliberately NOT ported:
  - Client-id (IP + User-Agent) whitelisting, which let a browser skip
    re-authenticating on raw, cookieless asset requests. That existed
    because the original serves site content on a SEPARATE port
    (ui_site_port) from the login-gated dashboard port, so a same-origin
    cookie wasn't guaranteed to reach a site-content request. This stack
    already collapsed both onto one port (see UiServer.py's own module
    docstring on the wrapper=0 single-port substitute), so every request
    here is same-origin and carries the session cookie already -- the
    whitelist existed to route around a problem this stack doesn't have.
  - config.ui_restrict (per-IP allowlist) and the addHomepageNotifications
    "you forgot to set a password" advisory -- separate features, not
    part of "gate the UI behind a password," left for their own pass.

Session expiry is checked lazily at lookup time (an expired session_id is
evicted the moment something looks it up and finds it stale) rather than
the original's periodic hourly sweep (sessionCleanup(), invoked inline on
whatever request happens to land after an hour has passed) -- observably
identical (an expired session is never accepted either way), simpler,
and needs no background task or nursery.
"""
import secrets
import time

SESSION_COOKIE = "session_id"
SESSION_MAX_AGE = 60 * 60 * 24            # 24h for a plain login
SESSION_MAX_AGE_KEEP = 60 * 60 * 24 * 60  # 60 days for "keep me logged in"

# Real production asset (plugins/disabled-UiPassword/login.html), ported
# verbatim except: the original's server-side "{result}" templating (Python
# string substitution) becomes a query-string flag the page's own existing
# inline JS already knows how to act on (badPassword()), so no server-side
# templating engine is needed for one boolean.
LOGIN_HTML = """<html>
<head>
 <title>Log In</title>
 <meta name="viewport" id="viewport" content="width=device-width, initial-scale=1.0">
</head>

<style>
body {
\tbackground-color: #323C4D; font-family: "Segoe UI", Helvetica, Arial; font-weight: lighter;
    font-size: 22px; color: #333; letter-spacing: 1px; color: white; overflow: hidden;
}
.login { left: 50%; position: absolute; top: 50%; transform: translateX(-50%) translateY(-50%); -webkit-transform: translateX(-50%) translateY(-50%); width: 100%; max-width: 370px; text-align: center; }

*:focus { outline: 0; }
input[type=text], input[type=password] {
\tpadding: 10px 0px; border: 0px; display: block; margin: 15px 0px; width: 100%; border-radius: 30px; transition: 0.3s ease-out; background-color: #DDD;
\ttext-align: center; font-family: "Segoe UI", Helvetica, Arial; font-weight: lighter; font-size: 28px; border: 2px solid #323C4D;
}
input[type=text]:focus, input[type=password]:focus {
\tborder: 2px solid #FFF; background-color: #FFF;
}
input[type=checkbox] { opacity: 0; }
input[type=checkbox]:checked + label { color: white; }
input[type=checkbox]:focus + label::before { background-color: #435065; }
input[type=checkbox]:checked + label::before { box-shadow: inset 0px 0px 0px 5px white; background-color: #4DCC6E; }
input.error { border: 2px solid #F44336 !important; animation: shake 1s }
label::before {
\tcontent: ""; width: 20px; height: 20px; background-color: #323C4D;
\tdisplay: inline-block; margin-left: -20px; border-radius: 15px; box-shadow: inset 0px 0px 0px 2px #9EA5B3;
\ttransition: all 0.1s; margin-right: 7px; position: relative; top: 2px;
}
label { vertical-align: -1px; color: #9EA5B3; transition: all 0.3s; }

.button {
\tpadding: 13px; display: inline-block; margin: 15px 0px; width: 100%; border-radius: 30px; text-align: center; white-space: nowrap;
\tfont-size: 28px; color: #333; background: linear-gradient(45deg, #6B14D3 0, #7A26E2 25%, #4962DD 90%);
    box-sizing: border-box; margin-top: 50px; color: white; text-decoration: none; transition: 0.3s ease-out;
}
.button:hover, .button:focus { box-shadow: 0px 5px 30px rgba(0,0,0,0.3); }
.button:active { transform: translateY(1px); box-shadow: 0px 0px 20px rgba(0,0,0,0.5); transition: none; }

#login_form_submit { display: none; }

.login-anim { animation: login 1s cubic-bezier(0.785, 0.135, 0.15, 0.86) forwards; }

@keyframes login {
    0%   { width: 100%; }
    60%  { width: 63px; transform: scale(1); color: rgba(255,255,255,0); }
    70%  { width: 63px; transform: scale(1); color: rgba(255,255,255,0); }
    100% { transform: scale(80); width: 63px; color: rgba(255,255,255,0); }
}

@keyframes shake {
    0%, 100% { transform: translateX(0); }
    10%, 30%, 50%, 70%, 90% { transform: translateX(-10px); }
    20%, 40%, 60%, 80% { transform: translateX(10px); }
}
</style>

<body>


<div class="login">
 <form action="" method="post" id="login_form" onkeypress="return onFormKeypress(event)">
  <input type="password" name="password" placeholder="Password" required/>
  <input type="checkbox" name="keep" id="keep"><label for="keep">Keep me logged in</label>
  <div style="clear: both"></div>
  <a href="#" class="button" onclick="return submit()" id="login_button"><span>Log In</span></a>
  <input type="submit" id="login_form_submit"/>
 </form>
</div>


<script>

function onFormKeypress(event) {
\tif (event.keyCode == 13) {
\t\tsubmit()
\t\treturn false
\t}
}

function submit() {
\tvar form = document.getElementById("login_form")
\tif (form.checkValidity()) {
\t\tdocument.getElementById("login_button").className = "button login-anim"
\t\tsetTimeout(function() {
\t\t\tform.submit()
\t\t}, 1000)
\t} else {
\t\tform.submit()
\t}
\treturn false
}

function badPassword() {
\tvar elem = document.getElementsByName("password")[0]
\telem.className = "error"
\telem.placeholder = "Wrong Password"
\telem.focus()
\telem.addEventListener('input', function() {
\t\telem.className = ""
\t\telem.placeholder = "Password"
\t})
}

result = "__LOGIN_RESULT__"

if (result == "bad_password")
\tbadPassword()

</script>

</body>
</html>"""


class SessionStore:
    """In-memory session_id -> expiry map. Not persisted -- restarting the
    server logs everyone out, matching the original's own module-level
    (process-lifetime-only) `sessions` dict."""

    def __init__(self):
        self._expiry: dict[str, float] = {}

    def create(self, keep: bool) -> str:
        session_id = secrets.token_urlsafe(20)
        ttl = SESSION_MAX_AGE_KEEP if keep else SESSION_MAX_AGE
        self._expiry[session_id] = time.time() + ttl
        return session_id, ttl

    def valid(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        expiry = self._expiry.get(session_id)
        if expiry is None:
            return False
        if expiry < time.time():
            del self._expiry[session_id]
            return False
        return True

    def delete(self, session_id: str | None) -> None:
        if session_id:
            self._expiry.pop(session_id, None)


def renderLogin(bad_password: bool = False) -> str:
    return LOGIN_HTML.replace("__LOGIN_RESULT__", "bad_password" if bad_password else "")


class PasswordGateMiddleware:
    """Plain ASGI middleware, not BaseHTTPMiddleware -- this needs to see
    (and immediately ignore) websocket scope too, since a page that
    already passed the HTTP gate embeds the real wrapper_key in its own
    markup, and the websocket connection built from that is already
    implicitly gated (nothing hands out a valid wrapper_key without going
    through an authenticated HTTP response first). Exempting the whole
    "websocket" scope type here, rather than trying to check a cookie on
    the websocket handshake too, matches that model."""

    EXEMPT_PATHS = ("/Login", "/Logout")

    def __init__(self, app, sessions: SessionStore):
        self.app = app
        self.sessions = sessions

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self.EXEMPT_PATHS or scope["path"].startswith("/uimedia/"):
            return await self.app(scope, receive, send)
        cookies = _parseCookieHeader(scope)
        if self.sessions.valid(cookies.get(SESSION_COOKIE)):
            return await self.app(scope, receive, send)
        query = ("?" + scope["query_string"].decode("latin1")) if scope.get("query_string") else ""
        next_url = scope["path"] + query
        response_start = {
            "type": "http.response.start", "status": 303,
            "headers": [(b"location", ("/Login?next=" + _urlEncode(next_url)).encode("latin1"))],
        }
        await send(response_start)
        await send({"type": "http.response.body", "body": b""})


def _parseCookieHeader(scope) -> dict:
    for name, value in scope.get("headers", ()):
        if name == b"cookie":
            cookies = {}
            for part in value.decode("latin1").split(";"):
                if "=" in part:
                    key, val = part.strip().split("=", 1)
                    cookies[key] = val
            return cookies
    return {}


def _urlEncode(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")
