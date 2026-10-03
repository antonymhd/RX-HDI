import streamlit as st
import pandas as pd

# Konfigurasi Halaman Web
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide"
)

# Custom Styling CSS agar tombol berbentuk badge rapi & berwarna
st.markdown("""
<style>
    /* Styling Tombol Popover Grid */
    div[data-testid="stPopover"] > button {
        width: 100% !important;
        height: 42px !important;
        font-weight: bold !important;
        font-size: 11px !important;
        padding: 0px !important;
        border-radius: 6px !important;
        border: 1px solid #d0d7de !important;
        white-space: nowrap !important;
    }
    
    /* Menghilangkan panah dropdown bawaan st.popover */
    div[data-testid="stPopover"] span[data-testid="stIcon"] {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 Visualisasi Grid Racking Gudang (2D Matrix)")
st.caption("Klik pada kotak koordinat rak untuk melihat detail slot pallet (1-44) dan produk di dalamnya.")

# Function Load Data Excel
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

# Deteksi otomatis nama kolom produk
product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# Filter & Search Sidebar
st.sidebar.header("🔍 Pencarian & Filter")
search_query = st.sidebar.text_input("Cari Nama Barang / Part Number:", "").strip()

st.sidebar.divider()
st.sidebar.header("🎨 Indikator Warna Status")
st.sidebar.markdown("""
- 🟢 **Hijau (1–2 SKU):** Ideal / Sesuai SOP
- 🟡 **Kuning (3 SKU):** Warning / Perlu Diatur
- 🔴 **Merah (≥4 SKU):** Kritis / Produk Bercampur
- ⚪ **Abu-Abu (0 SKU):** Baris Kosong Total
- 🔵 **Biru:** Hasil Pencarian Produk
- ⬛ **Satu Strip (-):** Area Tidak Ada Rak
""")

# Fungsi untuk memeriksa apakah rak tersedia secara fisik
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5:
        return False
    if kolom == 'G' and baris < 17:
        return False
    return True

# Menghitung Ringkasan Matriks Gudang
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
            
            # Match search
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

# Metric Summary Cards
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("Total Baris Racking Aktif", "156 Baris")
col_m2.metric("Baris Status Kritis (≥4 SKU)", f"{total_critical} Baris", delta_color="inverse")
col_m3.metric("Baris Kosong Total", f"{total_kosong} Baris")
col_m4.metric("Ketersediaan Space", "Siap Inbound" if total_kosong > 0 else "Penuh")

st.divider()

# Render Grid Matriks 2D (Kolom G-A vs Baris 1-28)
for k in kolom_list:
    cols = st.columns([0.6] + [1] * 28)
    cols[0].markdown(f"### **{k}**") # Label Kolom Racking G-A
    
    for idx, b in enumerate(baris_list):
        info = matrix_info[(k, b)]
        
        # Area yang tidak ada rak fisiknya
        if not info['exist']:
            cols[idx + 1].caption("❌")
            continue
            
        sku_cnt = info['sku_cnt']
        is_match = info['is_match']
        
        # Tentukan Teks & Indikator Warna Tombol
        if is_match:
            btn_label = f"🔵 {sku_cnt} SKU"
        elif sku_cnt >= 4:
            btn_label = f"🔴 {sku_cnt} SKU"
        elif sku_cnt == 3:
            btn_label = f"🟡 3 SKU"
        elif sku_cnt in [1, 2]:
            btn_label = f"🟢 {sku_cnt} SKU"
        else:
            btn_label = f"⚪ Kosong"
            
        # Popover Detail saat Sel Diklik
        with cols[idx + 1]:
            with st.popover(btn_label, use_container_width=True):
                st.subheader(f"📍 Location: Racking {k} - Baris {b}")
                st.write(f"**Variasi SKU:** {sku_cnt} Jenis | **Terisi:** {info['filled']} Pallet | **Space Kosong:** {info['usable_space']} Slot")
                st.divider()
                
                if sku_cnt > 0:
                    st.write("**Ringkasan Barang di Baris Ini:**")
                    rekap = info['df_sub'][product_col].value_counts().reset_index()
                    rekap.columns = ['Nama Produk', 'Jumlah Pallet']
                    st.dataframe(rekap, use_container_width=True, hide_index=True)
                    
                    with st.expander("📋 Rincian Slot Pallet (1–44)"):
                        available_cols = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', 'No Lot', product_col, 'Status'] if c in info['df_sub'].columns]
                        st.dataframe(
                            info['df_sub'][available_cols],
                            use_container_width=True,
                            hide_index=True
                        )
                else:
                    st.success("✅ Baris ini 100% KOSONG. Boleh digunakan untuk penempatan Inbound!")

# Label Nomor Baris (1-28) di Bawah Grid
cols_bottom = st.columns([0.6] + [1] * 28)
for idx, b in enumerate(baris_list):
    cols_bottom[idx + 1].caption(f"**{b}**")
