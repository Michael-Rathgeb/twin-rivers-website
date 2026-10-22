// Lead form: one script for every page's #quote form (BUILD-PLAN.md section 5.3).
// Success is shown only when the webhook answers 2xx. On any failure the
// visitor keeps what they typed and gets the phone number instead.
(function () {
  var MIN_FILL_MS = 2000;
  var loadedAt = Date.now();

  function phoneLink(form) {
    var a = form.querySelector(".quote-call a[href^='tel:']") || document.querySelector("a[href^='tel:']");
    return a ? { href: a.getAttribute("href"), text: a.textContent.trim() } : null;
  }

  function setStatus(form, kind, html) {
    var el = form.querySelector(".form-status");
    el.className = "form-status " + kind;
    el.innerHTML = html;
  }

  function showSuccess(form) {
    var tel = phoneLink(form);
    form.innerHTML =
      '<div class="form-success" role="status">' +
      '<p class="quote-title">Thanks — we got it.</p>' +
      "<p>We'll call you shortly to set up a time.</p>" +
      (tel ? '<p>Water coming in right now? Call <a href="' + tel.href + '">' + tel.text + "</a>.</p>" : "") +
      "</div>";
  }

  document.querySelectorAll("form[data-lead-form]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var data = new FormData(form);
      var name = String(data.get("name") || "").trim();
      var phone = String(data.get("phone") || "").trim();
      var tel = phoneLink(form);

      // Spam traps: a filled honeypot or an instant submit gets a quiet "thanks".
      if (String(data.get("company_website") || "").trim() || Date.now() - loadedAt < MIN_FILL_MS) {
        showSuccess(form);
        return;
      }

      var problems = [];
      if (!name) problems.push("your name");
      if (phone.replace(/\D/g, "").length < 10) problems.push("a phone number with area code");
      if (problems.length) {
        setStatus(form, "error", "Please add " + problems.join(" and ") + ".");
        (name ? form.querySelector("[name=phone]") : form.querySelector("[name=name]")).focus();
        return;
      }

      var btn = form.querySelector("button[type=submit]");
      var label = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Sending…";
      setStatus(form, "", "");

      var payload = {
        name: name,
        phone: phone,
        email: String(data.get("email") || "").trim(),
        service: String(data.get("service") || ""),
        description: String(data.get("description") || "").trim(),
        source: "Twin Rivers Website",
        page: location.pathname,
        submitted_at: new Date().toISOString()
      };

      // The endpoint comes from _src/site.json ("webhook") via the form's data-endpoint.
      fetch(form.getAttribute("data-endpoint"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
        .then(function (res) {
          if (!res.ok) throw new Error("Webhook answered " + res.status);
          if (typeof window.gtag === "function") {
            window.gtag("event", "generate_lead", {
              form_location: form.getAttribute("data-form-location") || "hero",
              page_path: location.pathname
            });
          }
          showSuccess(form);
        })
        .catch(function (err) {
          console.error("Lead form failed:", err);
          btn.disabled = false;
          btn.textContent = label;
          setStatus(
            form,
            "error",
            "Something went wrong and your request didn't send." +
              (tel ? ' Please call us at <a href="' + tel.href + '">' + tel.text + "</a>." : " Please call us.")
          );
        });
    });
  });
})();
