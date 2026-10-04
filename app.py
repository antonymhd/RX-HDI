import streamlit as st
import pandas as pd

# 1. Konfigurasi Web
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📦 Visualisasi Grid Racking Gudang (2D Matrix)")
st.caption("Klik pada kotak untuk melihat rincian isi slot pallet.")

# 2. Load Data Master
@st.cache_data(ttl=60)
def load_data():
    file_path = "Racking Pallet Pivoted.xlsx" 
    df = pd.read_excel(file_path, sheet_name="Racking HDI")
    df.columns = df.columns.astype(str).str.strip()
    return df

try:
    df = load_data()
except Exception as e:
    st.error(f"⚠ Gagal memuat data master! Error: {e}")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# 3. Sidebar (DIPERBARUI DENGAN DROPDOWN SELECTBOX)
st.sidebar.header("🔍 Pencarian & Filter")

# Mengambil daftar unik nama produk dari Excel, buang yang kosong (NaN), lalu urutkan abjad
daftar_barang = sorted(df[product_col].dropna().astype(str).unique().tolist())
daftar_pilihan = ["-- Tampilkan Semua --"] + daftar_barang

# Menampilkan Dropdown yang bisa diketik
pilihan_pencarian = st.sidebar.selectbox("Pilih / Ketik Nama Barang:", options=daftar_pilihan)

# Menentukan kata kunci pencarian
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

# 4. Kondisi Rak Fisik
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

# 5. Hitung Data Matriks
def process_matrix_data(df, search_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    matrix_info = {}
    total_critical = total_kosong = 0
    lokasi_kritis = []
    lokasi_kosong = []
    
    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {'exist': False}
                continue
                
            sub = df[(df['Kolom'] == k) & (df['Baris'] == b)]
            prods = sub[prod_col].dropna().unique() if prod_col in sub.columns else []
            sku = len(prods)
            filled = sub['Part Number'].notna().sum() if 'Part Number' in sub.columns else 0
            
            is_match = False
            if search_term and prod_col in sub.columns:
                # Menggunakan regex=False agar kebal terhadap simbol aneh di nama produk
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
                'usable_space': max(0, len(sub) - filled), 'prods': prods,
                'df_sub': sub, 'is_match': is_match
            }
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list, lokasi_kritis, lokasi_kosong

matrix_info, total_critical, total_kosong, kolom_list, baris_list, lokasi_kritis, lokasi_kosong = process_matrix_data(df, search_query, product_col)

# 6. Modal Pop-up (Dialog Detail)
@st.dialog("📦 Rincian Detail Rak", width="large")
def show_rack_detail(k, b, info):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    c2.metric("Pallet Terisi", f"{info['filled']} / 44")
    c3.metric("Space Kosong", f"{info['usable_space']} Slot")
    st.divider()
    
    if info['sku_cnt'] > 0:
        st.write("### 📋 Ringkasan Produk:")
        rekap = info['df_sub'][product_col].value_counts().reset_index()
        rekap.columns = ['Nama Produk', 'Jumlah Pallet']
        st.dataframe(rekap, use_container_width=True, hide_index=True)
        with st.expander("🔍 Lihat Detail Seluruh Slot (1-44)"):
             avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', 'No Lot', product_col, 'Status'] if c in info['df_sub'].columns]
             st.dataframe(info['df_sub'][avail], use_container_width=True, hide_index=True)
    else:
        st.success("✅ Baris ini KOSONG. Siap digunakan untuk Inbound!")

# 7. Dashboard Metrics
teks_kritis = ", ".join(lokasi_kritis) if lokasi_kritis else "Semua baris aman."
teks_kosong = ", ".join(lokasi_kosong) if lokasi_kosong else "Tidak ada yang 100% kosong."

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Total Baris Racking Aktif", "156 Baris")
col_m2.metric("Baris Status Kritis", f"{total_critical} Baris", help=f"🚨 Kritis:\n\n{teks_kritis}")
col_m3.metric("Baris Kosong Total", f"{total_kosong} Baris", help=f"✅ Kosong:\n\n{teks_kosong}")
st.divider()

# =========================================================================
# 8. OPTIMASI CSS (SUPER RINGAN & HEADER TIDAK TERPOTONG)
# =========================================================================
dynamic_css = """
/* Memastikan header atas aman dari bar hitam */
.block-container { 
    max-width: 98% !important; 
    padding-top: 3.5rem !important; 
    padding-bottom: 2rem !important; 
}

/* Mencegah kolom hancur ke bawah di HP */
div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
div[data-testid="stColumn"] { padding-left: 2px !important; padding-right: 2px !important; }

/* Huruf Rak A-G di kiri diselaraskan ke tengah vertikal */
div[data-testid="stColumn"]:nth-child(1) {
    display: flex; align-items: center; justify-content: center;
}

/* Desain Kotak Angka (Aspect Ratio Persegi) */
div[class^="st-key-btn_"] button {
    aspect-ratio: 1/1 !important;
    width: 100% !important;
    min-width: 22px !important;
    padding: 0px !important;
    margin: 0px !important;
    border: 1px solid #475569 !important;
    border-radius: 4px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: clamp(10px, 1.2vw, 16px) !important;
    font-weight: 900 !important;
}
div[class^="st-key-btn_"] button:hover {
    transform: scale(1.15);
    border: 2px solid #fff !important;
    z-index: 10;
}
"""

# OPTIMASI RENDER WARNA (Batch Processing)
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

# =========================================================================
# 9. FUNGSI RENDER GRID AREA
# =========================================================================
def render_grid_area(title, start_baris, end_baris):
    st.markdown(f"### {title}")
    
    subset_baris = list(range(start_baris, end_baris + 1))
    total_kolom = 16  # Kunci agar ukuran kotak antar Area 1 dan Area 2 tetap sama
    
    for k in kolom_list:
        cols = st.columns([0.6] + [1] * total_kolom, gap="small")
        
        with cols[0]:
            st.markdown(f"<div style='font-size:16px; font-weight:900; color:#cbd5e1;'>{k}</div>", unsafe_allow_html=True)
            
        for idx, b in enumerate(subset_baris):
            info = matrix_info[(k, b)]
            
            with cols[idx + 1]:
                if not info['exist']:
                    # MENGHILANGKAN TANDA X (Dibiarkan kosong melompong / negative space)
                    st.write("") 
                else:
                    btn_text = f"{info['sku_cnt']}"
                    if st.button(btn_text, key=f"btn_{k}_{b}", use_container_width=True):
                        show_rack_detail(k, b, info)
                            
    # Render Penomoran Bawah (1-16 / 17-28)
    cols_bottom = st.columns([0.6] + [1] * total_kolom, gap="small")
    with cols_bottom[0]:
        st.write("")
        
    for idx, b in enumerate(subset_baris):
        with cols_bottom[idx + 1]:
            st.markdown(f"<div style='text-align:center; font-weight:900; color:#0ea5e9; font-size:clamp(10px, 1.2vw, 16px); margin-top:5px;'>{b}</div>", unsafe_allow_html=True)

# =========================================================================
# 10. EKSEKUSI PEMBAGIAN 2 AREA RAK
# =========================================================================
render_grid_area("📍 Area 1: Rak Nomor 1 - 16", 1, 16)

st.write("")
st.divider()
st.write("")

render_grid_area("📍 Area 2: Rak Nomor 17 - 28", 17, 28)
