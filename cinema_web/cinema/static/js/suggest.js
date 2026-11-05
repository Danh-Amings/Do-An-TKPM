// Gợi ý tìm phim theo thời gian thực
(function () {
  const input = document.getElementById("q");
  const box = document.getElementById("sugg");
  if (!input || !box) return;
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const v = input.value.trim();
    if (!v) { box.innerHTML = ""; return; }
    timer = setTimeout(async () => {
      const r = await fetch("/api/movies/suggest?q=" + encodeURIComponent(v));
      const items = await r.json();
      box.innerHTML = items.map(i => `<a class="list-group-item list-group-item-action" href="/movies/${i.id}">${i.title} <small class="text-muted">(${i.year})</small></a>`).join("");
    }, 200);
  });
  document.addEventListener("click", e => { if (!box.contains(e.target) && e.target !== input) box.innerHTML = ""; });
})();
