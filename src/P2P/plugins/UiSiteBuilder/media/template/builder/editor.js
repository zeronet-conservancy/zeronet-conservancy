/* Site Builder - editor. Owns site content via the ZeroFrame API.
 * Uses Editor.js for block editing; stores our own block model in data/pages/*.json.
 */
(function () {
  "use strict";

  var zf = window.zeroframe;
  var siteInfo = null;
  var settings = {};
  var pages = [];
  var templates = [];
  var currentPageId = null;
  var dirty = false;
  var suppressChange = false;
  var autosaveTimer = null;
  var editor = null;
  var undo = null;
  var historyData = { history: {} };

  function qs(sel) { return document.querySelector(sel); }

  function utf8ToBase64(str) {
    return btoa(unescape(encodeURIComponent(str)));
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function fmtBytes(bytes) {
    if (bytes < 1024) return bytes + "B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + "KB";
    return (bytes / 1024 / 1024).toFixed(1) + "MB";
  }

  function setStatus(text) { qs("#status").textContent = text; }

  function setDirty(v) {
    dirty = v;
    qs("#dirty").style.display = v ? "" : "none";
  }

  function notify(type, message, timeout) {
    zf.cmd("wrapperNotification", [type, message, timeout || 5000]);
  }

  // ---- Block converters (our model <-> Editor.js) ----

  function ourToEJ(blocks) {
    return (blocks || []).map(function (b) {
      switch (b.type) {
        case "heading": return { type: "header", data: { text: b.body || "", level: b.level || 2 } };
        case "text": return { type: "paragraph", data: { text: b.body || "" } };
        case "quote": return { type: "quote", data: { text: b.body || "" } };
        case "code": return { type: "code", data: { code: b.body || "" } };
        case "image": return { type: "image", data: { file: { url: b.src || "" }, caption: b.alt || "" } };
        case "divider": return { type: "delimiter", data: {} };
        case "list": return { type: "list", data: { style: b.ordered ? "ordered" : "unordered", items: b.items || [] } };
        case "markdown": return { type: "markdown", data: { text: b.body || "" } };
        case "columns": return { type: "columns", data: { columns: b.columns || ["", ""] } };
        case "card": return { type: "card", data: { title: b.title || "", url: b.url || "", description: b.description || "", image: b.image || "" } };
        case "accordion": return { type: "accordion", data: { items: b.items || [] } };
        case "gallery": return { type: "gallery", data: { images: b.images || [] } };
        case "section": return { type: "section", data: { columns: b.columns || [[], []] } };
        default: return null;
      }
    }).filter(Boolean);
  }

  function ejToOur(blocks) {
    return (blocks || []).map(function (b) {
      switch (b.type) {
        case "paragraph": return { type: "text", body: b.data.text || "" };
        case "header": return { type: "heading", level: b.data.level || 2, body: b.data.text || "" };
        case "quote": return { type: "quote", body: b.data.text || "" };
        case "code": return { type: "code", body: b.data.code || "" };
        case "image": return { type: "image", src: (b.data.file && b.data.file.url) || "", alt: b.data.caption || "" };
        case "delimiter": return { type: "divider" };
        case "list": return { type: "list", ordered: b.data.style === "ordered", items: b.data.items || [] };
        case "markdown": return { type: "markdown", body: b.data.text || "" };
        case "columns": return { type: "columns", columns: b.data.columns || [] };
        case "card": return { type: "card", title: b.data.title || "", url: b.data.url || "", description: b.data.description || "", image: b.data.image || "" };
        case "accordion": return { type: "accordion", items: b.data.items || [] };
        case "gallery": return { type: "gallery", images: b.data.images || [] };
        case "section": return { type: "section", columns: b.data.columns || [] };
        default: return null;
      }
    }).filter(Boolean);
  }

  // ---- Custom Editor.js tools ----

  function svg(path) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
  }

  var MarkdownTool = (function () {
    function MarkdownTool(_a) { this.data = (_a && _a.data) || {}; }
    MarkdownTool.prototype.render = function () {
      this.ta = document.createElement("textarea");
      this.ta.className = "cdx-markdown";
      this.ta.placeholder = "Write markdown here\u2026";
      this.ta.value = this.data.text || "";
      return this.ta;
    };
    MarkdownTool.prototype.save = function () { return { text: this.ta.value }; };
    MarkdownTool.toolbox = { icon: svg('<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h10"/>'), title: "Markdown" };
    return MarkdownTool;
  })();

  var ColumnsTool = (function () {
    function ColumnsTool(_a) { this.data = (_a && _a.data) || {}; }
    ColumnsTool.prototype.render = function () {
      var wrap = document.createElement("div");
      wrap.className = "cdx-columns";
      var cells = this.data.columns && this.data.columns.length ? this.data.columns : ["", ""];
      this.tas = cells.map(function (c) {
        var ta = document.createElement("textarea");
        ta.placeholder = "Column content (markdown)\u2026";
        ta.value = c || "";
        wrap.appendChild(ta);
        return ta;
      });
      return wrap;
    };
    ColumnsTool.prototype.save = function () { return { columns: this.tas.map(function (ta) { return ta.value; }) }; };
    ColumnsTool.toolbox = { icon: svg('<rect x="3" y="3" width="7" height="18" rx="1"/><rect x="14" y="3" width="7" height="18" rx="1"/>'), title: "Columns (text)" };
    return ColumnsTool;
  })();

  var CardTool = (function () {
    function CardTool(_a) { this.data = (_a && _a.data) || {}; }
    CardTool.prototype.render = function () {
      var wrap = document.createElement("div");
      wrap.className = "cdx-card";
      this.title = mkCardInput("Title", this.data.title);
      this.url = mkCardInput("URL", this.data.url);
      this.description = mkCardInput("Description", this.data.description);
      this.image = mkCardInput("Image path (optional)", this.data.image);
      [this.title, this.url, this.description, this.image].forEach(function (i) { wrap.appendChild(i); });
      return wrap;
    };
    CardTool.prototype.save = function () {
      return { title: this.title.value, url: this.url.value, description: this.description.value, image: this.image.value };
    };
    CardTool.toolbox = { icon: svg('<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'), title: "Card" };
    return CardTool;
  })();

  var AccordionTool = (function () {
    function AccordionTool(_a) { this.data = (_a && _a.data) || {}; }
    AccordionTool.prototype.render = function () {
      var self = this;
      this.wrap = document.createElement("div");
      this.wrap.className = "cdx-accordion";
      var items = (this.data.items && this.data.items.length) ? this.data.items : [{ q: "", a: "" }];
      items.forEach(function (item) { self._appendRow(item.q, item.a); });
      this.addBtn = document.createElement("button");
      this.addBtn.type = "button"; this.addBtn.className = "btn"; this.addBtn.textContent = "+ Question";
      this.addBtn.addEventListener("click", function () { self._appendRow("", ""); });
      this.wrap.appendChild(this.addBtn);
      return this.wrap;
    };
    AccordionTool.prototype._appendRow = function (q, a) {
      var row = document.createElement("div");
      row.className = "cdx-accordion-row";
      var qi = document.createElement("input"); qi.placeholder = "Question"; qi.value = q || "";
      var ta = document.createElement("textarea"); ta.placeholder = "Answer"; ta.rows = 2; ta.value = a || "";
      var del = document.createElement("button"); del.type = "button"; del.className = "btn btn-danger"; del.textContent = "\u00d7";
      del.addEventListener("click", function () { row.remove(); });
      row.appendChild(qi); row.appendChild(ta); row.appendChild(del);
      this.wrap.insertBefore(row, this.addBtn);
    };
    AccordionTool.prototype.save = function () {
      var items = [];
      var rows = this.wrap.querySelectorAll(".cdx-accordion-row");
      for (var i = 0; i < rows.length; i++) {
        items.push({ q: rows[i].querySelector("input").value, a: rows[i].querySelector("textarea").value });
      }
      return { items: items };
    };
    AccordionTool.toolbox = { icon: svg('<path d="M3 6h18"/><path d="M3 12h18"/><path d="M3 18h18"/><path d="M12 3v18"/>'), title: "FAQ / Accordion" };
    return AccordionTool;
  })();

  var GalleryTool = (function () {
    function GalleryTool(_a) { this.data = (_a && _a.data) || {}; }
    GalleryTool.prototype.render = function () {
      var self = this;
      this.wrap = document.createElement("div");
      this.wrap.className = "cdx-gallery";
      this.rowsEl = document.createElement("div");
      this.wrap.appendChild(this.rowsEl);
      (this.data.images || []).forEach(function (path) { self._appendImage(path); });
      var add = document.createElement("button");
      add.type = "button"; add.className = "btn"; add.textContent = "+ Image";
      add.addEventListener("click", function () { self._appendImage(""); });
      var browse = document.createElement("button");
      browse.type = "button"; browse.className = "btn"; browse.textContent = "Pick from media";
      browse.addEventListener("click", function () { self._pickMedia(); });
      this.wrap.appendChild(add); this.wrap.appendChild(browse);
      return this.wrap;
    };
    GalleryTool.prototype._appendImage = function (path) {
      var row = document.createElement("div");
      row.className = "cdx-gallery-row";
      var input = document.createElement("input");
      input.placeholder = "data/media/image.jpg";
      input.value = path || "";
      var del = document.createElement("button"); del.type = "button"; del.className = "btn btn-danger"; del.textContent = "\u00d7";
      del.addEventListener("click", function () { row.remove(); });
      row.appendChild(input); row.appendChild(del);
      this.rowsEl.appendChild(row);
    };
    GalleryTool.prototype._pickMedia = function () {
      var self = this;
      pickMedia(function (path) { self._appendImage(path); });
    };
    GalleryTool.prototype.save = function () {
      var images = [];
      var inputs = this.rowsEl.querySelectorAll("input");
      for (var i = 0; i < inputs.length; i++) {
        var v = inputs[i].value.trim();
        if (v) images.push(v);
      }
      return { images: images };
    };
    GalleryTool.toolbox = { icon: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>'), title: "Gallery" };
    return GalleryTool;
  })();

  // Section: SharePoint-style container with 1-3 columns, each holding nested blocks
  var SectionTool = (function () {
    function SectionTool(_a) { this.data = (_a && _a.data) || {}; this.nested = []; }
    SectionTool.prototype.render = function () {
      var self = this;
      var wrap = document.createElement("div");
      wrap.className = "cdx-section";
      var toolbar = document.createElement("div");
      toolbar.className = "cdx-section-toolbar";
      var add = document.createElement("button");
      add.type = "button"; add.className = "btn"; add.textContent = "+ Column";
      add.addEventListener("click", function () { self._changeCols(1); });
      var del = document.createElement("button");
      del.type = "button"; del.className = "btn"; del.textContent = "\u2212 Column";
      del.addEventListener("click", function () { self._changeCols(-1); });
      toolbar.appendChild(add); toolbar.appendChild(del);
      wrap.appendChild(toolbar);
      this.colsEl = document.createElement("div");
      this.colsEl.className = "cdx-section-columns";
      wrap.appendChild(this.colsEl);
      var cols = (this.data.columns && this.data.columns.length) ? this.data.columns : [[], []];
      this._renderColumns(cols);
      return wrap;
    };
    SectionTool.prototype._nestedTools = function () {
      return {
        header: { class: window.Header, config: { levels: [1, 2, 3, 4, 5, 6], defaultLevel: 2 } },
        list: window.List,
        quote: window.Quote,
        code: window.CodeTool,
        image: { class: window.ImageTool, config: { caption: true, uploader: { uploadByFile: uploadByFile, uploadByUrl: uploadByUrl } } },
        delimiter: window.Delimiter,
        markdown: MarkdownTool,
        card: CardTool
      };
    };
    SectionTool.prototype._renderColumns = function (cols) {
      var self = this;
      this._destroyNested();
      this.colsEl.innerHTML = "";
      cols.forEach(function (colBlocks) {
        var colEl = document.createElement("div");
        colEl.className = "cdx-section-column";
        var holder = document.createElement("div");
        holder.className = "cdx-section-editor";
        colEl.appendChild(holder);
        self.colsEl.appendChild(colEl);
        var nested = new window.EditorJS({
          holder: holder,
          tools: self._nestedTools(),
          data: { blocks: ourToEJ(colBlocks) },
          minHeight: 40,
          onChange: function () { if (!suppressChange) onEditorChange(); }
        });
        self.nested.push(nested);
      });
    };
    SectionTool.prototype._destroyNested = function () {
      this.nested.forEach(function (e) { try { e.destroy(); } catch (err) {} });
      this.nested = [];
    };
    SectionTool.prototype._changeCols = function (delta) {
      var self = this;
      this.save().then(function (data) {
        var cols = data.columns || [[], []];
        if (delta > 0 && cols.length < 3) cols.push([]);
        else if (delta < 0 && cols.length > 1) cols.pop();
        else return;
        self.data.columns = cols;
        self._renderColumns(cols);
        onEditorChange();
      });
    };
    SectionTool.prototype.save = function () {
      var self = this;
      return Promise.all(this.nested.map(function (e) { return e.isReady; })).then(function () {
        return Promise.all(self.nested.map(function (e) { return e.save(); }));
      }).then(function (outputs) {
        return { columns: outputs.map(function (o) { return ejToOur(o.blocks); }) };
      });
    };
    SectionTool.toolbox = { icon: svg('<rect x="3" y="4" width="18" height="5" rx="1"/><rect x="3" y="15" width="18" height="5" rx="1"/><path d="M3 12h18"/>'), title: "Section (columns)" };
    return SectionTool;
  })();

  function mkCardInput(placeholder, value) {
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder = placeholder;
    input.value = value || "";
    return input;
  }

  // ---- Modal helpers ----

  function openModal(title, items) {
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    var box = document.createElement("div");
    box.className = "modal";
    var h = document.createElement("h2"); h.textContent = title; box.appendChild(h);
    var list = document.createElement("div");
    items.forEach(function (it) {
      var b = document.createElement("button");
      b.className = "page-item";
      b.innerHTML = "<strong>" + escapeHtml(it.label) + "</strong><br><small>" + escapeHtml(it.desc || "") + "</small>";
      b.addEventListener("click", function () { overlay.remove(); it.action(); });
      list.appendChild(b);
    });
    box.appendChild(list);
    var cancel = document.createElement("button");
    cancel.className = "btn"; cancel.textContent = "Cancel";
    cancel.addEventListener("click", function () { overlay.remove(); });
    box.appendChild(cancel);
    overlay.appendChild(box);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
  }

  function pickMedia(onPick) {
    zf.cmdp("fileList", { inner_path: "data/media" }).then(function (files) {
      var overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      var box = document.createElement("div");
      box.className = "modal";
      var h = document.createElement("h2"); h.textContent = "Pick an image"; box.appendChild(h);
      var grid = document.createElement("div");
      grid.className = "media-list";
      (files || []).forEach(function (f) {
        var img = document.createElement("img");
        img.className = "media-item";
        img.src = "data/media/" + f;
        img.title = f;
        img.addEventListener("click", function () { overlay.remove(); onPick("data/media/" + f); });
        grid.appendChild(img);
      });
      box.appendChild(grid);
      var cancel = document.createElement("button");
      cancel.className = "btn"; cancel.textContent = "Cancel";
      cancel.addEventListener("click", function () { overlay.remove(); });
      box.appendChild(cancel);
      overlay.appendChild(box);
      overlay.addEventListener("click", function (e) { if (e.target === overlay) overlay.remove(); });
      document.body.appendChild(overlay);
    }).catch(function () {});
  }

  // ---- Image uploader ----

  function readFileAsBase64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result.split(",")[1]); };
      reader.onerror = function () { reject(new Error("Read error")); };
      reader.readAsDataURL(file);
    });
  }

  function sanitizeFilename(name) {
    return (name || "image").replace(/[^a-zA-Z0-9._-]/g, "-").slice(-64);
  }

  function remainingBytes() {
    var sizeLimitMB = (siteInfo && siteInfo.size_limit) || 10;
    var currentSize = (siteInfo && siteInfo.settings && siteInfo.settings.size) || 0;
    return sizeLimitMB * 1024 * 1024 - currentSize;
  }

  function uploadByFile(file) {
    var remaining = remainingBytes();
    if (file.size > remaining) {
      notify("error", "Image is " + fmtBytes(file.size) + " but only " + fmtBytes(remaining) +
        " remain under the site size limit. Increase the limit from the 0net sidebar (top-right \u201c0\u201d button).");
      return Promise.reject(new Error("File too large"));
    }
    return readFileAsBase64(file).then(function (b64) {
      var name = "data/media/" + Date.now() + "-" + sanitizeFilename(file.name);
      return zf.cmdp("fileWrite", { inner_path: name, content_base64: b64 }).then(function () {
        refreshMedia();
        return { success: 1, file: { url: name } };
      });
    });
  }

  function uploadByUrl(url) {
    return Promise.resolve({ success: 1, file: { url: url } });
  }

  // ---- Editor.js setup ----

  function makeTools() {
    return {
      header: { class: window.Header, config: { levels: [1, 2, 3, 4, 5, 6], defaultLevel: 2 } },
      list: window.List,
      quote: window.Quote,
      code: window.CodeTool,
      image: { class: window.ImageTool, config: { caption: true, uploader: { uploadByFile: uploadByFile, uploadByUrl: uploadByUrl } } },
      delimiter: window.Delimiter,
      markdown: MarkdownTool,
      columns: ColumnsTool,
      card: CardTool,
      accordion: AccordionTool,
      gallery: GalleryTool,
      section: SectionTool
    };
  }

  function initEditor() {
    if (editor) return Promise.resolve();
    editor = new window.EditorJS({
      holder: "editorjs",
      tools: makeTools(),
      data: { blocks: [] },
      onChange: function () { if (!suppressChange) onEditorChange(); },
      onReady: function () { setStatus("Ready"); }
    });
    return editor.isReady.then(function () {
      if (window.Undo && !undo) {
        undo = new window.Undo({ editor: editor });
      }
    });
  }

  function onEditorChange() {
    setDirty(true);
    if (autosaveTimer) clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(function () { savePage(); }, 1500);
  }

  function renderEditorBlocks(blocks) {
    suppressChange = true;
    return editor.render({ blocks: blocks }).then(function () {
      suppressChange = false;
      if (undo) undo.clear();
    });
  }

  // ---- Page loading ----

  function loadSettings() {
    return zf.cmdp("fileGet", { inner_path: "data/settings.json", required: false }).then(function (raw) {
      try { settings = raw ? JSON.parse(raw) : {}; } catch (e) { settings = {}; }
      if (!settings.next_page_id) settings.next_page_id = 1;
    });
  }

  function loadPages() {
    return zf.cmdp("dbQuery", { query: "SELECT page_id, slug, title, modified FROM page ORDER BY page_id" }).then(function (rows) {
      pages = rows || [];
    });
  }

  function loadTemplates() {
    return zf.cmdp("fileGet", { inner_path: "templates/templates.json", required: false }).then(function (raw) {
      try { templates = raw ? JSON.parse(raw) : []; } catch (e) { templates = []; }
    }).catch(function () { templates = []; });
  }

  function loadPageFile(pageId) {
    return zf.cmdp("fileGet", { inner_path: "data/pages/" + pageId + ".json", required: false }).then(function (raw) {
      var obj = null;
      if (raw) {
        var data = JSON.parse(raw);
        var list = data.page || [];
        obj = list[0] || null;
      }
      if (!obj) obj = { page_id: pageId, slug: "page-" + pageId, title: "Untitled", modified: 0, blocks: [] };
      obj.page_id = pageId;
      return obj;
    });
  }

  // ---- Rendering ----

  function renderSidebar() {
    qs("#site-title").value = settings.title || "";
    qs("#site-description").value = settings.description || "";
    qs("#site-theme").value = settings.theme || "default";
    document.body.dataset.theme = settings.theme || "default";
    renderPageList();
  }

  function renderPageList() {
    var list = qs("#page-list");
    list.innerHTML = "";
    pages.forEach(function (p) {
      var btn = document.createElement("button");
      btn.className = "page-item" + (p.page_id === currentPageId ? " active" : "");
      btn.textContent = p.title || p.slug;
      btn.addEventListener("click", function () { selectPage(p.page_id); });
      list.appendChild(btn);
    });
  }

  function selectPage(pageId) {
    if (autosaveTimer) { clearTimeout(autosaveTimer); autosaveTimer = null; }
    var flush = dirty ? savePage() : Promise.resolve();
    flush.then(function () {
      return loadPageFile(pageId);
    }).then(function (page) {
      currentPageId = pageId;
      qs("#page-title").value = page.title || "";
      qs("#page-slug").value = page.slug || "";
      renderPageList();
      renderHistory();
      return renderEditorBlocks(ourToEJ(page.blocks));
    }).then(function () {
      setDirty(false);
      setStatus("Editing page");
    });
  }

  // ---- Revision history (localStorage via the wrapper) ----

  function loadLS() {
    return zf.cmdp("wrapperGetLocalStorage").then(function (d) {
      return (d && typeof d === "object") ? d : {};
    }).catch(function () { return {}; });
  }

  function saveLS(obj) {
    return zf.cmdp("wrapperSetLocalStorage", obj);
  }

  function loadHistory() {
    return loadLS().then(function (ls) {
      historyData = (ls.history && typeof ls.history === "object") ? { history: ls.history } : { history: {} };
    });
  }

  function saveHistory() {
    return loadLS().then(function (ls) {
      ls.history = historyData.history;
      return saveLS(ls);
    });
  }

  function snapshotHistory() {
    if (currentPageId == null) return Promise.resolve();
    return editor.save().then(function (out) {
      var page = {
        page_id: currentPageId,
        title: qs("#page-title").value,
        slug: qs("#page-slug").value,
        blocks: ejToOur(out.blocks)
      };
      var list = historyData.history[page.page_id] || [];
      var prev = list[list.length - 1];
      if (prev && prev.title === page.title && prev.slug === page.slug &&
          JSON.stringify(prev.blocks) === JSON.stringify(page.blocks)) {
        return;
      }
      list.push({ ts: Date.now(), title: page.title, slug: page.slug, blocks: page.blocks });
      if (list.length > 25) list = list.slice(-25);
      historyData.history[page.page_id] = list;
      return saveHistory();
    });
  }

  function renderHistory() {
    var list = qs("#history-list");
    list.innerHTML = "";
    var snapshots = (historyData.history[currentPageId] || []).slice().reverse();
    if (!snapshots.length) {
      var empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No snapshots yet";
      list.appendChild(empty);
      return;
    }
    snapshots.forEach(function (s) {
      var btn = document.createElement("button");
      btn.className = "page-item";
      btn.textContent = (s.title || "Untitled") + " \u00b7 " + new Date(s.ts).toLocaleString();
      btn.addEventListener("click", function () { restoreSnapshot(s); });
      list.appendChild(btn);
    });
  }

  function restoreSnapshot(s) {
    zf.cmd("wrapperConfirm", ["Restore this version?", "Restore"], function (res) {
      if (!res) return;
      qs("#page-title").value = s.title || "";
      qs("#page-slug").value = s.slug || "";
      renderEditorBlocks(ourToEJ(s.blocks)).then(function () {
        setDirty(true);
        setStatus("Restored snapshot - save or publish to keep it");
      });
    });
  }

  function preview() {
    var slug = qs("#page-slug").value || "home";
    var url = window.location.origin + "/" + siteInfo.address + "/index.html?page=" + encodeURIComponent(slug);
    zf.cmd("wrapperOpenWindow", [url, "_blank", ""]);
  }

  // ---- Persistence ----

  function collectPage() {
    return editor.save().then(function (out) {
      return {
        page_id: currentPageId,
        slug: qs("#page-slug").value,
        title: qs("#page-title").value,
        modified: Math.floor(Date.now() / 1000),
        blocks: ejToOur(out.blocks)
      };
    });
  }

  function savePage() {
    if (currentPageId == null) return Promise.resolve();
    return collectPage().then(function (page) {
      var payload = { page: [page] };
      return zf.cmdp("fileWrite", {
        inner_path: "data/pages/" + page.page_id + ".json",
        content_base64: utf8ToBase64(JSON.stringify(payload, null, 1))
      }).then(function () {
        setDirty(false);
        return page;
      });
    });
  }

  function saveSettings() {
    settings.title = qs("#site-title").value;
    settings.description = qs("#site-description").value;
    settings.theme = qs("#site-theme").value;
    document.body.dataset.theme = settings.theme || "default";
    return zf.cmdp("fileWrite", { inner_path: "data/settings.json", content_base64: utf8ToBase64(JSON.stringify(settings, null, 1)) });
  }

  function save() {
    Promise.resolve()
      .then(function () { return snapshotHistory(); })
      .then(function () { return savePage(); })
      .then(function () { return saveSettings(); })
      .then(function () { renderHistory(); setStatus("Saved (not yet published)"); })
      .catch(function (err) { notify("error", "Save failed: " + err.message); });
  }

  // ---- Page templates ----

  function uniqueSlug(base) {
    var slug = base || "page";
    var taken = pages.some(function (p) { return p.slug === slug; });
    var i = 2;
    while (taken) {
      slug = base + "-" + i;
      taken = pages.some(function (p) { return p.slug === slug; });
      i += 1;
    }
    return slug;
  }

  function createPage(title, slug, blocks) {
    var id = settings.next_page_id || 1;
    var page = { page_id: id, slug: uniqueSlug(slug), title: title || "New page", modified: Math.floor(Date.now() / 1000), blocks: blocks || [] };
    var payload = { page: [page] };
    settings.next_page_id = id + 1;
    return zf.cmdp("fileWrite", { inner_path: "data/pages/" + id + ".json", content_base64: utf8ToBase64(JSON.stringify(payload, null, 1)) })
      .then(function () { return saveSettings(); })
      .then(function () {
        pages.push({ page_id: id, slug: page.slug, title: page.title, modified: page.modified });
        currentPageId = id;
        renderSidebar();
        renderHistory();
        qs("#page-title").value = page.title;
        qs("#page-slug").value = page.slug;
        return renderEditorBlocks(ourToEJ(page.blocks));
      })
      .then(function () { setDirty(true); setStatus("Created page - sign & publish to make it live"); });
  }

  function newPage() {
    var items = templates.map(function (t) {
      return {
        label: t.title || t.id,
        desc: t.description || "",
        action: function () { createPageFromTemplate(t.id); }
      };
    });
    if (!items.length) {
      items = [{ label: "Blank", desc: "Start from scratch", action: function () { createPage("New page", "page", []); } }];
    }
    openModal("New page", items);
  }

  function createPageFromTemplate(templateId) {
    if (templateId === "empty" || !templateId) {
      createPage("New page", "page", []).catch(function (err) { notify("error", "New page failed: " + err.message); });
      return;
    }
    zf.cmdp("fileGet", { inner_path: "templates/" + templateId + ".json", required: false }).then(function (raw) {
      var t = JSON.parse(raw);
      createPage(t.title || "New page", t.slug || "page", t.blocks || []).catch(function (err) { notify("error", "New page failed: " + err.message); });
    }).catch(function () {
      createPage("New page", "page", []).catch(function (err) { notify("error", "New page failed: " + err.message); });
    });
  }

  // ---- New site (starter) ----

  function newSite() {
    var url = window.location.origin + "/SiteBuilder/new";
    zf.cmd("wrapperOpenWindow", [url, "_blank", ""]);
  }

  // ---- Page delete ----

  function deletePage() {
    if (currentPageId == null) return;
    zf.cmd("wrapperConfirm", ["Delete this page?", "Delete"], function (res) {
      if (!res) return;
      zf.cmdp("fileDelete", { inner_path: "data/pages/" + currentPageId + ".json" }).then(function () {
        pages = pages.filter(function (p) { return p.page_id !== currentPageId; });
        currentPageId = null;
        renderSidebar();
        renderHistory();
        qs("#page-title").value = "";
        qs("#page-slug").value = "";
        setDirty(true);
        setStatus("Page deleted - sign & publish to update");
      }).catch(function (err) { notify("error", "Delete failed: " + err.message); });
    });
  }

  // ---- Sign & publish ----

  function publish() {
    var doSign = function (key) {
      setStatus("Signing & publishing\u2026");
      return snapshotHistory()
        .then(function () { return savePage(); })
        .then(function () { return saveSettings(); })
        .then(function () { return zf.cmdp("siteSign", { privatekey: key, inner_path: "content.json", update_changed_files: true }); })
        .then(function () { return zf.cmdp("sitePublish", { inner_path: "content.json", sign: false }); })
        .then(function () {
          setStatus("Published");
          notify("done", "Content published", 5000);
          setDirty(false);
          renderHistory();
        })
        .catch(function (err) {
          setStatus("Publish failed");
          notify("error", "Publish failed: " + err.message);
        });
    };

    if (siteInfo && siteInfo.privatekey) {
      doSign("stored");
    } else {
      zf.cmd("wrapperPrompt", ["Private key (input hidden):", "password", "OK", ""], function (key) {
        if (key) doSign(key);
      });
    }
  }

  // ---- Media manager ----

  function refreshMedia() {
    zf.cmdp("fileList", { inner_path: "data/media" }).then(function (files) {
      var list = qs("#media-list");
      list.innerHTML = "";
      (files || []).forEach(function (f) {
        var img = document.createElement("img");
        img.className = "media-item";
        img.src = "data/media/" + f;
        img.title = f;
        img.addEventListener("click", function () { insertImageBlock("data/media/" + f); });
        list.appendChild(img);
      });
    }).catch(function () {});
  }

  function insertImageBlock(url) {
    if (!editor) return;
    editor.blocks.insert("image", { file: { url: url }, caption: "" });
    setDirty(true);
  }

  function handleUpload(e) {
    var files = Array.prototype.slice.call(e.target.files || []);
    e.target.value = "";
    files.forEach(function (file) {
      uploadByFile(file).then(function () {
        notify("done", "Uploaded: " + file.name, 4000);
      }).catch(function (err) { /* already notified */ });
    });
  }

  // ---- Wiring ----

  function init() {
    zf.cmdp("siteInfo").then(function (info) {
      siteInfo = info;
      if (!siteInfo.settings.own) {
        qs("#own-warning").style.display = "";
        qs("#own-warning").textContent = "You do not own this site - editing is disabled.";
        return;
      }
      return loadSettings().then(loadPages).then(loadTemplates).then(function () {
        renderSidebar();
        return initEditor();
      }).then(function () {
        return loadHistory();
      }).then(function () {
        var home = null;
        for (var i = 0; i < pages.length; i++) {
          if (pages[i].slug === "home") { home = pages[i]; break; }
        }
        if (!home && pages.length) home = pages[0];
        if (home) selectPage(home.page_id);
        else setStatus("No pages yet - create one");
        refreshMedia();
      });
    }).catch(function (err) {
      setStatus("Error: " + err.message);
    });

    qs("#btn-publish").addEventListener("click", publish);
    qs("#btn-save").addEventListener("click", save);
    qs("#btn-save-settings").addEventListener("click", save);
    qs("#btn-new-page").addEventListener("click", newPage);
    qs("#btn-new-site").addEventListener("click", newSite);
    qs("#btn-delete-page").addEventListener("click", deletePage);
    qs("#btn-undo").addEventListener("click", function () { if (undo) undo.undo(); });
    qs("#btn-redo").addEventListener("click", function () { if (undo) undo.redo(); });
    qs("#btn-preview").addEventListener("click", preview);
    qs("#media-upload").addEventListener("change", handleUpload);
    qs("#page-title").addEventListener("input", onEditorChange);
    qs("#page-slug").addEventListener("input", onEditorChange);
    qs("#site-title").addEventListener("input", function () { setDirty(true); });
    qs("#site-description").addEventListener("input", function () { setDirty(true); });
    qs("#site-theme").addEventListener("change", function () {
      document.body.dataset.theme = qs("#site-theme").value;
      setDirty(true);
    });

    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
    });

    window.addEventListener("beforeunload", function (e) {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
