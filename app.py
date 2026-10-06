import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# 1. Konfigurasi Web
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Koneksi Resmi ke Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1rPODgznxi5QxPWk6paIK0-SsTPwIByJPcGYZ8YAUEwc/edit"

@st.cache_data(ttl=5) 
def load_data():
    try:
        df = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Racking HDI")
        df.columns = df.columns.astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"⚠ Gagal memuat data master! Error: {e}")
        st.stop()

def load_log():
    try:
        df_log = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Log Transaksi")
        if df_log.empty:
            return pd.DataFrame(columns=["Timestamp", "Tipe Transaksi", "Nama Barang", "Rak", "Qty"])
        return df_log
    except Exception:
        return pd.DataFrame(columns=["Timestamp", "Tipe Transaksi", "Nama Barang", "Rak", "Qty"])

df = load_data()
product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'
daftar_barang = sorted(df[product_col].dropna().astype(str).unique().tolist())
kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
baris_list = list(range(1, 29))

def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

daftar_rak = [f"{k}{b}" for k in kolom_list for b in baris_list if is_rack_exist(k, b)]

# =========================================================================
# A. SIDEBAR - NAVIGASI MULTI-HALAMAN
# =========================================================================
st.sidebar.title("📌 Navigasi Menu")
menu = st.sidebar.radio("Pilih Halaman:", ["🏠 Dashboard 2D", "📝 Form Transaksi"])
st.sidebar.divider()

if menu == "🏠 Dashboard 2D":
    # =========================================================================
    # B. HALAMAN 1: DASHBOARD VISUAL 2D
    # =========================================================================
    st.title("📦 Visualisasi Grid Racking Gudang (2D Matrix)")
    st.caption("Klik pada kotak untuk melihat rincian isi slot pallet.")

    st.sidebar.header("🔍 Pencarian & Filter")
    daftar_pilihan = ["-- Tampilkan Semua --"] + daftar_barang
    pilihan_pencarian = st.sidebar.selectbox("Pilih / Ketik Nama Barang:", options=daftar_pilihan)
    search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian

    st.sidebar.divider()
    st.sidebar.header("🎨 Indikator Warna")
    st.sidebar.markdown("""
    - 🟢 **Hijau (1–2 SKU):** Aman / Ideal
    - 🟡 **Kuning (3 SKU):** Warning
    - 🔴 **Merah (≥4 SKU):** Kritis
    - ⚪ **Abu-Abu (0 SKU):** Kosong
    - 🔵 **Biru:** Hasil Pencarian
    """)

    def process_matrix_data(df, search_term, prod_col):
        matrix_info = {}
        total_critical = total_kosong = 0
        lokasi_kritis = []
        lokasi_kosong = []
        
        for k in kolom_list:
            for b in baris_list:
                if not is_rack_exist(k, b):
                    matrix_info[(k, b)] = {'exist': False}
                    continue
                    
                max_slot = 31 if b <= 16 else 44
                
                sub = df[(df['Kolom'] == k) & (df['Baris'] == b)]
                if len(sub) > max_slot: sub = sub.head(max_slot)
                    
                prods = sub[prod_col].dropna().unique() if prod_col in sub.columns else []
                sku = len(prods)
                filled = sub['Part Number'].notna().sum() if 'Part Number' in sub.columns else 0
                
                usable_space = max_slot - filled
                if usable_space < 0: usable_space = 0
                
                is_match = False
                if search_term and prod_col in sub.columns:
                    match_prod = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False, regex=False).any()
                    match_part = False
                    if 'Part Number' in sub.columns:
                        match_part = sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False, regex=False).any()
                    is_match = match_prod or match_part
                
                if sku >= 4: 
                    total_critical += 1
                    lokasi_kritis.append(f"{k}{b}")
                elif sku == 0: 
                    total_kosong += 1
                    lokasi_kosong.append(f"{k}{b}")
                    
                matrix_info[(k, b)] = {
                    'exist': True, 'sku_cnt': sku, 'filled': filled,
                    'usable_space': usable_space, 'max_slot': max_slot, 'prods': prods,
                    'df_sub': sub, 'is_match': is_match
                }
        return matrix_info, total_critical, total_kosong, lokasi_kritis, lokasi_kosong

    matrix_info, total_critical, total_kosong, lokasi_kritis, lokasi_kosong = process_matrix_data(df, search_query, product_col)

    @st.dialog("📦 Rincian Detail Rak", width="large")
    def show_rack_detail(k, b, info):
        st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
        c2.metric("Pallet Terisi", f"{info['filled']} / {info['max_slot']}")
        c3.metric("Space Kosong", f"{info['usable_space']} Slot")
        
        st.divider()
        
        if info['sku_cnt'] > 0:
            st.write("### 📋 Ringkasan Produk:")
            rekap = info['df_sub'][product_col].value_counts().reset_index()
            rekap.columns = ['Nama Produk', 'Jumlah Pallet']
            st.dataframe(rekap, use_container_width=True, hide_index=True)
            with st.expander(f"🔍 Lihat Detail Seluruh Slot (1-{info['max_slot']})"):
                 avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', 'No Lot', product_col, 'Status'] if c in info['df_sub'].columns]
                 st.dataframe(info['df_sub'][avail], use_container_width=True, hide_index=True)
        else:
            st.success("✅ Baris ini KOSONG. Siap digunakan untuk Inbound!")

    teks_kritis = ", ".join(lokasi_kritis) if lokasi_kritis else "Semua baris aman."
    teks_kosong = ", ".join(lokasi_kosong) if lokasi_kosong else "Tidak ada yang 100% kosong."

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Total Baris Racking Aktif", "156 Baris")
    col_m2.metric("Baris Status Kritis", f"{total_critical} Baris", help=f"🚨 Kritis:\n\n{teks_kritis}")
    col_m3.metric("Baris Kosong Total", f"{total_kosong} Baris", help=f"✅ Kosong:\n\n{teks_kosong}")
    st.divider()

    dynamic_css = """
    .block-container { max-width: 98% !important; padding-top: 3.5rem !important; padding-bottom: 2rem !important; }
    div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
    div[data-testid="stColumn"] { padding-left: 2px !important; padding-right: 2px !important; }
    div[data-testid="stColumn"]:nth-child(1) { display: flex; align-items: center; justify-content: center; }
    div[class^="st-key-btn_"] button { aspect-ratio: 1/1 !important; width: 100% !important; min-width: 22px !important; padding: 0px !important; margin: 0px !important; border: 1px solid #475569 !important; border-radius: 4px !important; display: flex !important; align-items: center !important; justify-content: center !important; font-size: clamp(10px, 1.2vw, 16px) !important; font-weight: 900 !important; }
    div[class^="st-key-btn_"] button:hover { transform: scale(1.15); border: 2px solid #fff !important; z-index: 10; }
    """

    color_map = {
        'match': {"bg": "#38bdf8", "txt": "#000000", "selectors": []},
        'critical': {"bg": "#ef4444", "txt": "#ffffff", "selectors": []},
        'warning': {"bg": "#fde047", "txt": "#000000", "selectors": []},
        'ideal': {"bg": "#86efac", "txt": "#000000", "selectors": []},
        'empty': {"bg": "#e2e8f0", "txt": "#94a3b8", "selectors": []}
    }

    for k in kolom_list:
        for b in baris_list:
            info = matrix_info.get((k, b))
            if not info or not info['exist']: continue
            sku = info['sku_cnt']
            selector = f".st-key-btn_{k}_{b} button"
            
            if info['is_match']: color_map['match']['selectors'].append(selector)
            elif sku >= 4: color_map['critical']['selectors'].append(selector)
            elif sku == 3: color_map['warning']['selectors'].append(selector)
            elif sku in [1, 2]: color_map['ideal']['selectors'].append(selector)
            else: color_map['empty']['selectors'].append(selector)

    for group in color_map.values():
        if group['selectors']:
            dynamic_css += f"\n{', '.join(group['selectors'])} {{ background-color: {group['bg']} !important; color: {group['txt']} !important; }}"

    st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)

    def render_grid_area(title, start_baris, end_baris):
        st.markdown(f"### {title}")
        subset_baris = list(range(start_baris, end_baris + 1))
        total_kolom = 16  
        
        for k in kolom_list:
            cols = st.columns([0.6] + [1] * total_kolom, gap="small")
            with cols[0]:
                st.markdown(f"<div style='font-size:16px; font-weight:900; color:#cbd5e1;'>{k}</div>", unsafe_allow_html=True)
            for idx, b in enumerate(subset_baris):
                info = matrix_info[(k, b)]
                with cols[idx + 1]:
                    if not info['exist']: st.write("") 
                    else:
                        btn_text = f"{info['sku_cnt']}"
                        if st.button(btn_text, key=f"btn_{k}_{b}", use_container_width=True):
                            show_rack_detail(k, b, info)
                                
        cols_bottom = st.columns([0.6] + [1] * total_kolom, gap="small")
        with cols_bottom[0]: st.write("")
        for idx, b in enumerate(subset_baris):
            with cols_bottom[idx + 1]:
                st.markdown(f"<div style='text-align:center; font-weight:900; color:#0ea5e9; font-size:clamp(10px, 1.2vw, 16px); margin-top:5px;'>{b}</div>", unsafe_allow_html=True)

    render_grid_area("📍 Area 1: Rak Nomor 1 - 16 (Kapasitas: 31 Slot/Baris)", 1, 16)
    st.write("")
    st.divider()
    st.write("")
    render_grid_area("📍 Area 2: Rak Nomor 17 - 28 (Kapasitas: 44 Slot/Baris)", 17, 28)

elif menu == "📝 Form Transaksi":
    # =========================================================================
    # C. HALAMAN 2: FORM TRANSAKSI (MINI WMS) AKTIF PENUH
    # =========================================================================
    st.title("📝 Form Transaksi Gudang")
    st.caption("Catat barang masuk (Inbound) dan barang keluar (Outbound) ke dalam sistem.")
    
    with st.container(border=True):
        st.subheader("Form Data Pallet")
        
        tipe_trx = st.radio("Tipe Pergerakan:", ["INBOUND (Barang Masuk) ⬇️", "OUTBOUND (Barang Keluar) ⬆️"])
        tipe_clean = "INBOUND" if "INBOUND" in tipe_trx else "OUTBOUND"
        
        barang_dipilih = st.selectbox("Nama Barang:", options=daftar_barang)
        rak_tujuan = st.selectbox("Lokasi Rak (Tujuan/Asal):", options=daftar_rak)
        qty = st.number_input("Jumlah Pallet (Qty):", min_value=1, step=1)
        
        submitted = st.button("💾 Simpan Transaksi", use_container_width=True, type="primary")

        if submitted:
            waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_row = pd.DataFrame([{
                "Timestamp": waktu_sekarang,
                "Tipe Transaksi": tipe_clean,
                "Nama Barang": barang_dipilih,
                "Rak": rak_tujuan,
                "Qty": qty
            }])
            
            try:
                log_lama = load_log()
                log_baru = pd.concat([log_lama, new_row], ignore_index=True)
                conn.update(worksheet="Log Transaksi", data=log_baru)
                st.success(f"✅ Transaksi berhasil dicatat! ({tipe_clean} | {qty} Pallet | {barang_dipilih} di Rak {rak_tujuan})")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"❌ Gagal menyimpan transaksi. Pastikan kunci Secrets JSON Anda valid. Error: {e}")

    st.divider()
    st.subheader("📜 Riwayat Transaksi Terbaru")
    log_sekarang = load_log()
    if not log_sekarang.empty:
        st.dataframe(log_sekarang.tail(5).iloc[::-1], use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada transaksi tercatat.")
