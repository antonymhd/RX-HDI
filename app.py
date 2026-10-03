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

# 3. Sidebar
st.sidebar.header("🔍 Pencarian & Filter")
search_query = st.sidebar.text_input("Cari Nama Barang / Part Number:", "").strip()

st.sidebar.divider()
st.sidebar.header("🎨 Indikator Warna")
st.sidebar.markdown("""
- 🟢 **Hijau (1–2 SKU):** Aman / Ideal
- 🟡 **Kuning (3 SKU):** Warning
- 🔴 **Merah (≥4 SKU):** Kritis (Bercampur)
- ⚪ **Abu-Abu (0 SKU):** Kosong
- 🔵 **Biru:** Hasil Pencarian
""")

# 4. Kondisi Rak Fisik
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

# 5. Hitung Data Matriks & Kumpulkan Lokasi Spesifik
def process_matrix_data(df, search_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    matrix_info = {}
    total_critical = total_kosong = 0
    
    # List untuk menyimpan informasi bubble
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
                is_match = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False).any() or \
                           sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False).any()
            
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

# 7. Dashboard Metrics Atas (DENGAN FITUR BUBBLE TOOLTIP)
teks_kritis = ", ".join(lokasi_kritis) if lokasi_kritis else "Semua baris aman."
teks_kosong = ", ".join(lokasi_kosong) if lokasi_kosong else "Tidak ada yang 100% kosong."

# Ubah dari 4 kolom menjadi 3 kolom
col_m1, col_m2, col_m3 = st.columns(3)

col_m1.metric("Total Baris Racking Aktif", "156 Baris", 
              help="Total ketersediaan blok/baris rak fisik yang ada di dalam layout gudang saat ini.")

col_m2.metric("Baris Status Kritis (≥4 SKU)", f"{total_critical} Baris", 
              help=f"🚨 **Lokasi Rak Bercampur (Perlu Relokasi):**\n\n{teks_kritis}")

col_m3.metric("Baris Kosong Total", f"{total_kosong} Baris", 
              help=f"✅ **Lokasi Siap Pakai (Kosong 100%):**\n\n{teks_kosong}")

st.divider()

# =========================================================================
# 8. SISTEM INJEKSI WARNA BARU & UKURAN IKON DIPERBESAR
# =========================================================================
dynamic_css = """
/* ========================================================================= */
/* TWEAK RESPONSIVE UNTUK MOBILE / HP (ANTI-BERANTAKAN)                      */
/* ========================================================================= */

/* Memaksa baris kolom untuk tetap menyamping dan bisa di-swipe ke kiri/kanan */
div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch !important; /* Animasi scroll halus di iPhone/Android */
    padding-bottom: 8px !important;
}

/* Mempercantik bentuk Scrollbar Horizontal */
div[data-testid="stHorizontalBlock"]::-webkit-scrollbar {
    height: 5px;
}
div[data-testid="stHorizontalBlock"]::-webkit-scrollbar-thumb {
    background-color: #94a3b8;
    border-radius: 10px;
}

/* Mencegah layar HP memaksa kotak-kotak turun ke bawah */
@media (max-width: 768px) {
    div[data-testid="stColumn"] {
        flex: 0 0 auto !important; 
        width: auto !important;
        min-width: 44px !important; /* Mengunci lebar kotak agar tidak gepeng di HP */
    }
    
    /* Menyesuaikan ukuran huruf Rak (A-G) di sebelah kiri saat di HP */
    div[data-testid="stColumn"]:nth-child(1) {
        min-width: 30px !important; 
    }
    div[data-testid="stColumn"]:nth-child(1) h3 {
        font-size: 18px !important;
        margin-top: 10px !important;
    }
}
.block-container { max-width: 98% !important; }

div[class^="st-key-box_"] button {
    aspect-ratio: 1/1 !important;
    width: 100% !important;
    min-width: 40px !important;
    min-height: 40px !important;
    font-size: 20px !important;
    font-weight: 900 !important;
    padding: 0px !important;
    margin: 0px !important;
    border: 1px solid #475569 !important;
    border-radius: 6px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
div[class^="st-key-box_"] button:hover {
    transform: scale(1.15);
    border: 2px solid #000 !important;
    z-index: 10;
}
div[data-testid="stColumn"] { padding-left: 0.2rem !important; padding-right: 0.2rem !important; }
"""

# Menyuntikkan warna secara spesifik ke masing-masing kotak
for k in kolom_list:
    for b in baris_list:
        info = matrix_info.get((k, b))
        if not info or not info['exist']: continue
        
        sku = info['sku_cnt']
        if info['is_match']: bg, txt = "#38bdf8", "#000000"       
        elif sku >= 4: bg, txt = "#ef4444", "#ffffff"             
        elif sku == 3: bg, txt = "#fde047", "#000000"             
        elif sku in [1, 2]: bg, txt = "#86efac", "#000000"        
        else: bg, txt = "#e2e8f0", "#94a3b8"                      
        
        dynamic_css += f"\n.st-key-box_{k}_{b} button {{ background-color: {bg} !important; color: {txt} !important; }}"

st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)

# =========================================================================
# 9. RENDER GRID (KOLOM & TOMBOL)
# =========================================================================
for k in kolom_list:
    cols = st.columns([0.6] + [1] * 28, gap="small")
    cols[0].markdown(f"### **{k}**") 
    
    for idx, b in enumerate(baris_list):
        info = matrix_info[(k, b)]
        
        if not info['exist']:
            cols[idx + 1].markdown("<div style='text-align:center; color:#ef4444; font-size:16px; margin-top:10px;'>❌</div>", unsafe_allow_html=True)
            continue
            
        with cols[idx + 1]:
            with st.container(key=f"box_{k}_{b}"):
                btn_text = f"{info['sku_cnt']}"
                if st.button(btn_text, key=f"btn_{k}_{b}", use_container_width=True):
                    show_rack_detail(k, b, info)

# 10. Baris Nomor (1-28) di Bawah
cols_bottom = st.columns([0.6] + [1] * 28, gap="small")
cols_bottom[0].write("")
for idx, b in enumerate(baris_list):
    cols_bottom[idx + 1].markdown(f"<div style='text-align:center; font-weight:900; color:#0ea5e9; font-size:18px; margin-top:5px;'>{b}</div>", unsafe_allow_html=True)
