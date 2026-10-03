import streamlit as st
import pandas as pd

# 1. Konfigurasi Halaman Web (Buat lebih lebar agar 28 kotak muat)
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📦 Visualisasi Grid Racking Gudang (2D Matrix)")
st.caption("Kotak berbentuk persegi mewakili jumlah SKU pallet. Klik kotak mana saja untuk membuka rincian slot.")

# 2. Load Data Master Excel
@st.cache_data(ttl=60)
def load_data():
    file_path = "Racking Pallet Pivoted.xlsx" 
    df = pd.read_excel(file_path, sheet_name="Racking HDI")
    df.columns = df.columns.astype(str).str.strip()
    return df

try:
    df = load_data()
except Exception as e:
    st.error(f"⚠️ Gagal memuat data master. Pastikan file Excel tersedia! Error: {e}")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# 3. Sidebar
st.sidebar.header("🔍 Pencarian & Filter")
search_query = st.sidebar.text_input("Cari Nama Barang / Part Number:", "").strip()

st.sidebar.divider()
st.sidebar.header("🎨 Indikator Warna")
st.sidebar.markdown("""
- 🟢 **Hijau (1–2 SKU):** Aman
- 🟡 **Kuning (3 SKU):** Warning
- 🔴 **Merah (≥4 SKU):** Kritis
- ⚪ **Abu-Abu (0 SKU):** Kosong
- 🔵 **Biru:** Hasil Pencarian
""")

# 4. Fungsi Cek Fisik Rak
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

# 5. Kalkulasi Data Matriks
def process_matrix_data(df, search_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    
    matrix_info = {}
    total_critical = total_kosong = 0
    
    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {'exist': False}
                continue
                
            sub = df[(df['Kolom'] == k) & (df['Baris'] == b)]
            prods = sub[prod_col].dropna().unique() if prod_col in sub.columns else []
            sku_cnt = len(prods)
            filled = sub['Part Number'].notna().sum() if 'Part Number' in sub.columns else 0
            
            is_match = False
            if search_term and prod_col in sub.columns:
                is_match = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False).any() or \
                           sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False).any()
            
            if sku_cnt >= 4: total_critical += 1
            elif sku_cnt == 0: total_kosong += 1
                
            matrix_info[(k, b)] = {
                'exist': True, 'sku_cnt': sku_cnt, 'filled': filled,
                'usable_space': max(0, len(sub) - filled), 'prods': prods,
                'df_sub': sub, 'is_match': is_match
            }
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list

matrix_info, total_critical, total_kosong, kolom_list, baris_list = process_matrix_data(df, search_query, product_col)

# 6. Modal Pop-up Dialog
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
    else:
        st.success("✅ Baris ini KOSONG. Siap digunakan untuk Inbound!")

# 7. Metric Dashboard (Ini adalah Blok Horizontal Ke-1)
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("Total Baris Racking Aktif", "156 Baris")
col_m2.metric("Baris Status Kritis (≥4 SKU)", f"{total_critical} Baris")
col_m3.metric("Baris Kosong Total", f"{total_kosong} Baris")
col_m4.metric("Ketersediaan Space", "Siap Inbound" if total_kosong > 0 else "Penuh")

st.divider()

# =========================================================================
# 8. HACK CSS: Generate Warna Dinamis & Kotak Persegi (Aspect Ratio 1:1)
# =========================================================================
grid_css = """
/* Melebarkan area kerja agar 28 kotak muat tanpa terpotong */
.block-container {
    max-width: 98% !important;
    padding-top: 1rem !important;
}

/* Memaksa tombol Streamlit menjadi kotak persegi sempurna */
div[data-testid="stHorizontalBlock"] button {
    aspect-ratio: 1 / 1 !important; 
    height: auto !important; 
    min-height: 0px !important;
    width: 100% !important;
    padding: 0px !important;
    margin: 0px !important;
    border-radius: 4px !important;
    font-weight: 900 !important;
    font-size: 15px !important;
    border: 1px solid #94a3b8 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: transform 0.1s ease;
}
div[data-testid="stHorizontalBlock"] button:hover {
    transform: scale(1.15);
    border: 2px solid #000000 !important;
    z-index: 99;
}
"""

# Menyuntikkan warna spesifik ke koordinat kolom & baris di DOM Streamlit
base_row_idx = 2 # Blok grid dimulai setelah blok metric di atas
for r_idx, k in enumerate(kolom_list):
    row_idx = base_row_idx + r_idx
    for c_idx, b in enumerate(baris_list):
        info = matrix_info[(k, b)]
        if not info['exist']: continue
        
        sku = info['sku_cnt']
        col_idx = c_idx + 2 # +2 karena index ke-1 dipakai huruf rak (A-G)
        
        if info['is_match']: bg, txt = "#38bdf8", "#000000" # Biru Search
        elif sku >= 4: bg, txt = "#ef4444", "#ffffff"       # Merah
        elif sku == 3: bg, txt = "#fef08a", "#000000"       # Kuning
        elif sku in [1, 2]: bg, txt = "#bbf7d0", "#000000"  # Hijau
        else: bg, txt = "#f1f5f9", "#94a3b8"                # Abu-abu
            
        grid_css += f"""
        div[data-testid="stHorizontalBlock"]:nth-of-type({row_idx}) div[data-testid="stColumn"]:nth-child({col_idx}) button {{
            background-color: {bg} !important;
        }}
        div[data-testid="stHorizontalBlock"]:nth-of-type({row_idx}) div[data-testid="stColumn"]:nth-child({col_idx}) button p {{
            color: {txt} !important;
        }}
        """

st.markdown(f"<style>{grid_css}</style>", unsafe_allow_html=True)

# =========================================================================
# 9. Render Matriks 2D
# =========================================================================
for k in kolom_list:
    cols = st.columns([0.6] + [1] * 28)
    cols[0].markdown(f"### **{k}**")
    
    for idx, b in enumerate(baris_list):
        info = matrix_info[(k, b)]
        
        if not info['exist']:
            cols[idx + 1].markdown("<div style='text-align:center; color:#ef4444; font-size:12px; margin-top:8px;'>❌</div>", unsafe_allow_html=True)
            continue
            
        # Tombol akan merender angka variasi SKU di tengah kotak
        btn_text = f"{info['sku_cnt']}"
        
        with cols[idx + 1]:
            if st.button(btn_text, key=f"btn_{k}_{b}"):
                show_rack_detail(k, b, info)

# 10. Baris Nomor (1-28) Bawah
cols_bottom = st.columns([0.6] + [1] * 28)
cols_bottom[0].write("")
for idx, b in enumerate(baris_list):
    cols_bottom[idx + 1].markdown(f"<div style='text-align:center; font-weight:bold; color:#38bdf8; font-size:15px; margin-top:5px;'>{b}</div>", unsafe_allow_html=True)
