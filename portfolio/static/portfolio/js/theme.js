(function () {
  var root = document.documentElement;
  var storageKey = "stock-workbench-theme";

  function currentTheme() {
    return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    var nextTheme = theme === "dark" ? "dark" : "light";
    root.setAttribute("data-theme", nextTheme);
    root.classList.toggle("dark", nextTheme === "dark");
    try {
      localStorage.setItem(storageKey, nextTheme);
    } catch (error) {
      // Ignore storage failures and keep the current in-memory theme.
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-theme-toggle]");
    if (!button) {
      return;
    }
    event.preventDefault();
    applyTheme(currentTheme() === "dark" ? "light" : "dark");
  });
}());

(function () {
  var sidebar = document.querySelector("[data-navigation-sidebar]");
  var content = document.querySelector("[data-navigation-content]");
  var openButton = document.querySelector("[data-nav-open-button]");
  var closeButtons = document.querySelectorAll("[data-nav-backdrop]");
  var backdrop = document.querySelector("[data-nav-backdrop]");
  var desktopQuery = window.matchMedia("(min-width: 1024px)");
  var storageKey = "stock-workbench-sidebar-collapsed";

  if (!sidebar || !content || !openButton) {
    return;
  }

  function setExpanded(expanded) {
    openButton.setAttribute("aria-expanded", expanded ? "true" : "false");
  }

  function showNavigation() {
    if (desktopQuery.matches) {
      sidebar.classList.remove("sidebar-collapsed");
      content.classList.remove("sidebar-collapsed");
      localStorage.setItem(storageKey, "false");
      setExpanded(true);
      if (backdrop) {
        backdrop.hidden = true;
      }
      document.body.classList.remove("nav-open");
      return;
    }

    sidebar.classList.add("is-open");
    document.body.classList.add("nav-open");
    if (backdrop) {
      backdrop.hidden = false;
    }
    setExpanded(true);
  }

  function hideNavigation() {
    if (desktopQuery.matches) {
      sidebar.classList.add("sidebar-collapsed");
      content.classList.add("sidebar-collapsed");
      localStorage.setItem(storageKey, "true");
      setExpanded(false);
      return;
    }

    sidebar.classList.remove("is-open");
    document.body.classList.remove("nav-open");
    if (backdrop) {
      backdrop.hidden = true;
    }
    setExpanded(false);
  }

  function syncNavigation() {
    if (desktopQuery.matches) {
      var collapsed = localStorage.getItem(storageKey) === "true";
      sidebar.classList.toggle("sidebar-collapsed", collapsed);
      content.classList.toggle("sidebar-collapsed", collapsed);
      setExpanded(!collapsed);
      if (backdrop) {
        backdrop.hidden = true;
      }
      document.body.classList.remove("nav-open");
      return;
    }

    sidebar.classList.remove("sidebar-collapsed");
    content.classList.remove("sidebar-collapsed");
    setExpanded(sidebar.classList.contains("is-open"));
  }

  function toggleNavigation() {
    if (desktopQuery.matches) {
      if (sidebar.classList.contains("sidebar-collapsed")) {
        showNavigation();
      } else {
        hideNavigation();
      }
      return;
    }

    if (sidebar.classList.contains("is-open")) {
      hideNavigation();
    } else {
      showNavigation();
    }
  }

  openButton.addEventListener("click", toggleNavigation);
  closeButtons.forEach(function (button) {
    button.addEventListener("click", hideNavigation);
  });
  desktopQuery.addEventListener("change", syncNavigation);
  syncNavigation();
}());
