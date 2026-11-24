"""
CARE-MOTOR (versi Website)
Flask ini hanya jadi "wajah" baru untuk logic yang sudah ada di main.py.
Semua aturan bisnis (validasi, interval servis, perhitungan target,
status Aman/Peringatan/Bahaya) TETAP dari main.py, tidak diduplikasi di sini.
"""
from datetime import datetime

from flask import (Flask, g, flash, redirect, render_template,
                    request, session, url_for)

import main as backend  # main.py yang sama persis dengan versi CLI

app = Flask(__name__)
app.secret_key = "ganti-dengan-random-string-untuk-skripsi-sendiri"  # cukup untuk tugas/lokal


# ---------- koneksi database per-request ----------

def get_db():
    if "db" not in g:
        g.db = backend.connect()  # pakai DB yang sama: care_motor.db
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        if "uid" not in session:
            flash("Silakan login dahulu", "error")
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


def get_owned_vehicle_or_404(vid):
    """Pakai get_vehicle() dari main.py -> otomatis cek kepemilikan."""
    try:
        return backend.get_vehicle(get_db(), session["uid"], vid)
    except ValueError:
        flash("Kendaraan tidak ditemukan", "error")
        return None


# ---------- auth ----------

@app.route("/")
def index():
    return redirect(url_for("dashboard") if "uid" in session else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            backend.register(get_db(), request.form["nama"],
                              request.form["username"], request.form["password"])
            flash("Registrasi berhasil, silakan login", "success")
            return redirect(url_for("login"))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = backend.login(get_db(), request.form["username"], request.form["password"])
        if user:
            session["uid"], session["nama"] = user
            return redirect(url_for("dashboard"))
        flash("Username atau Password Salah", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- dashboard ----------

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    vehicles = backend.list_vehicles(db, session["uid"])
    # dashboard notifikasi otomatis, sama seperti dashboard() versi CLI
    notif_per_vehicle = {}
    for v in vehicles:
        vid, km = v[0], v[4]
        notif_per_vehicle[vid] = backend.status_servis(db, vid, km)
    return render_template("dashboard.html", vehicles=vehicles, notif=notif_per_vehicle)


# ---------- kendaraan ----------

@app.route("/vehicle/add", methods=["GET", "POST"])
@login_required
def add_vehicle():
    if request.method == "POST":
        try:
            backend.add_vehicle(
                get_db(), session["uid"],
                request.form["nopol"], request.form["merk"], request.form["tipe"],
                int(request.form["tahun"]), int(request.form["km"]))
            flash("Kendaraan tersimpan", "success")
            return redirect(url_for("dashboard"))
        except (ValueError, KeyError) as e:
            flash(str(e) if isinstance(e, ValueError) else "Data tidak valid", "error")
    return render_template("add_vehicle.html")


@app.route("/vehicle/<int:vid>")
@login_required
def vehicle_detail(vid):
    v = get_owned_vehicle_or_404(vid)
    if v is None:
        return redirect(url_for("dashboard"))
    db = get_db()
    km = v[5]
    status = backend.status_servis(db, vid, km)
    history = backend.riwayat(db, vid)
    n, total, rata, top = backend.ringkasan(db, vid)
    laporan_text = backend.laporan(db, session["uid"], vid)
    return render_template(
        "vehicle.html", v=v, status=status, history=history,
        n=n, total=total, rata=rata, top=top, laporan_text=laporan_text,
        jenis_list=backend.INTERVAL, fmt=backend.fmt)


@app.route("/vehicle/<int:vid>/update_km", methods=["POST"])
@login_required
def update_km(vid):
    try:
        backend.update_km(get_db(), session["uid"], vid, int(request.form["km_baru"]))
        flash("Kilometer diperbarui", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("vehicle_detail", vid=vid))


@app.route("/vehicle/<int:vid>/add_service", methods=["POST"])
@login_required
def add_service(vid):
    try:
        # input HTML type="date" -> yyyy-mm-dd, main.py minta format DD-MM-YYYY
        tgl_html = request.form["tanggal"]
        tanggal = datetime.strptime(tgl_html, "%Y-%m-%d").strftime("%d-%m-%Y")
        target = backend.add_service(
            get_db(), session["uid"], vid,
            request.form["jenis"], tanggal,
            int(request.form["km"]), int(request.form["biaya"]),
            request.form.get("catatan", ""))
        flash(f"Tersimpan. Target {request.form['jenis']} berikutnya: "
              f"{backend.fmt(target)} Km", "success")
    except ValueError as e:
        flash(f"Format tanggal tidak valid atau {e}" if "does not match" in str(e) else str(e),
              "error")
    except Exception:
        flash("Tanggal wajib diisi", "error")
    return redirect(url_for("vehicle_detail", vid=vid))


if __name__ == "__main__":
    app.run(debug=True)
