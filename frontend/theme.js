/* One preference controls public pages, sign-in, and the authenticated workspace. */
(() => {
  const key = "academy-theme";
  const root = document.documentElement;
  const system = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  let choice = null;

  try {
    const saved = window.localStorage.getItem(key);
    if (saved === "light" || saved === "dark") choice = saved;
  } catch (_) {
    // Browsers that block storage still get the system theme and a working switch.
  }

  function current() {
    return choice || (system && system.matches ? "dark" : "light");
  }

  function apply() {
    const theme = current();
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      const next = theme === "dark" ? "light" : "dark";
      button.textContent = next === "dark" ? "☾ Dark mode" : "☀ Light mode";
      button.setAttribute("aria-label", `Switch to ${next} mode`);
      button.setAttribute("title", `Switch to ${next} mode`);
    });
  }

  function set(theme) {
    if (theme !== "light" && theme !== "dark") return;
    choice = theme;
    try { window.localStorage.setItem(key, theme); } catch (_) { /* In-memory choice remains active. */ }
    apply();
  }

  apply();
  document.addEventListener("DOMContentLoaded", () => {
    apply();
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => set(current() === "dark" ? "light" : "dark"));
    });
  });
  if (system) {
    const onChange = () => { if (!choice) apply(); };
    if (system.addEventListener) system.addEventListener("change", onChange);
    else if (system.addListener) system.addListener(onChange);
  }
})();
