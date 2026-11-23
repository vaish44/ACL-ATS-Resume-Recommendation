(function () {
  var root = document.documentElement;
  var toggle = document.getElementById("themeToggle");

  function updateIcon() {
    if (!toggle) return;
    var dark = root.getAttribute("data-bs-theme") === "dark";
    toggle.innerHTML = dark ? '<i class="bi bi-sun"></i>' : '<i class="bi bi-moon-stars"></i>';
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      localStorage.setItem("theme", next);
      updateIcon();
    });
  }
  updateIcon();

  document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
    button.addEventListener("click", function () {
      var input = document.getElementById(button.dataset.togglePassword);
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.innerHTML = show ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented || !form.checkValidity()) return;
      document.getElementById("loadingText").textContent = form.dataset.loading;
      document.getElementById("loadingOverlay").classList.remove("d-none");
      form.querySelectorAll("button[type=submit]").forEach(function (b) { b.disabled = true; });
    });
  });

  window.addEventListener("pageshow", function () {
    var overlay = document.getElementById("loadingOverlay");
    if (overlay) overlay.classList.add("d-none");
    document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) { b.disabled = false; });
  });

  var roleInputs = document.querySelectorAll("input[name=role]");
  var companyField = document.getElementById("companyField");
  roleInputs.forEach(function (input) {
    input.addEventListener("change", function () {
      if (companyField) companyField.classList.toggle("d-none", input.value !== "hirer" || !input.checked);
    });
  });

  var fileInput = document.getElementById("resumeInput");
  if (fileInput) {
    var zone = fileInput.closest(".drop-zone");
    var label = zone.querySelector("[data-file-label]");
    fileInput.addEventListener("change", function () {
      if (fileInput.files.length) label.textContent = fileInput.files[0].name;
    });
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (e) { e.preventDefault(); zone.classList.add("dragging"); });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function (e) { e.preventDefault(); zone.classList.remove("dragging"); });
    });
    zone.addEventListener("drop", function (e) {
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        label.textContent = e.dataTransfer.files[0].name;
      }
    });
  }

  var checks = document.querySelectorAll(".compare-check");
  if (checks.length) {
    var bar = document.getElementById("compareBar");
    var count = document.getElementById("compareCount");
    var button = document.getElementById("compareButton");
    checks.forEach(function (check) {
      check.addEventListener("change", function () {
        var selected = document.querySelectorAll(".compare-check:checked").length;
        if (selected > 4) { check.checked = false; selected = 4; }
        count.textContent = selected;
        bar.classList.toggle("d-none", selected === 0);
        button.disabled = selected < 2;
      });
    });
  }
})();
