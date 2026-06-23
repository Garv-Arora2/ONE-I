// ONE-I — minimal client helpers
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.narrative-bar-fill').forEach((el) => {
    const w = el.style.width;
    el.style.width = '0';
    requestAnimationFrame(() => { el.style.width = w; });
  });
});
