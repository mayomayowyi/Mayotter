

from __future__ import annotations

from PySide6.QtWebEngineCore import QWebEngineScript

FILTER_SCRIPT_NAME = "MayotterContentFilter"

_FILTER_JS = """\
(function () {
  "use strict";
  if (window.__mayotterContentFilter) { return; }
  window.__mayotterContentFilter = true;

  var KEYWORDS = ["promoted", "\\u5e83\\u544a", "\\u30d7\\u30ed\\u30e2\\u30fc\\u30b7\\u30e7\\u30f3"];
  var STYLE_ID = "mayotter-content-filter-style";
  var SCANNED_ATTR = "data-mayotter-scanned";
  var HIDDEN_ATTR = "data-mayotter-filtered";
  var HIDDEN_VALUE = "hidden";

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) { return; }
    var css = document.createElement("style");
    css.id = STYLE_ID;
    css.textContent =
      '[' + HIDDEN_ATTR + '="' + HIDDEN_VALUE + '"] { display: none !important; }';
    (document.head || document.documentElement).appendChild(css);
  }

  function norm(value) {
    return (value || "").replace(/\\s+/g, " ").trim();
  }

  function isPromotionLabel(text) {
    var t = norm(text);
    if (!t || t.length > 40) { return false; }
    var lower = t.toLowerCase();
    for (var i = 0; i < KEYWORDS.length; i++) {
      var kw = KEYWORDS[i];
      if (lower === kw) { return true; }
      if (kw === "promoted" && lower.indexOf(kw) === 0) { return true; }
    }
    return false;
  }

  function looksPromoted(article) {
    var labeled = article.querySelectorAll("[aria-label]");
    for (var i = 0; i < labeled.length; i++) {
      if (isPromotionLabel(labeled[i].getAttribute("aria-label"))) { return true; }
    }
    var spans = article.querySelectorAll("span");
    for (var j = 0; j < spans.length; j++) {
      var span = spans[j];
      if (span.childElementCount === 0 && isPromotionLabel(span.textContent)) {
        return true;
      }
    }
    return false;
  }

  function processArticle(article) {
    if (!article || !article.setAttribute) { return; }
    if (article.getAttribute(SCANNED_ATTR)) { return; }
    article.setAttribute(SCANNED_ATTR, "1");
    if (looksPromoted(article)) {
      article.setAttribute(HIDDEN_ATTR, HIDDEN_VALUE);
    }
  }

  function processNode(node) {
    if (!node) { return; }
    if (node.tagName === "ARTICLE") {
      processArticle(node);
      return;
    }
    if (!node.querySelectorAll) { return; }
    var articles = node.querySelectorAll("article");
    for (var i = 0; i < articles.length; i++) {
      processArticle(articles[i]);
    }
  }

  function startObserver() {
    var observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var added = mutations[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          processNode(added[j]);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function init() {
    if (!document.body) {
      setTimeout(init, 50);
      return;
    }
    ensureStyle();
    processNode(document.body);
    startObserver();
  }

  init();
})();
"""

def build_filter_script() -> QWebEngineScript:
    script = QWebEngineScript()
    script.setName(FILTER_SCRIPT_NAME)
    script.setInjectionPoint(QWebEngineScript.DocumentCreation)
    script.setWorldId(QWebEngineScript.ApplicationWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(_FILTER_JS)
    return script

def install_filter(page) -> bool:
    collection = page.scripts()
    for existing in collection.toList():
        if existing.name() == FILTER_SCRIPT_NAME:
            return False
    collection.insert(build_filter_script())
    return True
