// Đếm ngược thời gian giữ ghế,hết giờ thì tải lại trang để hệ thống nhả ghế
(function () {
  const el = document.getElementById("left"); if (!el) return;
  const until = new Date(el.dataset.until).getTime() - parseInt(el.dataset.offset || 0);
  const tick = () => {
    const s = Math.max(0, Math.round((until - Date.now()) / 1000));
    el.textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
    if (s <= 0) { clearInterval(t); setTimeout(() => location.reload(), 800); }
  };
  const t = setInterval(tick, 1000); tick();
})();
