/* Shared, device-only appearance preference. Load before styles to avoid a flash. */
(() => {
  const key = "atlas.theme.v1";
  const valid = (value) => value === "dark" || value === "light";
  function apply(value) {
    const theme = valid(value) ? value : "light";
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll("[data-theme-select]").forEach((select) => {
      select.value = theme;
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#090b0d" : "#f8f9fc";
    window.dispatchEvent(new Event("atlas-theme-change"));
  }
  try { apply(localStorage.getItem(key)); } catch { apply("light"); }
  document.addEventListener("DOMContentLoaded", () => {
    apply(document.documentElement.dataset.theme);
  });
  document.addEventListener("change", (event) => {
    if (!event.target.matches("[data-theme-select]")) return;
    const value = event.target.value;
    if (!valid(value)) return;
    apply(value);
    let message = "この端末に保存しました。Study Atlas と Anki Atlas に共通で適用します。";
    try { localStorage.setItem(key, value); }
    catch { message = "表示を切り替えました。端末に保存できないため、再読み込みすると元に戻ります。"; }
    document.querySelectorAll("[data-theme-status]").forEach((status) => {
      status.textContent = message;
    });
  });
  window.addEventListener("storage", (event) => {
    if (event.key === key || event.key === null) apply(event.newValue);
  });
})();
