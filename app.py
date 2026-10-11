import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import time
import re

# ==========================================================
# 1. KONFIGURASI WEB & DATABASE
# ==========================================================
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 💡 NAMA DATABASE
NAMA_DATABASE = 'uji_coba_rak'

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==========================================================
# 2. SIDEBAR: REFRESH & AKSES ADMIN
# ==========================================================
st.sidebar.header("🔄 Muat Ulang")
if st.sidebar.button("Refresh Layar Visualisasi", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.header("🔐 Akses Khusus Admin")
st.sidebar.caption("Masukkan kunci untuk memunculkan menu Update/Hapus data master.")

KUNCI_RAHASIA = "admin123"
kunci_input = st.sidebar.text_input("Kunci Rahasia:", type="password")

if kunci_input == KUNCI_RAHASIA:
    st.sidebar.success("✅ Akses Diberikan")
    
    st.sidebar.divider()
    st.sidebar.subheader("📤 Update Data Harian (Master CSV)")
    uploaded_file = st.sidebar.file_uploader("Upload File Stok (.csv)", type=["csv"])

    if uploaded_file is not None:
        if st.sidebar.button("🚀 Sinkronisasi ke Firebase", use_container_width=True, type="primary"):
            with st.spinner("Membungkus dan mengirim data dalam hitungan detik..."):
                try:
                    try:
                        df_upload = pd.read_csv(uploaded_file, sep=";")
                    except Exception:
                        uploaded_file.seek(0)
                        df_upload = pd.read_csv(uploaded_file, sep=",")
                    
                    df_upload.columns = df_upload.columns.str.replace('\ufeff', '').str.strip()
                    
                    if 'Kolom' in df_upload.columns:
                        batch = db.batch()
                        for col_name, group in df_upload.groupby('Kolom'):
                            if pd.notna(col_name) and str(col_name).strip() != "":
                                doc_id = f"Kolom_{str(col_name).strip()}"
                                doc_ref = db.collection(NAMA_DATABASE).document(doc_id)
                                
                                records = group.to_dict(orient='records')
                                clean_records = []
                                for r in records:
                                    clean_r = {str(k): (v if pd.notna(v) else "") for k, v in r.items()}
                                    clean_records.append(clean_r)
                                    
                                batch.set(doc_ref, {'data': clean_records})
                                
                        batch.commit()
                        st.sidebar.success("✅ Seluruh data berhasil di-update seketika!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.sidebar.error("Format CSV salah: Tidak ada header 'Kolom'")
                except Exception as e:
                    st.sidebar.error(f"Gagal mengunggah data: {e}")

    st.sidebar.divider()
    st.sidebar.subheader("⚠️ Zona Bahaya")
    if st.sidebar.button("🗑️ Hapus Semua Data", type="primary", use_container_width=True):
        with st.spinner("Menyapu bersih data..."):
            try:
                docs = db.collection(NAMA_DATABASE).stream()
                batch = db.batch()
                for doc in docs:
                    batch.delete(doc.reference)
                batch.commit()
                st.sidebar.success("✅ Data berhasil dihapus!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Gagal menghapus: {e}")

elif kunci_input != "":
    st.sidebar.error("❌ Kunci salah.")

st.sidebar.divider()

# ==========================================================
# 3. KONTEN UTAMA: JUDUL & LOAD DATA
# ==========================================================
st.title("📦 Visualisasi Grid Racking Gudang (WMS)")
st.caption(f"Mode Terhubung. Menampilkan data real-time dari database: {NAMA_DATABASE}")

@st.cache_data(ttl=10)
def load_data_from_firebase():
    try:
        docs = db.collection(NAMA_DATABASE).stream()
        all_data = []
        for doc in docs:
            doc_data = doc.to_dict()
            if 'data' in doc_data:
                all_data.extend(doc_data['data'])
                
        if all_data:
            df = pd.DataFrame(all_data)
            for col in ['Baris', 'Pallet Ke']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            for col in ['In', 'Out', 'Sisa']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"🚨 **Gagal memuat data dari Firebase.** Detail Error: {e}")
        return None

df = load_data_from_firebase()

if df is None:
    st.stop() 
elif df.empty:
    st.info("Data visualisasi masih kosong. Silakan gunakan WMS Transaksi untuk melakukan Inbound data.")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# ==========================================================
# 4. SIDEBAR: PENCARIAN & FILTER
# ==========================================================
st.sidebar.header("🔍 Pencarian & Filter")
if product_col in df.columns:
    daftar_barang = sorted(df[df[product_col].astype(str).str.strip() != ""][product_col].dropna().astype(str).unique().tolist())
else:
    daftar_barang = []
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

# ==========================================================
# 5. LOGIKA MATRIKS & KAPASITAS DINAMIS
# ==========================================================
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

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
                
            sub = df[(df['Kolom'] == k) & (float(b) == pd.to_numeric(df['Baris'], errors='coerce'))]
            
            is_all_box = False
            if 'Part Number' in sub.columns:
                part_nums = sub['Part Number'].dropna().astype(str).str.strip().str.upper()
                if not part_nums.empty:
                    is_all_box = part_nums.str.endswith(('D', 'G')).all()
            
            if is_all_box:
                max_slot = 32 if b <= 16 else 46
            else:
                max_slot = 31 if b <= 16 else 44
                
            if 'Pallet Ke' in sub.columns and not sub.empty:
                actual_max = pd.to_numeric(sub['Pallet Ke'], errors='coerce').max()
                if pd.notna(actual_max) and actual_max > max_slot:
                    max_slot = int(actual_max)
                    
            if len(sub) > max_slot:
                sub = sub.head(max_slot)
                
            prods = sub[sub[prod_col].astype(str).str.strip() != ""][prod_col].unique() if prod_col in sub.columns else []
            sku = len(prods)
            filled = sub['Part Number'].apply(lambda x: str(x).strip() != "" and pd.notna(x)).sum() if 'Part Number' in sub.columns else 0
            
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
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list, lokasi_kritis, lokasi_kosong

matrix_info, total_critical, total_kosong, kolom_list, baris_list, lokasi_kritis, lokasi_kosong = process_matrix_data(df, search_query, product_col)

# ==========================================================
# 6. MODAL POP-UP (DETAIL PALLET & KONVERSI KEMASAN BOX/SAK)
# ==========================================================
@st.dialog("📦 Rincian Detail Rak & Konversi Stok", width="large")
def show_rack_detail(k, b, info):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    c2.metric("Slot Fisik Terpakai", f"{info['filled']} / {info['max_slot']}")
    c3.metric("Space Kosong", f"{info['usable_space']} Slot")
    
    st.divider()
    
    if info['sku_cnt'] > 0:
        # Buka Master Produk
        try:
            try:
                df_master = pd.read_csv("Master_Produk.csv", sep=";")
            except:
                df_master = pd.read_csv("Master_Produk.csv", sep=",")
        except FileNotFoundError:
            df_master = pd.DataFrame()

        st.write("### 📋 Ringkasan & Konversi Kuantitas:")
        df_terisi = info['df_sub'][info['df_sub'][product_col].astype(str).str.strip() != ""]
        
        rekap_data = []
        for prod in df_terisi[product_col].unique():
            df_prod = df_terisi[df_terisi[product_col] == prod]
            
            part_num = str(df_prod['Part Number'].iloc[0]).strip() if 'Part Number' in df_prod.columns else ""
            jml_utuh = df_prod[~df_prod['Keterangan'].astype(str).str.contains('Pecahan', case=False, na=False)].shape[0]
            
            # Ambil nilai pecahan dari keterangan
            pecahan_rows = df_prod[df_prod['Keterangan'].astype(str).str.contains('Pecahan', case=False, na=False)]
            val_pecahan = 0
            if not pecahan_rows.empty:
                ket_str = str(pecahan_rows['Keterangan'].iloc[0])
                numbers = re.findall(r'\d+', ket_str)
                if numbers:
                    val_pecahan = int(numbers[0])

            # Ambil data dari Master Produk
            isi_pallet_pcs = 0
            pcs_per_box = 0
            pcs_per_sak = 0
            
            if not df_master.empty and part_num in df_master['Part Number'].astype(str).values:
                m_row = df_master[df_master['Part Number'].astype(str) == part_num].iloc[0]
                isi_pallet_pcs = pd.to_numeric(m_row.get('Isi 1 Pallet (pcs)', 0), errors='coerce') or 0
                pcs_per_box = pd.to_numeric(m_row.get('Box / Pallet', 0), errors='coerce') or 0
                pcs_per_sak = pd.to_numeric(m_row.get('Sac / Pallet', 0), errors='coerce') or 0

            # --- LOGIKA KONVERSI BENAR SESUAI MASTER ---
            is_box_type = part_num.upper().endswith('D')
            satuan_kecil = "Box" if is_box_type else "Sak"
            pcs_per_satuan = pcs_per_box if is_box_type else pcs_per_sak
            
            # Hitung jumlah box/sak per pallet (Total Pcs Pallet / Pcs per Box/Sak)
            satuan_per_pallet = (isi_pallet_pcs / pcs_per_satuan) if (pcs_per_satuan > 0 and isi_pallet_pcs > 0) else 0
            
            total_utuh_satuan = jml_utuh * satuan_per_pallet
            total_keseluruhan_satuan = total_utuh_satuan + val_pecahan
            
            if satuan_per_pallet > 0:
                teks_rincian = f"{jml_utuh} Pallet ({total_utuh_satuan:,.0f} {satuan_kecil})"
                if val_pecahan > 0:
                    teks_rincian += f" + {val_pecahan} {satuan_kecil} (Pecahan)"
                teks_rincian += f" = **Total {total_keseluruhan_satuan:,.0f} {satuan_kecil}**"
            else:
                teks_rincian = f"{jml_utuh} Pallet"
                if val_pecahan > 0:
                    teks_rincian += f" + {val_pecahan} Pecahan"
                teks_rincian += " (Data Master Konversi Belum Lengkap)"

            rekap_data.append({
                'Part Number': part_num,
                'Nama Produk': prod,
                'Pallet Utuh': jml_utuh,
                'Pecahan': val_pecahan if val_pecahan > 0 else "-",
                'Konversi Detail': teks_rincian
            })
            
        st.dataframe(pd.DataFrame(rekap_data), use_container_width=True, hide_index=True)
        
        with st.expander(f"🔍 Lihat Detail Posisi Tiap Pallet"):
            avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', product_col, 'Keterangan', 'Status'] if c in df_terisi.columns]
            df_tampil = df_terisi[avail].copy()
            if 'Pallet Ke' in df_tampil.columns:
                df_tampil = df_tampil.sort_values(by='Pallet Ke', ascending=True)
            st.dataframe(df_tampil, use_container_width=True, hide_index=True)
    else:
        st.success("✅ Baris ini KOSONG. Siap digunakan!")

# ==========================================================
# 7. METRIK & CSS VISUALISASI GRID
# ==========================================================
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
div[class^="st-key-btn_"] button {
    aspect-ratio: 1/1 !important; width: 100% !important; min-width: 22px !important;
    padding: 0px !important; margin: 0px !important; border: 1px solid #475569 !important;
    border-radius: 4px !important; display: flex !important; align-items: center !important;
    justify-content: center !important; font-size: clamp(10px, 1.2vw, 16px) !important; font-weight: 900 !important;
}
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

# ==========================================================
# 8. RENDER GRID AREA
# ==========================================================
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
                if not info['exist']:
                    st.write("") 
                else:
                    if st.button(f"{info['sku_cnt']}", key=f"btn_{k}_{b}", use_container_width=True):
                        show_rack_detail(k, b, info)
                            
    cols_bottom = st.columns([0.6] + [1] * total_kolom, gap="small")
    with cols_bottom[0]:
        st.write("")
        
    for idx, b in enumerate(subset_baris):
        with cols_bottom[idx + 1]:
            st.markdown(f"<div style='text-align:center; font-weight:900; color:#0ea5e9; font-size:clamp(10px, 1.2vw, 16px); margin-top:5px;'>{b}</div>", unsafe_allow_html=True)

render_grid_area("📍 Area 1: Rak Nomor 1 - 16 (Kapasitas: 31 Slot/Baris)", 1, 16)
st.write("")
st.divider()
st.write("")
render_grid_area("📍 Area 2: Rak Nomor 17 - 28 (Kapasitas: 44 Slot/Baris)", 17, 28)
