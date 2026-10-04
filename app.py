import streamlit as st
import pandas as pd
import json

# 1. Konfigurasi Web
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.title("📦 Visualisasi Grid Racking Gudang (2D Matrix)")
st.caption("Tampilan layaknya Tabel Periodik. Akan mengecil otomatis agar muat di layar HP tanpa perlu scroll.")

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
st.sidebar.markdown("""
🎨 **Indikator Warna**
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

# 6. Modal Pop-up
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

# 7. Dashboard Metrics
teks_kritis = ", ".join(lokasi_kritis) if lokasi_kritis else "Aman."
teks_kosong = ", ".join(lokasi_kosong) if lokasi_kosong else "Tidak ada yang kosong."

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Total Baris Racking Aktif", "156 Baris")
col_m2.metric("Baris Status Kritis", f"{total_critical} Baris", help=f"🚨 Kritis:\n{teks_kritis}")
col_m3.metric("Baris Kosong Total", f"{total_kosong} Baris", help=f"✅ Kosong:\n{teks_kosong}")
st.divider()

# =========================================================================
# 8. SISTEM TABEL PERIODIK DENGAN HORIZONTAL SCROLL (UNTUK HP)
# =========================================================================
st.markdown("""
<style>
/* Melebarkan layar penuh dan menghilangkan padding bawaan Streamlit yang berlebihan */
.block-container { 
    max-width: 100% !important; 
    padding-top: 1rem !important; 
    padding-left: 0.5rem !important; 
    padding-right: 0.5rem !important;
}

/* WADAH UTAMA: Memaksa Scroll Horizontal di Layar Kecil */
.scroll-wrapper {
    width: 100%;
    overflow-x: auto; /* Mengaktifkan scroll kiri-kanan jika konten terlalu lebar */
    overflow-y: hidden; /* Mencegah scroll atas-bawah di dalam tabel */
    -webkit-overflow-scrolling: touch; /* Efek licin/halus saat digeser pakai jari di HP */
    padding-bottom: 10px;
}

/* Mempercantik Scrollbar di HP/Browser */
.scroll-wrapper::-webkit-scrollbar { height: 8px; }
.scroll-wrapper::-webkit-scrollbar-thumb { background-color: #94a3b8; border-radius: 4px; }

/* CSS Grid Rigid (Peta Denah yang Tidak Bisa Dihancurkan) */
.periodic-grid {
    display: grid;
    grid-template-columns: 30px repeat(28, minmax(35px, 1fr)); /* Lebar Minimal Kotak = 35px */
    gap: 4px;
    min-width: 1100px; /* KUNCI UTAMA: Memaksa Grid tetap lebar, memicu Scroll di HP */
    margin-bottom: 5px;
}

/* Huruf Rak (A-G) di sebelah kiri */
.row-label {
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 900;
    font-size: 18px;
    color: #cbd5e1;
}

/* Memodifikasi semua tombol st.button di dalam grid */
.periodic-grid button {
    aspect-ratio: 1/1 !important;
    width: 100% !important;
    min-height: 35px !important; /* Tinggi kotak tetap proporsional */
    padding: 0px !important;
    margin: 0px !important;
    border-radius: 4px !important;
    border: 1px solid #475569 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-weight: 900 !important;
    font-size: 16px !important; /* Font tetap besar */
}
.periodic-grid button:hover {
    border: 2px solid #fff !important;
    transform: scale(1.1);
    z-index: 99;
}

/* Penomoran baris 1-28 di bawah grid */
.col-label {
    display: flex;
    justify-content: center;
    font-weight: 900;
    font-size: 14px;
    color: #38bdf8;
    margin-top: 5px;
}
</style>
""", unsafe_allow_html=True)

# Membuat String CSS Dinamis untuk Warna Kotak
color_css = ""

# =========================================================================
# 9. RENDER GRID (BUNGKUS DENGAN WRAPPER SCROLL)
# =========================================================================

# Buka Wadah Scroll Horizontal
st.markdown('<div class="scroll-wrapper">', unsafe_allow_html=True)

for k in kolom_list:
    # Buka Baris Grid
    st.markdown('<div class="periodic-grid">', unsafe_allow_html=True)
    
    # Render Huruf Rak A-G
    st.markdown(f'<div class="row-label">{k}</div>', unsafe_allow_html=True)
    
    # 28 Kolom Streamlit untuk Tombol
    cols = st.columns(28) 
    
    for idx, b in enumerate(baris_list):
        info = matrix_info[(k, b)]
        
        with cols[idx]:
            if not info['exist']:
                st.markdown("<div style='text-align:center; color:#ef4444; font-size:16px; padding-top:20%;'>❌</div>", unsafe_allow_html=True)
            else:
                sku = info['sku_cnt']
                # Pewarnaan
                if info['is_match']: bg, txt = "#38bdf8", "#000000"
                elif sku >= 4: bg, txt = "#ef4444", "#ffffff"
                elif sku == 3: bg, txt = "#fde047", "#000000"
                elif sku in [1, 2]: bg, txt = "#86efac", "#000000"
                else: bg, txt = "#e2e8f0", "#94a3b8"
                
                color_css += f".st-key-btn_{k}_{b} button {{ background-color: {bg} !important; color: {txt} !important; }}\n"
                
                # Render Tombol
                if st.button(str(sku), key=f"btn_{k}_{b}", use_container_width=True):
                    show_rack_detail(k, b, info)
                    
    # Tutup Baris Grid
    st.markdown('</div>', unsafe_allow_html=True)

# Render Penomoran Bawah (1-28) di dalam Grid Terakhir
st.markdown('<div class="periodic-grid">', unsafe_allow_html=True)
st.markdown('<div></div>', unsafe_allow_html=True) # Spasi kosong untuk huruf
for b in baris_list:
    st.markdown(f'<div class="col-label">{b}</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# Tutup Wadah Scroll Horizontal
st.markdown('</div>', unsafe_allow_html=True)

# 10. Terapkan Warna CSS
st.markdown(f"<style>{color_css}</style>", unsafe_allow_html=True)

# 10. Terapkan Warna CSS
st.markdown(f"<style>{color_css}</style>", unsafe_allow_html=True)

# 11. Render Penomoran Bawah (1-28)
st.markdown('<div class="col-label-grid">', unsafe_allow_html=True)
st.markdown('<div></div>', unsafe_allow_html=True) # Spasi kosong untuk huruf
for b in baris_list:
    st.markdown(f'<div class="col-label">{b}</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)
