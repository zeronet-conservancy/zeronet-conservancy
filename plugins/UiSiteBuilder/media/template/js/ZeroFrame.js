/* ZeroFrame - minimal site-side API for 0net (zero dependency).
 * Exposes window.ZeroFrame and window.zeroframe.
 * Commands not handled by the wrapper (e.g. fileGet, dbQuery, sitePublish)
 * are proxied to the 0net websocket server.
 */
(function () {
  "use strict";

  var CMD_INNER_READY = "innerReady";
  var CMD_RESPONSE = "response";
  var CMD_WRAPPER_READY = "wrapperReady";
  var CMD_PING = "ping";
  var CMD_PONG = "pong";
  var CMD_WRAPPER_OPENED_WEBSOCKET = "wrapperOpenedWebsocket";
  var CMD_WRAPPER_CLOSE_WEBSOCKET = "wrapperClosedWebsocket";

  function ZeroFrame() {
    this.waiting_cb = {};
    this.next_message_id = 1;
    var m = (document.location.href.match(/wrapper_nonce=([A-Za-z0-9]+)/) || []);
    this.wrapper_nonce = m[1] || "";
    this.target = window.parent;
    this.onOpenWebsocket = null;
    this.onCloseWebsocket = null;
    window.addEventListener("message", this.onMessage.bind(this), false);
    this.cmd(CMD_INNER_READY);
  }

  ZeroFrame.prototype.onMessage = function (e) {
    var message = e.data;
    if (!message || !message.cmd) return;
    if (message.cmd === CMD_RESPONSE) {
      if (this.waiting_cb[message.to]) {
        this.waiting_cb[message.to](message.result);
        delete this.waiting_cb[message.to];
      }
    } else if (message.cmd === CMD_WRAPPER_READY) {
      this.cmd(CMD_INNER_READY);
    } else if (message.cmd === CMD_PING) {
      this.response(message.id, CMD_PONG);
    } else if (message.cmd === CMD_WRAPPER_OPENED_WEBSOCKET) {
      if (this.onOpenWebsocket) this.onOpenWebsocket();
    } else if (message.cmd === CMD_WRAPPER_CLOSE_WEBSOCKET) {
      if (this.onCloseWebsocket) this.onCloseWebsocket();
    }
  };

  ZeroFrame.prototype.response = function (to, result) {
    this.send({ cmd: CMD_RESPONSE, to: to, result: result });
  };

  ZeroFrame.prototype.cmd = function (cmd, params, cb) {
    if (typeof params === "function") { cb = params; params = {}; }
    if (params == null) params = {};
    this.send({ cmd: cmd, params: params }, cb);
  };

  ZeroFrame.prototype.cmdp = function (cmd, params) {
    var self = this;
    return new Promise(function (resolve, reject) {
      self.cmd(cmd, params, function (res) {
        if (res && res.error) reject(new Error(res.error));
        else resolve(res);
      });
    });
  };

  ZeroFrame.prototype.send = function (message, cb) {
    message.wrapper_nonce = this.wrapper_nonce;
    message.id = this.next_message_id++;
    this.target.postMessage(message, "*");
    if (cb) this.waiting_cb[message.id] = cb;
  };

  window.ZeroFrame = ZeroFrame;
  window.zeroframe = new ZeroFrame();
})();
