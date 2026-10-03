import streamlit as st
import pandas as pd

# 1. Konfigurasi Halaman Web
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide"
)

# 2. Custom CSS untuk Membuat Grid Kotak Presisi Berwarna Solid (Persis Excel/WMS)
st.markdown("""
<style>
    /* Styling Container Grid Utama */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
    }
    
    /* Custom Styling Tombol Rak Matriks */
    div.stButton > button {
        width: 100% !important;
        height: 42px !important;
        font-size: 15px !important;
        font-weight: 900 !important;
        border-radius: 4px !important;
        padding: 0px !important;
        margin: 0px !important;
        border: 1px solid #1e293b !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        transition: transform 0.1s ease;
    }
    div.stButton > button:hover {
        transform: scale(1.08);
        border: 2px solid #ffffff !important;
        z-index: 10;
    }

    /* Warna Background Solid Berdasarkan Indikator Status Rak */
    /* OK (1-2 SKU) -> Hijau Soft */
    .btn-ok div.stButton > button {
        background-color: #22c55e !important;
        color: #000000 !important;
    }
    /* WARNING (3 SKU) -> Kuning Oranye */
    .btn-warning div.stButton > button {
        background-color: #f59e0b !important;
        color: #000000 !important;
    }
    /* CRITICAL (>=4 SKU) -> Merah Menyala */
    .btn-critical div.stButton > button {
        background-color: #ef4444 !important;
        color: #ffffff !important;
    }
    /* EMPTY (0 SKU) -> Abu-abu */
    .btn-empty div.stButton > button {
        background-color: #e2e8f0 !important;
        color: #64748b !important;
    }
    /* MATCH (Hasil Cari) -> Biru */
    .btn-match div.stButton > button {
        background-color: #0284c7 !important;
        color: #ffffff !important;
    }

    /* Header Angka Baris 1-28 di Bagian Bawah Grid */
    .baris-header {
        font-size: 15px !important;
        font-weight: bold !important;
        text-align: center !important;
        color: #38bdf8 !important;
        margin-top: 10px !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 Visualisasi Grid Racking Gudang (2D Matrix)")
st.caption("Setiap sel menampilkan jumlah variasi SKU/Barang. Klik kotak mana saja untuk membuka rincian slot pallet.")

# 3. Load Data Master Excel
@st.cache_data(ttl=60)
def load_data():
    file_path = "Racking Pallet Pivoted.xlsx" 
    df = pd.read_excel(file_path, sheet_name="Racking HDI")
    df.columns = df.columns.astype(str).str.strip()
    return df

try:
    df = load_data()
except Exception as e:
    st.error(f"⚠️ Gagal memuat data master. Pastikan file Excel tersedia di repository! Error: {e}")
    st.stop()

# Deteksi otomatis nama kolom produk
product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# 4. Sidebar Filter & Legenda
st.sidebar.header("🔍 Pencarian & Filter")
search_query = st.sidebar.text_input("Cari Nama Barang / Part Number:", "").strip()

st.sidebar.divider()
st.sidebar.header("🎨 Indikator Warna & Pallet")
st.sidebar.markdown("""
- 🟢 **Hijau (1–2 SKU):** Ideal / Sesuai SOP
- 🟡 **Kuning (3 SKU):** Warning / Perlu Diatur
- 🔴 **Merah (≥4 SKU):** Kritis / Produk Bercampur
- ⚪ **Abu-Abu (0 SKU):** Baris Kosong Total
- 🔵 **Biru:** Hasil Pencarian Produk
- ❌ **Merah Silang:** Area Tidak Ada Rak
""")

# 5. Cek Ketersediaan Rak Fisik (Sesuai Layout Gudang Real)
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5:
        return False
    if kolom == 'G' and baris < 17:
        return False
    return True

# 6. Pemrosesan Data Matriks
def process_matrix_data(df, search_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    
    matrix_info = {}
    total_critical = 0
    total_kosong = 0
    
    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {'exist': False}
                continue
                
            sub = df[(df['Kolom'] == k) & (df['Baris'] == b)]
            
            prods = sub[prod_col].dropna().unique() if prod_col in sub.columns else []
            sku_cnt = len(prods)
            filled = sub['Part Number'].notna().sum() if 'Part Number' in sub.columns else 0
            empty_slots = len(sub) - filled
            usable_space = 0 if empty_slots <= 1 else empty_slots
            
            is_match = False
            if search_term and prod_col in sub.columns:
                is_match = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False).any() or \
                           sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False).any()
            
            if sku_cnt >= 4:
                total_critical += 1
            elif sku_cnt == 0:
                total_kosong += 1
                
            matrix_info[(k, b)] = {
                'exist': True,
                'sku_cnt': sku_cnt,
                'filled': filled,
                'usable_space': usable_space,
                'prods': prods,
                'df_sub': sub,
                'is_match': is_match
            }
            
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list

matrix_info, total_critical, total_kosong, kolom_list, baris_list = process_matrix_data(df, search_query, product_col)

# 7. Modal Pop-up Dialog untuk Menampilkan Detail Saat Sel Diklik
@st.dialog("📦 Rincian Detail Rak", width="large")
def show_rack_detail(k, b, info):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Jumlah Variasi SKU", f"{info['sku_cnt']} SKU")
    col_b.metric("Pallet Terisi", f"{info['filled']} / 44 Slot")
    col_c.metric("Space Kosong", f"{info['usable_space']} Slot")
    st.divider()
    
    if info['sku_cnt'] > 0:
        st.write("### 📋 Ringkasan Produk & Jumlah Pallet:")
        rekap = info['df_sub'][product_col].value_counts().reset_index()
        rekap.columns = ['Nama Produk', 'Jumlah Pallet']
        st.dataframe(rekap, use_container_width=True, hide_index=True)
        
        with st.expander("🔍 Detail Seluruh Slot Pallet (1–44)"):
            available_cols = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', 'No Lot', product_col, 'Status'] if c in info['df_sub'].columns]
            st.dataframe(info['df_sub'][available_cols], use_container_width=True, hide_index=True)
    else:
        st.success("✅ Baris ini 100% KOSONG. Siap digunakan untuk lokasi penempatan Inbound!")

# 8. Metric Cards Dashboard Upper Section
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("Total Baris Racking Aktif", "156 Baris")
col_m2.metric("Baris Status Kritis (≥4 SKU)", f"{total_critical} Baris", delta_color="inverse")
col_m3.metric("Baris Kosong Total", f"{total_kosong} Baris")
col_m4.metric("Ketersediaan Space", "Siap Inbound" if total_kosong > 0 else "Penuh")

st.divider()

# 9. Render Grid Matriks 2D (G-A x 1-28) dengan Warna Solid Presisi
for k in kolom_list:
    cols = st.columns([0.6] + [1] * 28)
    cols[0].markdown(f"### **{k}**") # Label Kolom Rak G - A
    
    for idx, b in enumerate(baris_list):
        info = matrix_info[(k, b)]
        
        # Sembunyikan area yang tidak ada raknya secara fisik
        if not info['exist']:
            cols[idx + 1].markdown("<div style='text-align:center; color:#ef4444; font-size:14px; font-weight:bold; margin-top:8px;'>❌</div>", unsafe_allow_html=True)
            continue
            
        sku_cnt = info['sku_cnt']
        is_match = info['is_match']
        
        # Tentukan Teks Label Angka & Class Warna Solid
        if is_match:
            btn_text = f"{sku_cnt}"
            css_class = "btn-match"
        elif sku_cnt >= 4:
            btn_text = f"{sku_cnt}"
            css_class = "btn-critical"
        elif sku_cnt == 3:
            btn_text = f"3"
            css_class = "btn-warning"
        elif sku_cnt in [1, 2]:
            btn_text = f"{sku_cnt}"
            css_class = "btn-ok"
        else:
            btn_text = "0"
            css_class = "btn-empty"
            
        # Render Tombol Warna Solid Interaktif
        with cols[idx + 1]:
            st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
            if st.button(btn_text, key=f"btn_{k}_{b}"):
                show_rack_detail(k, b, info)
            st.markdown('</div>', unsafe_allow_html=True)

# 10. Header Angka Baris (1-28) di Bawah Grid
cols_bottom = st.columns([0.6] + [1] * 28)
cols_bottom[0].write("")
for idx, b in enumerate(baris_list):
    cols_bottom[idx + 1].markdown(f'<div class="baris-header">{b}</div>', unsafe_allow_html=True)
