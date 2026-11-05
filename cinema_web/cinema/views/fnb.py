"""QLKho: UC41-UC44 (kho theo lô) · QLQR: UC62-UC64 (gọi món qua QR)"""
from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

from ..db import q, q1, ex, run
from ..security import roles_required, WAREHOUSE_STAFF, MANAGER, TICKET_STAFF, CUSTOMER
from .. import services as sv

bp = Blueprint("fnb", __name__)
CATEGORIES = {"POPCORN": "Bắp", "DRINK": "Nước uống", "SNACK": "Đồ ăn nhẹ", "COMBO": "Combo", "INGREDIENT": "Nguyên liệu"}
ORDER_STATUS = {"NEW": "Mới (chờ xác nhận)", "PREPARING": "Đang chuẩn bị", "DELIVERING": "Đang giao", "DONE": "Hoàn tất", "CANCELLED": "Đã hủy"}
PAY_METHODS = {"MOMO": "Ví MoMo", "ZALOPAY": "ZaloPay", "VNPAY": "VNPay", "CARD": "Thẻ ngân hàng / Visa"}


def expiry_state(exp, today=None):
    today = today or date.today()
    e = sv.to_date(exp)
    if e < today:
        return "EXPIRED"
    return "NEAR_EXPIRY" if (e - today).days <= sv.setting("NEAR_EXPIRY_DAYS", 7) else "OK"


# ================================================================== UC41 Nhập kho theo lô
@bp.route("/warehouse/receive", methods=["GET", "POST"])
@roles_required(WAREHOUSE_STAFF)
def receive():
    products = q("SELECT * FROM fb_products ORDER BY category, product_name")
    suppliers = q("SELECT * FROM suppliers ORDER BY name")
    if request.method == "POST":
        f = request.form
        if not g.employee:
            raise sv.AppError("Tài khoản chưa có hồ sơ nhân viên nên không thể lập phiếu nhập")
        new_name = f.get("new_product", "").strip()
        pid = f.get("product_id")
        sup_new = f.get("new_supplier", "").strip()
        sup_id = f.get("supplier_id")
        qty, exp = f.get("quantity", "").strip(), f.get("expiry_date")
        imp = sv.to_date(f.get("import_date")) if f.get("import_date") else date.today()
        if not ((pid or new_name) and qty.isdigit() and int(qty) > 0 and exp and (sup_id or sup_new)):       # 2a
            flash("Thiếu trường bắt buộc: sản phẩm, số lượng, hạn sử dụng, nhà cung cấp", "danger")
            return render_template("fnb/receive.html", products=products, suppliers=suppliers, cats=CATEGORIES, f=f, today=date.today())
        if sv.to_date(exp) < date.today():
            flash("Cảnh báo: hạn sử dụng đã qua, không thể nhập lô này", "danger")                           # 2b
            return render_template("fnb/receive.html", products=products, suppliers=suppliers, cats=CATEGORIES, f=f, today=date.today())
        if new_name:
            if q1("SELECT 1 AS x FROM fb_products WHERE product_name=%s", (new_name,)):
                raise sv.AppError("Sản phẩm đã tồn tại, hãy chọn trong danh sách")
            try:
                price = int(f.get("new_price", "0") or 0)
            except ValueError:
                price = 0
            pid = ex("INSERT INTO fb_products (product_name, category, unit, price, is_combo) VALUES (%s,%s,%s,%s,0)",
                     (new_name, f.get("new_category", "INGREDIENT"), f.get("new_unit", "cái") or "cái", price))
        if sup_new:
            sup = q1("SELECT supplier_id FROM suppliers WHERE name=%s", (sup_new,))
            sup_id = sup["supplier_id"] if sup else ex("INSERT INTO suppliers (name) VALUES (%s)", (sup_new,))
        rid = ex("INSERT INTO stock_receipts (supplier_id, received_by, receipt_date, note) VALUES (%s,%s,%s,%s)",
                 (sup_id, g.employee["employee_id"], imp, f.get("note", "").strip() or None))
        n = q1("SELECT COUNT(*) AS n FROM inventory_batches WHERE import_date=%s", (imp,))["n"] + 1
        code = f"LO-{imp:%Y%m%d}-{n:02d}"                                                                      # hệ thống tự tạo mã lô
        while q1("SELECT 1 AS x FROM inventory_batches WHERE batch_code=%s", (code,)):
            n += 1
            code = f"LO-{imp:%Y%m%d}-{n:02d}"
        try:
            cost = int(f.get("unit_cost", "0") or 0)
        except ValueError:
            cost = 0
        bid = ex("INSERT INTO inventory_batches (batch_code, receipt_id, product_id, qty_received, qty_remaining, import_date, expiry_date, unit_cost) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (code, rid, pid, int(qty), int(qty), imp, exp, cost))
        ex("INSERT INTO stock_movements (batch_id, movement_type, quantity, created_by) VALUES (%s,'IN',%s,%s)", (bid, int(qty), g.employee["employee_id"]))
        flash(f"Đã nhập kho thành công. Mã lô: {code}", "success")
        return redirect(url_for("fnb.stock"))
    return render_template("fnb/receive.html", products=products, suppliers=suppliers, cats=CATEGORIES, f={}, today=date.today())


# ================================================================== UC42 Xem tồn kho theo lô
@bp.route("/warehouse/stock")
@roles_required(WAREHOUSE_STAFF, MANAGER)
def stock():
    pid = request.args.get("product", type=int)
    sql = ("SELECT b.*, p.product_name, p.unit, sp.name AS supplier FROM inventory_batches b JOIN fb_products p ON p.product_id=b.product_id "
           "JOIN stock_receipts r ON r.receipt_id=b.receipt_id JOIN suppliers sp ON sp.supplier_id=r.supplier_id")
    args = ()
    if pid:
        sql += " WHERE b.product_id=%s"
        args = (pid,)
    rows = q(sql + " ORDER BY p.product_name, b.import_date, b.expiry_date", args)
    today = date.today()
    for r in rows:
        r["state"] = expiry_state(r["expiry_date"], today) if r["qty_remaining"] > 0 else "EMPTY"
        r["days_left"] = (sv.to_date(r["expiry_date"]) - today).days
    return render_template("fnb/stock.html", rows=rows, products=q("SELECT * FROM fb_products ORDER BY product_name"), pid=pid)


# ================================================================== UC43 Cảnh báo lô cận hạn / hết hạn
@bp.route("/warehouse/alerts", methods=["GET", "POST"])
@roles_required(WAREHOUSE_STAFF, MANAGER)
def alerts():
    if request.method == "POST":
        act = request.form.get("action")
        if act == "scan":
            n = sv.expiry_scan()
            flash(f"Đã quét kho: {n} cảnh báo mới", "success")
        elif act == "handle":
            a = q1("SELECT a.*, b.qty_remaining FROM stock_alerts a JOIN inventory_batches b ON b.batch_id=a.batch_id WHERE a.alert_id=%s",
                   (request.form.get("alert_id"),))
            if a and not a["is_handled"]:
                emp = g.employee["employee_id"] if g.employee else None
                if a["alert_type"] == "EXPIRED" and int(a["qty_remaining"]) > 0:      # hủy hàng hết hạn khỏi kho
                    ex("INSERT INTO stock_movements (batch_id, movement_type, quantity, created_by) VALUES (%s,'OUT_EXPIRED',%s,%s)",
                       (a["batch_id"], a["qty_remaining"], emp))
                    run("UPDATE inventory_batches SET qty_remaining=0 WHERE batch_id=%s", (a["batch_id"],))
                run("UPDATE stock_alerts SET is_handled=1, handled_by=%s WHERE alert_id=%s", (emp, a["alert_id"]))
                flash("Đã xử lý cảnh báo", "success")
        return redirect(url_for("fnb.alerts"))
    rows = q("SELECT a.*, b.batch_code, b.qty_remaining, b.expiry_date, p.product_name FROM stock_alerts a JOIN inventory_batches b "
             "ON b.batch_id=a.batch_id JOIN fb_products p ON p.product_id=b.product_id ORDER BY a.is_handled, a.alert_date DESC, a.alert_id DESC LIMIT 200")
    return render_template("fnb/alerts.html", rows=rows)


# ================================================================== UC62 Quét QR xem menu & gọi món
def _menu():
    items = q("SELECT * FROM fb_products WHERE is_active=1 AND category<>'INGREDIENT' ORDER BY is_combo DESC, category, product_name")
    for p in items:
        p["available"] = sv.product_available(p["product_id"])
    return items


@bp.route("/qr/<code>", methods=["GET", "POST"])
@roles_required(CUSTOMER)
def qr_menu(code):
    loc = q1("SELECT * FROM qr_locations WHERE qr_code=%s AND is_active=1", (code,))
    if not loc:
        return render_template("error.html", code=400, msg="Mã QR không hợp lệ"), 400                         # 1a
    menu = _menu()
    if request.method == "POST":
        picks = []
        for p in menu:
            n = request.form.get(f"qty_{p['product_id']}", "0")
            if n.isdigit() and int(n) > 0:
                if int(n) > p["available"]:
                    flash(f"Món \"{p['product_name']}\" đã hết hàng, vui lòng chọn món khác", "danger")       # 3a
                    return redirect(url_for("fnb.qr_menu", code=code))
                picks.append((p, int(n)))
        if not picks:
            flash("Vui lòng chọn ít nhất một món", "danger")
            return redirect(url_for("fnb.qr_menu", code=code))
        method = request.form.get("method")
        if method not in PAY_METHODS and method != "AT_COUNTER":
            flash("Vui lòng chọn hình thức thanh toán", "danger")
            return redirect(url_for("fnb.qr_menu", code=code))
        total = sum(int(p["price"]) * n for p, n in picks)
        oid = ex("INSERT INTO fb_orders (order_code, customer_id, qr_id, total_amount, payment_method, status) VALUES (%s,%s,%s,%s,%s,'NEW')",
                 (sv.new_code("FB", "fb_orders", "order_code"), g.customer["customer_id"], loc["qr_id"], total,
                  "AT_COUNTER" if method == "AT_COUNTER" else "ONLINE"))
        for p, n in picks:
            ex("INSERT INTO fb_order_items (fb_order_id, product_id, quantity, unit_price) VALUES (%s,%s,%s,%s)", (oid, p["product_id"], n, p["price"]))
        if method != "AT_COUNTER":
            ex("INSERT INTO payments (fb_order_id, method, amount, status) VALUES (%s,%s,%s,'PENDING')", (oid, method, total))
            return redirect(url_for("fnb.qr_pay", oid=oid))
        sv.notify_roles([TICKET_STAFF], "Đơn gọi món mới", f"{loc['label'] or 'Sảnh'}: đơn mới chờ xác nhận")
        flash("Đã gửi đơn đến nhân viên phục vụ. Bạn sẽ thanh toán khi nhận món.", "success")
        return redirect(url_for("fnb.qr_order", oid=oid))
    return render_template("fnb/qr_menu.html", loc=loc, menu=menu, cats=CATEGORIES, methods=PAY_METHODS)


def _order_or_404(oid):
    o = q1("SELECT o.*, l.label, l.location_type FROM fb_orders o JOIN qr_locations l ON l.qr_id=o.qr_id WHERE o.fb_order_id=%s", (oid,))
    if not o:
        abort(404)
    if not (g.customer and o["customer_id"] == g.customer["customer_id"]) and g.user["role_code"] not in (TICKET_STAFF, MANAGER, "ADMIN"):
        abort(403)
    return o


@bp.route("/qr/order/<int:oid>/pay", methods=["GET", "POST"])
@roles_required(CUSTOMER)
def qr_pay(oid):
    o = _order_or_404(oid)
    pay = q1("SELECT * FROM payments WHERE fb_order_id=%s ORDER BY payment_id DESC LIMIT 1", (oid,))
    if o["payment_status"] == "PAID" or not pay:
        return redirect(url_for("fnb.qr_order", oid=oid))
    if request.method == "POST":
        if request.form.get("result") == "ok":
            run("UPDATE payments SET status='SUCCESS', paid_at=%s, transaction_ref=%s WHERE payment_id=%s", (sv.now(), f"SIMFB{oid:06d}", pay["payment_id"]))
            run("UPDATE fb_orders SET payment_status='PAID' WHERE fb_order_id=%s", (oid,))
            sv.add_points(o["customer_id"], o["total_amount"], None, f"Tích điểm đơn F&B {o['order_code']}")
            sv.notify_roles([TICKET_STAFF], "Đơn gọi món mới", f"{o['label'] or 'Sảnh'}: đơn {o['order_code']} đã thanh toán, chờ xác nhận")
            flash("Thanh toán thành công. Đơn đã được gửi đến nhân viên phục vụ.", "success")
            return redirect(url_for("fnb.qr_order", oid=oid))
        run("UPDATE payments SET status='FAILED' WHERE payment_id=%s", (pay["payment_id"],))
        ex("INSERT INTO payments (fb_order_id, method, amount, status) VALUES (%s,%s,%s,'PENDING')", (oid, pay["method"], pay["amount"]))
        flash("Thanh toán thất bại. Bạn có thể thử lại.", "danger")
        return redirect(url_for("fnb.qr_pay", oid=oid))
    return render_template("fnb/qr_pay.html", o=o, pay=pay, methods=PAY_METHODS)


@bp.route("/qr/order/<int:oid>")
def qr_order(oid):
    o = _order_or_404(oid)
    items = q("SELECT i.*, p.product_name FROM fb_order_items i JOIN fb_products p ON p.product_id=i.product_id WHERE i.fb_order_id=%s", (oid,))
    return render_template("fnb/qr_order.html", o=o, items=items, ORDER_STATUS=ORDER_STATUS)


# ================================================================== UC63-UC64 Nhân viên xử lý đơn
@bp.route("/staff/orders")
@roles_required(TICKET_STAFF)
def staff_orders():
    show = request.args.get("show", "open")
    cond = "o.status IN ('NEW','PREPARING','DELIVERING')" if show == "open" else "o.status IN ('DONE','CANCELLED')"
    rows = q("SELECT o.*, l.label, l.location_type, u.full_name FROM fb_orders o JOIN qr_locations l ON l.qr_id=o.qr_id "
             "LEFT JOIN customers c ON c.customer_id=o.customer_id LEFT JOIN users u ON u.user_id=c.user_id WHERE " + cond +
             " ORDER BY o.fb_order_id DESC LIMIT 100")
    for o in rows:
        o["items"] = q("SELECT i.quantity, p.product_name FROM fb_order_items i JOIN fb_products p ON p.product_id=i.product_id "
                       "WHERE i.fb_order_id=%s", (o["fb_order_id"],))
    return render_template("fnb/staff_orders.html", rows=rows, show=show, ORDER_STATUS=ORDER_STATUS)


NEXT = {"NEW": "PREPARING", "PREPARING": "DELIVERING", "DELIVERING": "DONE"}


@bp.route("/staff/orders/<int:oid>/status", methods=["POST"])
@roles_required(TICKET_STAFF)
def staff_order_status(oid):
    o = q1("SELECT o.*, l.label FROM fb_orders o JOIN qr_locations l ON l.qr_id=o.qr_id WHERE o.fb_order_id=%s FOR UPDATE", (oid,))
    if not o:
        abort(404)
    emp = g.employee["employee_id"] if g.employee else None
    if request.form.get("action") == "cancel":
        if o["status"] != "NEW":
            raise sv.AppError("Chỉ hủy được đơn chưa xác nhận")
        run("UPDATE fb_orders SET status='CANCELLED', handled_by=%s WHERE fb_order_id=%s", (emp, oid))
        flash("Đã hủy đơn", "info")
        return redirect(url_for("fnb.staff_orders"))
    nxt = NEXT.get(o["status"])
    if not nxt:
        raise sv.AppError("Đơn đã ở trạng thái cuối")
    if o["status"] == "NEW":                                                           # xác nhận đơn -> trừ kho FIFO (UC44)
        for it in q("SELECT * FROM fb_order_items WHERE fb_order_id=%s", (oid,)):
            sv.fifo_deduct(it["product_id"], int(it["quantity"]), fb_order_id=oid, emp_id=emp)
    if nxt == "DONE" and o["payment_status"] == "UNPAID":                               # thu tiền khi giao xong
        run("UPDATE fb_orders SET payment_status='PAID' WHERE fb_order_id=%s", (oid,))
        ex("INSERT INTO payments (fb_order_id, method, amount, status, paid_at) VALUES (%s,'CASH',%s,'SUCCESS',%s)", (oid, o["total_amount"], sv.now()))
        if o["customer_id"]:
            sv.add_points(o["customer_id"], o["total_amount"], None, f"Tích điểm đơn F&B {o['order_code']}")
    run("UPDATE fb_orders SET status=%s, handled_by=%s WHERE fb_order_id=%s", (nxt, emp, oid))
    if o["customer_id"]:
        cu = q1("SELECT user_id FROM customers WHERE customer_id=%s", (o["customer_id"],))
        sv.notify(cu["user_id"], f"Đơn {o['order_code']}: {ORDER_STATUS[nxt]}", "")
    flash(f"Đã cập nhật trạng thái: {ORDER_STATUS[nxt]}", "success")
    return redirect(url_for("fnb.staff_orders"))


# ------------------------------------------------------------------ in mã QR (ghế/sảnh)
@bp.route("/manage/qr")
@roles_required(MANAGER)
def qr_print():
    rows = q("SELECT * FROM qr_locations WHERE is_active=1 ORDER BY location_type DESC, room_id, label")
    return render_template("fnb/qr_print.html", rows=rows)
