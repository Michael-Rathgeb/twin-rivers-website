// Site chrome: mobile menu, nav dropdowns, footer year, click-to-call tracking.
(function () {
  var header = document.querySelector(".site-header");
  var burger = document.querySelector(".hamburger");

  if (burger && header) {
    burger.addEventListener("click", function () {
      var open = burger.getAttribute("aria-expanded") === "true";
      burger.setAttribute("aria-expanded", String(!open));
      burger.setAttribute("aria-label", open ? "Open menu" : "Close menu");
      header.classList.toggle("menu-open", !open);
    });
  }

  // Dropdowns open on hover (CSS) and on click/tap or keyboard (here).
  var toggles = document.querySelectorAll(".nav-sub-toggle");
  function closeAll(except) {
    toggles.forEach(function (t) {
      if (t !== except) {
        t.setAttribute("aria-expanded", "false");
        t.parentElement.classList.remove("open");
      }
    });
  }
  toggles.forEach(function (t) {
    t.addEventListener("click", function () {
      var open = t.getAttribute("aria-expanded") === "true";
      closeAll(t);
      t.setAttribute("aria-expanded", String(!open));
      t.parentElement.classList.toggle("open", !open);
    });
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".has-sub")) closeAll(null);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAll(null);
  });

  // In-page links (nav "Free Inspection", CTA bands) close the mobile menu
  // and put the cursor in the form.
  document.querySelectorAll('a[href="#quote"]').forEach(function (a) {
    a.addEventListener("click", function () {
      if (header) header.classList.remove("menu-open");
      if (burger) burger.setAttribute("aria-expanded", "false");
      var first = document.querySelector("#quote input[name=name]");
      if (first) setTimeout(function () { first.focus({ preventScroll: true }); }, 400);
    });
  });

  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = new Date().getFullYear();
  });

  // GA4 click_to_call on every tel: link (no-op until a GA4 ID is set in _src/site.json).
  document.addEventListener("click", function (e) {
    var a = e.target.closest('a[href^="tel:"]');
    if (a && typeof window.gtag === "function") {
      window.gtag("event", "click_to_call", {
        link_location: a.className || "inline",
        page_path: location.pathname
      });
    }
  });
})();
