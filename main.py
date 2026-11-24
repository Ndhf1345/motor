"""CARE-MOTOR: pencatat servis motor berkala. Python + SQLite, tanpa dependensi."""
import hashlib
import hmac
import os
import sqlite3
from datetime import datetime

DB = "care_motor.db"
INTERVAL = {"Ganti Oli": 2000, "Oli Gardan": 5000, "Tune Up": 8000,
            "Kampas Rem": 10000, "Ban": 20000}
WARN_KM = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE, password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kendaraan (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES user(id),
    nomor_polisi TEXT NOT NULL, merk TEXT NOT NULL, tipe TEXT NOT NULL,
    tahun INTEGER NOT NULL, kilometer_saat_ini INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS riwayat_servis (
    id INTEGER PRIMARY KEY AUTOINCREMENT, id_kendaraan INTEGER NOT NULL REFERENCES kendaraan(id),
    jenis_servis TEXT NOT NULL, km_saat_servis INTEGER NOT NULL, tanggal_servis TEXT NOT NULL,
    biaya INTEGER NOT NULL, km_target_berikutnya INTEGER NOT NULL, catatan TEXT);
"""


def fmt(n):
    """15500 -> '15.500'"""
    return f"{n:,}".replace(",", ".")


# ---------- database & akun ----------

def connect(path=DB):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def register(db, nama, username, password):
    nama, username = nama.strip(), username.strip()
    if not nama or not username:
        raise ValueError("Nama dan username wajib diisi")
    if len(password) < 6:
        raise ValueError("Password terlalu pendek")
    if db.execute("SELECT 1 FROM user WHERE username=?", (username,)).fetchone():
        raise ValueError("Username sudah dipakai")
    salt = os.urandom(16).hex()
    db.execute("INSERT INTO user (nama, username, password) VALUES (?,?,?)",
               (nama, username, f"{salt}${_hash(password, salt)}"))
    db.commit()


def login(db, username, password):
    """Return (id, nama) atau None."""
    row = db.execute("SELECT id, nama, password FROM user WHERE username=?",
                     (username.strip(),)).fetchone()
    if row:
        salt, hashed = row[2].split("$")
        if hmac.compare_digest(_hash(password, salt), hashed):
            return row[0], row[1]
    return None


# ---------- kendaraan ----------

def add_vehicle(db, uid, nopol, merk, tipe, tahun, km):
    if km < 0:
        raise ValueError("Kilometer tidak boleh negatif")
    if not (nopol.strip() and merk.strip() and tipe.strip()):
        raise ValueError("Nopol, merk, dan tipe wajib diisi")
    if not 1900 <= tahun <= datetime.now().year + 1:
        raise ValueError("Tahun tidak valid")
    cur = db.execute(
        "INSERT INTO kendaraan (user_id, nomor_polisi, merk, tipe, tahun, kilometer_saat_ini)"
        " VALUES (?,?,?,?,?,?)",
        (uid, nopol.strip().upper(), merk.strip(), tipe.strip(), tahun, km))
    db.commit()
    return cur.lastrowid


def list_vehicles(db, uid):
    return db.execute("SELECT id, nomor_polisi, merk, tipe, kilometer_saat_ini"
                      " FROM kendaraan WHERE user_id=?", (uid,)).fetchall()


def get_vehicle(db, uid, vid):
    """Cek kepemilikan: user hanya boleh akses kendaraannya sendiri."""
    row = db.execute("SELECT id, nomor_polisi, merk, tipe, tahun, kilometer_saat_ini"
                     " FROM kendaraan WHERE id=? AND user_id=?", (vid, uid)).fetchone()
    if not row:
        raise ValueError("Kendaraan tidak ditemukan")
    return row


def update_km(db, uid, vid, km_baru):
    km_lama = get_vehicle(db, uid, vid)[5]
    if km_baru < km_lama:
        raise ValueError("Kilometer tidak boleh berkurang")
    db.execute("UPDATE kendaraan SET kilometer_saat_ini=? WHERE id=?", (km_baru, vid))
    db.commit()


# ---------- servis ----------

def add_service(db, uid, vid, jenis, tanggal, km, biaya, catatan=""):
    """Simpan riwayat + target berikutnya. Return target (km)."""
    km_now = get_vehicle(db, uid, vid)[5]
    if jenis not in INTERVAL:
        raise ValueError("Jenis servis tidak dikenal")
    try:
        datetime.strptime(tanggal, "%d-%m-%Y")
    except ValueError:
        raise ValueError("Format tanggal harus DD-MM-YYYY")
    if km < 0 or biaya < 0:
        raise ValueError("KM dan biaya tidak boleh negatif")
    target = km + INTERVAL[jenis]
    db.execute("INSERT INTO riwayat_servis (id_kendaraan, jenis_servis, km_saat_servis,"
               " tanggal_servis, biaya, km_target_berikutnya, catatan) VALUES (?,?,?,?,?,?,?)",
               (vid, jenis, km, tanggal, biaya, target, catatan))
    if km > km_now:  # servis di KM lebih tinggi berarti odometer sudah segitu
        db.execute("UPDATE kendaraan SET kilometer_saat_ini=? WHERE id=?", (km, vid))
    db.commit()
    return target


def riwayat(db, vid):
    return db.execute("SELECT tanggal_servis, jenis_servis, km_saat_servis, biaya"
                      " FROM riwayat_servis WHERE id_kendaraan=? ORDER BY km_saat_servis, id",
                      (vid,)).fetchall()


def latest_targets(db, vid):
    """Target terbaru per jenis servis: [(jenis, target)]."""
    return db.execute(
        "SELECT jenis_servis, km_target_berikutnya FROM riwayat_servis r WHERE id_kendaraan=?"
        " AND id=(SELECT id FROM riwayat_servis WHERE id_kendaraan=r.id_kendaraan"
        " AND jenis_servis=r.jenis_servis ORDER BY km_saat_servis DESC, id DESC LIMIT 1)",
        (vid,)).fetchall()


def cek_status(km, target):
    """Percabangan status: return teks notifikasi."""
    sisa = target - km
    if sisa < 0:
        return f"BAHAYA !!!\nAnda terlambat servis\nKeterlambatan: {fmt(-sisa)} Km"
    if sisa < WARN_KM:
        return f"PERINGATAN\nServis akan jatuh tempo\nSisa: {fmt(sisa)} Km lagi"
    return f"STATUS: Masih Aman\nSisa: {fmt(sisa)} Km lagi"


def status_servis(db, vid, km):
    """[(sisa, jenis, target, teks)] diurutkan dari yang paling mendesak."""
    return sorted((target - km, jenis, target, cek_status(km, target))
                  for jenis, target in latest_targets(db, vid))


def ringkasan(db, vid):
    n, total = db.execute("SELECT COUNT(*), COALESCE(SUM(biaya),0) FROM riwayat_servis"
                          " WHERE id_kendaraan=?", (vid,)).fetchone()
    top = db.execute("SELECT jenis_servis, COUNT(*) c FROM riwayat_servis WHERE id_kendaraan=?"
                     " GROUP BY jenis_servis ORDER BY c DESC LIMIT 1", (vid,)).fetchone()
    return n, total, (round(total / n) if n else 0), top


def laporan(db, uid, vid):
    _, nopol, merk, tipe, _, km = get_vehicle(db, uid, vid)
    n, total, _, _ = ringkasan(db, vid)
    st = status_servis(db, vid, km)
    nxt = f"{st[0][1]}\nTarget: {fmt(st[0][2])} Km" if st else "-"
    bar = "=" * 22
    return (f"{bar}\nCARE MOTOR REPORT\n{bar}\nMotor: {merk} {tipe} ({nopol})\n"
            f"KM Saat Ini: {fmt(km)}\nTotal Servis: {n}\nTotal Biaya: Rp{fmt(total)}\n"
            f"Servis Berikutnya: {nxt}\n{bar}")


# ---------- menu (input/output) ----------

def ask_int(label):
    while True:
        try:
            return int(input(label).replace(".", "").strip())
        except ValueError:
            print("ERROR: Masukkan angka")


def pilih_kendaraan(db, uid):
    vs = list_vehicles(db, uid)
    if not vs:
        raise ValueError("Belum ada kendaraan, tambah dulu")
    tampil_kendaraan(vs)
    return ask_int("ID Kendaraan: ")


def tampil_kendaraan(vs):
    print("ID | Nopol | Merk | Tipe | KM")
    for v in vs:
        print(f"{v[0]} | {v[1]} | {v[2]} | {v[3]} | {v[4]}")


def m_tambah(db, uid):
    add_vehicle(db, uid, input("Nomor Polisi: "), input("Merk: "), input("Tipe: "),
                ask_int("Tahun: "), ask_int("KM Saat Ini: "))
    print("Kendaraan tersimpan")


def m_lihat(db, uid):
    vs = list_vehicles(db, uid)
    tampil_kendaraan(vs) if vs else print("Belum ada kendaraan")


def m_update(db, uid):
    vid = pilih_kendaraan(db, uid)
    update_km(db, uid, vid, ask_int("Kilometer Baru: "))
    print("Kilometer diperbarui")


def m_servis(db, uid):
    vid = pilih_kendaraan(db, uid)
    for i, j in enumerate(INTERVAL, 1):
        print(f"{i}. {j} (tiap {fmt(INTERVAL[j])} Km)")
    pil = ask_int("Jenis Servis (nomor): ")
    if not 1 <= pil <= len(INTERVAL):
        raise ValueError("Pilihan jenis servis tidak valid")
    jenis = list(INTERVAL)[pil - 1]
    target = add_service(db, uid, vid, jenis, input("Tanggal (DD-MM-YYYY): "),
                         ask_int("KM Servis: "), ask_int("Biaya: "), input("Catatan: "))
    print(f"Tersimpan. Target {jenis} berikutnya: {fmt(target)} Km")


def m_jadwal(db, uid):
    vid = pilih_kendaraan(db, uid)
    st = status_servis(db, vid, get_vehicle(db, uid, vid)[5])
    for _, jenis, target, _ in st or []:
        print(f"{jenis}: {fmt(target)} Km")
    st or print("Belum ada riwayat servis")


def m_notif(db, uid, vid=None):
    vid = vid or pilih_kendaraan(db, uid)
    km = get_vehicle(db, uid, vid)[5]
    st = status_servis(db, vid, km)
    for _, jenis, _, teks in st:
        print(f"[{jenis}]\n{teks}\n")
    st or print("Belum ada riwayat servis")


def m_laporan(db, uid):
    vid = pilih_kendaraan(db, uid)
    print(laporan(db, uid, vid))
    n, total, rata, top = ringkasan(db, vid)
    print(f"Biaya Rata-rata: Rp{fmt(rata)}")
    if top:
        print(f"Servis Terbanyak: {top[0]} ({top[1]} kali)")
    print("\nTanggal | Servis | KM | Biaya")
    for r in riwayat(db, vid):
        print(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}")


def dashboard(db, uid):
    """Notifikasi otomatis saat login untuk semua kendaraan."""
    for v in list_vehicles(db, uid):
        print(f"\n--- {v[2]} {v[3]} ({v[1]}) ---")
        m_notif(db, uid, v[0])


def run_menu(db, uid):
    aksi = {"1": m_tambah, "2": m_lihat, "3": m_update, "4": m_servis,
            "5": m_jadwal, "6": m_notif, "7": m_laporan}
    dashboard(db, uid)
    while True:
        print("\n===== CARE MOTOR =====\n1. Tambah Kendaraan\n2. Lihat Kendaraan\n"
              "3. Update Kilometer\n4. Tambah Riwayat Servis\n5. Jadwal Servis Berikutnya\n"
              "6. Notifikasi Servis\n7. Laporan Kendaraan\n8. Logout")
        pil = input("Pilih: ").strip()
        if pil == "8":
            return
        if pil not in aksi:
            print("ERROR: Menu tidak ada")
            continue
        try:
            aksi[pil](db, uid)
        except ValueError as e:
            print(f"ERROR: {e}")


def main():
    db = connect()
    while True:
        print("\n== CARE MOTOR ==\n1. Registrasi\n2. Login\n3. Keluar")
        pil = input("Pilih: ").strip()
        if pil == "1":
            try:
                register(db, input("Nama Lengkap: "), input("Username: "), input("Password: "))
                print("Registrasi berhasil")
            except ValueError as e:
                print(f"ERROR: {e}")
        elif pil == "2":
            user = login(db, input("Username: "), input("Password: "))
            if user:
                print(f"Login Berhasil. Halo, {user[1]}")
                run_menu(db, user[0])
            else:
                print("Username atau Password Salah")
        elif pil == "3":
            return


if __name__ == "__main__":
    main()
