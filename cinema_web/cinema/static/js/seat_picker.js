// Sơ đồ ghế thời gian thực
(function () {
  const cfg = JSON.parse(document.getElementById("cfg").textContent);
  const mode = cfg.mode;
  const box = document.getElementById("seatmap");
  const selBox = document.getElementById("sel");
  const totalEl = document.getElementById("total");
  const cntEl = document.getElementById("cnt");
  const goBtn = document.getElementById("go");
  const errEl = document.getElementById("err");
  const typeNames = {};
  cfg.tmap.forEach(([id, name]) => typeNames[id] = name);
  const price = {}; Object.keys(cfg.prices).forEach(k => price[k] = cfg.prices[k]);
  const defType = cfg.types.length ? cfg.types[0] : null;
  const selectable = mode !== "view";
  const picked = new Map();   // seat_id -> ticket_type_id
  let seats = [], first = true;

  const fmt = n => Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".") + " đ";
  const unit = (seat, tid) => { const b = (price[tid] || 0) + seat.surcharge; return Math.round(b - cfg.pct / 100 * b); };

  function render() {
    const rows = {};
    seats.forEach(s => (rows[s.row] = rows[s.row] || []).push(s));
    box.innerHTML = "";
    Object.keys(rows).sort().forEach(r => {
      const line = document.createElement("div"); line.className = "seat-row";
      line.innerHTML = `<span class="seat-label">${r}</span>`;
      rows[r].forEach(s => {
        const b = document.createElement("button");
        b.type = "button";
        let cls = "seat t-" + s.type.split(" ")[0] + " " + s.status;
        if (picked.has(s.seat_id)) cls += " picked";
        else if (s.mine && !selectable) cls += " mine";
        b.className = cls; b.textContent = s.num;
        b.title = `${r}${s.num} · ${s.type}` + (s.surcharge ? ` (+${fmt(s.surcharge)})` : "");
        const free = s.status === "AVAILABLE" || (s.status === "HELD" && s.mine);
        if (selectable && free) b.onclick = () => toggle(s);
        else b.disabled = !free;
        line.appendChild(b);
      });
      box.appendChild(line);
    });
    const types = {}; seats.forEach(s => types[s.type] = s.surcharge);
    const st = document.getElementById("seatTypes");
    if (st) st.textContent = "Loại ghế: " + Object.entries(types).map(([k, v]) => k + (v ? ` (+${fmt(v)})` : "")).join(" · ");
    summary();
  }

  function toggle(s) {
    errEl && errEl.classList.add("d-none");
    if (picked.has(s.seat_id)) picked.delete(s.seat_id);
    else {
      if (picked.size >= cfg.max) { showErr(`Mỗi lần đặt tối đa ${cfg.max} ghế`); return; }
      picked.set(s.seat_id, defType);
    }
    render();
  }

  function summary() {
    if (!selectable) return;
    cntEl.textContent = picked.size ? `(${picked.size})` : "";
    if (!picked.size) { selBox.innerHTML = "Chưa chọn ghế nào"; totalEl.textContent = fmt(0); goBtn.disabled = true; return; }
    let total = 0;
    selBox.innerHTML = "";
    picked.forEach((tid, sid) => {
      const s = seats.find(x => x.seat_id === sid); if (!s) return;
      const u = unit(s, tid); total += u;
      const row = document.createElement("div"); row.className = "d-flex align-items-center gap-2 mb-1";
      let sel = "";
      if (mode !== "exchange") {
        sel = `<select class="form-select form-select-sm w-auto">` + cfg.types.map(t => `<option value="${t}" ${t == tid ? "selected" : ""}>${typeNames[t]} - ${fmt(price[t])}</option>`).join("") + `</select>`;
      }
      row.innerHTML = `<strong style="width:2.5rem">${s.row}${s.num}</strong>${sel}<span class="ms-auto money">${mode === "exchange" ? "" : fmt(u)}</span>`;
      const el = row.querySelector("select");
      if (el) el.onchange = () => { picked.set(sid, parseInt(el.value)); summary(); };
      selBox.appendChild(row);
    });
    totalEl.textContent = mode === "exchange" ? "—" : fmt(total);
    goBtn.disabled = false;
  }

  function showErr(m) { if (!errEl) return; errEl.textContent = m; errEl.classList.remove("d-none"); }

  async function load() {
    try {
      const r = await fetch(`/api/showtimes/${cfg.sid}/seats`);
      if (!r.ok) return;
      seats = (await r.json()).seats;
      if (first && selectable && mode !== "exchange") {   // ghế mình đang giữ -> chọn lại sẵn
        seats.filter(s => s.mine).forEach(s => picked.set(s.seat_id, defType));
      }
      first = false;
      for (const id of [...picked.keys()]) {               // ghế vừa bị người khác lấy
        const s = seats.find(x => x.seat_id === id);
        if (!s || !(s.status === "AVAILABLE" || (s.status === "HELD" && s.mine))) {
          picked.delete(id); showErr("Một số ghế bạn chọn vừa được người khác giữ, vui lòng chọn ghế khác");
        }
      }
      render();
    } catch (e) { /* mất mạng tạm thời */ }
  }

  if (goBtn) goBtn.onclick = async () => {
    goBtn.disabled = true;
    const body = { showtime_id: cfg.sid, mode: mode, booking_id: cfg.exchange,
      seats: [...picked].map(([seat_id, ticket_type_id]) => ({ seat_id, ticket_type_id })) };
    const r = await fetch("/api/cart/hold", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": window.CSRF }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({ ok: false, message: "Có lỗi xảy ra" }));
    if (d.ok) location.href = d.next;
    else { showErr(d.message); goBtn.disabled = false; load(); }
  };

  load(); setInterval(load, 5000);
})();