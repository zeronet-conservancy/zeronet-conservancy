/* Site Builder - runtime renderer (visitor-facing).
 * Reads settings + pages from data/, renders the current page as blocks.
 */
(function () {
  "use strict";

  var zf = window.zeroframe;
  var siteInfo = null;
  var settings = {};
  var pages = [];
  var currentPage = null;
  var visitorTheme = null;

  function qs(sel) { return document.querySelector(sel); }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function getCurrentSlug() {
    return new URLSearchParams(window.location.search).get("page") || "home";
  }

  function highlightCode(code, lang) {
    var html;
    try {
      var result = lang && window.hljs.getLanguage(lang)
        ? window.hljs.highlight(code || "", { language: lang })
        : window.hljs.highlightAuto(code || "");
      html = result.value;
    } catch (e) {
      html = escapeHtml(code || "");
    }
    return html;
  }

  function configureMarkdown() {
    if (!window.marked || configureMarkdown.done) return;
    configureMarkdown.done = true;
    window.marked.setOptions({ breaks: true });
    var renderer = new window.marked.Renderer();
    renderer.code = function (code, infostring) {
      var lang = (infostring || "").trim().split(/\s+/)[0];
      return '<pre class="block-code"><code class="hljs">' + highlightCode(code, lang) + '</code></pre>';
    };
    window.marked.setOptions({ renderer: renderer });
  }

  function markdownToHtml(md) {
    configureMarkdown();
    if (window.marked) return window.marked.parse(md || "");
    return escapeHtml(md || "").replace(/\n+/g, "<br>");
  }

  function openLightbox(images, index) {
    var current = index;
    var overlay = document.createElement("div");
    overlay.className = "lightbox";
    var img = document.createElement("img");
    var show = function () { img.src = images[current]; };
    show();
    overlay.appendChild(img);

    var close = document.createElement("button");
    close.className = "lightbox-close"; close.textContent = "\u00d7";
    close.addEventListener("click", function (e) { e.stopPropagation(); overlay.remove(); });
    overlay.appendChild(close);

    if (images.length > 1) {
      var prev = document.createElement("button");
      prev.className = "lightbox-nav prev"; prev.textContent = "\u2039";
      prev.addEventListener("click", function (e) { e.stopPropagation(); current = (current - 1 + images.length) % images.length; show(); });
      var next = document.createElement("button");
      next.className = "lightbox-nav next"; next.textContent = "\u203a";
      next.addEventListener("click", function (e) { e.stopPropagation(); current = (current + 1) % images.length; show(); });
      overlay.appendChild(prev); overlay.appendChild(next);
    }
    overlay.addEventListener("click", function () { overlay.remove(); });
    document.body.appendChild(overlay);
  }

  function renderBlock(block) {
    var el;
    switch (block.type) {
      case "heading": {
        var level = Math.min(6, Math.max(1, parseInt(block.level, 10) || 2));
        el = document.createElement("h" + level);
        el.className = "block-heading";
        el.textContent = block.body || "";
        return el;
      }
      case "text": {
        var wrap = document.createElement("div");
        wrap.className = "block-text";
        (block.body || "").split(/\n+/).forEach(function (paragraph) {
          if (!paragraph.trim()) return;
          var p = document.createElement("p");
          p.textContent = paragraph;
          wrap.appendChild(p);
        });
        return wrap;
      }
      case "markdown": {
        el = document.createElement("div");
        el.className = "block-markdown";
        el.innerHTML = markdownToHtml(block.body);
        return el;
      }
      case "quote": {
        el = document.createElement("blockquote");
        el.className = "block-quote";
        el.textContent = block.body || "";
        return el;
      }
      case "code": {
        var pre = document.createElement("pre");
        pre.className = "block-code";
        var code = document.createElement("code");
        code.className = "hljs";
        code.innerHTML = highlightCode(block.body);
        pre.appendChild(code);
        return pre;
      }
      case "list": {
        el = document.createElement(block.ordered ? "ol" : "ul");
        el.className = "block-list";
        (block.items || []).forEach(function (item) {
          var li = document.createElement("li");
          li.textContent = item;
          el.appendChild(li);
        });
        return el;
      }
      case "image": {
        el = document.createElement("img");
        el.className = "block-image";
        el.src = block.src || "";
        el.alt = block.alt || "";
        el.addEventListener("click", function () { if (block.src) openLightbox([block.src], 0); });
        return el;
      }
      case "columns": {
        var cols = document.createElement("div");
        cols.className = "block-columns";
        (block.columns || []).forEach(function (cell) {
          var cellEl = document.createElement("div");
          cellEl.className = "block-column";
          cellEl.innerHTML = markdownToHtml(cell);
          cols.appendChild(cellEl);
        });
        return cols;
      }
      case "card": {
        el = document.createElement("a");
        el.className = "block-card";
        el.href = block.url || "#";
        el.target = "_top";
        if (block.image) {
          var img = document.createElement("img");
          img.src = block.image;
          img.alt = block.title || "";
          el.appendChild(img);
        }
        var body = document.createElement("div");
        body.className = "block-card-body";
        var title = document.createElement("strong");
        title.textContent = block.title || block.url || "";
        body.appendChild(title);
        if (block.description) {
          var desc = document.createElement("span");
          desc.textContent = block.description;
          body.appendChild(desc);
        }
        el.appendChild(body);
        return el;
      }
      case "accordion": {
        var accordion = document.createElement("div");
        accordion.className = "block-accordion";
        (block.items || []).forEach(function (item) {
          var details = document.createElement("details");
          var summary = document.createElement("summary");
          summary.textContent = item.q || "";
          details.appendChild(summary);
          var answer = document.createElement("div");
          answer.className = "block-accordion-answer";
          answer.innerHTML = markdownToHtml(item.a || "");
          details.appendChild(answer);
          accordion.appendChild(details);
        });
        return accordion;
      }
      case "gallery": {
        var grid = document.createElement("div");
        grid.className = "block-gallery";
        var images = block.images || [];
        if (!images.length) {
          var hint = document.createElement("p");
          hint.className = "empty";
          hint.textContent = "No images yet";
          grid.appendChild(hint);
          return grid;
        }
        images.forEach(function (src, i) {
          var gimg = document.createElement("img");
          gimg.src = src;
          gimg.addEventListener("click", function () { openLightbox(images, i); });
          grid.appendChild(gimg);
        });
        return grid;
      }
      case "section": {
        var section = document.createElement("div");
        section.className = "block-section";
        (block.columns || []).forEach(function (colBlocks) {
          var col = document.createElement("div");
          col.className = "block-section-column";
          (colBlocks || []).forEach(function (child) {
            var rendered = renderBlock(child);
            if (rendered) col.appendChild(rendered);
          });
          section.appendChild(col);
        });
        return section;
      }
      case "divider": {
        return document.createElement("hr");
      }
      default:
        return null;
    }
  }

  // ---- Theme ----

  function currentTheme() {
    return visitorTheme || settings.theme || "default";
  }

  function applyTheme() {
    document.body.dataset.theme = currentTheme();
  }

  function loadVisitorTheme() {
    return zf.cmdp("wrapperGetLocalStorage").then(function (ls) {
      visitorTheme = (ls && ls.theme) ? ls.theme : null;
    }).catch(function () {});
  }

  function setVisitorTheme(t) {
    visitorTheme = t;
    document.body.dataset.theme = t;
    return zf.cmdp("wrapperGetLocalStorage").then(function (ls) {
      ls = (ls && typeof ls === "object") ? ls : {};
      ls.theme = t;
      return zf.cmdp("wrapperSetLocalStorage", ls);
    }).catch(function () {});
  }

  function toggleTheme(btn) {
    setVisitorTheme(currentTheme() === "dark" ? "default" : "dark").then(function () {
      if (btn) btn.textContent = currentTheme() === "dark" ? "Light" : "Dark";
    });
  }

  function renderNav() {
    var header = qs("#site-header");
    header.innerHTML = "";

    var brand = document.createElement("a");
    brand.className = "brand";
    brand.href = "?page=home";
    brand.textContent = settings.title || "Untitled site";
    brand.addEventListener("click", navigate);
    header.appendChild(brand);

    var nav = document.createElement("nav");
    pages.forEach(function (p) {
      var a = document.createElement("a");
      a.href = "?page=" + encodeURIComponent(p.slug);
      a.textContent = p.title || p.slug;
      if (p.slug === getCurrentSlug()) a.className = "active";
      a.addEventListener("click", navigate);
      nav.appendChild(a);
    });
    header.appendChild(nav);

    var spacer = document.createElement("span");
    spacer.className = "header-spacer";
    header.appendChild(spacer);

    var toggle = document.createElement("button");
    toggle.className = "theme-toggle";
    toggle.textContent = currentTheme() === "dark" ? "Light" : "Dark";
    toggle.addEventListener("click", function () { toggleTheme(toggle); });
    header.appendChild(toggle);

    if (siteInfo && siteInfo.settings && siteInfo.settings.own) {
      var edit = document.createElement("a");
      edit.className = "edit-link";
      edit.href = "builder/editor.html";
      edit.textContent = "Edit site";
      header.appendChild(edit);
    }
  }

  function navigate(e) {
    e.preventDefault();
    history.pushState(null, "", e.currentTarget.getAttribute("href"));
    load();
  }

  function renderPage() {
    var main = qs("#page");
    main.innerHTML = "";
    if (!currentPage) {
      main.innerHTML = "<p class='empty'>No page found. " +
        (siteInfo && siteInfo.settings && siteInfo.settings.own
          ? "<a href='builder/editor.html'>Open the editor</a> to create one."
          : "") + "</p>";
      return;
    }

    var siteTitle = settings.title ? settings.title : "";
    document.title = (currentPage.title || currentPage.slug || "") + (siteTitle ? " - " + siteTitle : "");
    zf.cmd("wrapperSetTitle", document.title);

    var h = document.createElement("h1");
    h.className = "page-title";
    h.textContent = currentPage.title || currentPage.slug || "";
    main.appendChild(h);

    (currentPage.blocks || []).forEach(function (block) {
      var rendered = renderBlock(block);
      if (rendered) main.appendChild(rendered);
    });

    var footer = qs("#site-footer");
    footer.innerHTML = "";
    if (settings.description) {
      var d = document.createElement("p");
      d.textContent = settings.description;
      footer.appendChild(d);
    }
  }

  function loadPageContent(page) {
    return zf.cmdp("fileGet", { inner_path: "data/pages/" + page.page_id + ".json" }).then(function (raw) {
      var data = JSON.parse(raw);
      var list = data.page || [];
      var obj = list[0] || {};
      obj.page_id = page.page_id;
      return obj;
    });
  }

  function load() {
    var slug = getCurrentSlug();
    zf.cmdp("siteInfo").then(function (info) {
      siteInfo = info;
      return zf.cmdp("fileGet", { inner_path: "data/settings.json", required: false });
    }).then(function (raw) {
      try { settings = raw ? JSON.parse(raw) : {}; } catch (e) { settings = {}; }
      return loadVisitorTheme();
    }).then(function () {
      applyTheme();
      return zf.cmdp("dbQuery", { query: "SELECT page_id, slug, title, modified FROM page ORDER BY page_id" });
    }).then(function (rows) {
      pages = rows || [];
      var page = null;
      for (var i = 0; i < pages.length; i++) {
        if (pages[i].slug === slug) { page = pages[i]; break; }
      }
      if (!page && pages.length) page = pages[0];
      if (!page) {
        currentPage = null;
        renderNav();
        renderPage();
        return;
      }
      return loadPageContent(page).then(function (content) {
        currentPage = content;
        renderNav();
        renderPage();
      });
    }).catch(function (err) {
      qs("#page").innerHTML = "<p class='empty'>Error loading site: " +
        escapeHtml(err && err.message ? err.message : err) + "</p>";
    });
  }

  window.addEventListener("popstate", load);
  document.addEventListener("DOMContentLoaded", load);
})();
