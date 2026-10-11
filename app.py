import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import time

# ==========================================================
# 1. KONFIGURASI WEB & DATABASE
# ==========================================================
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 💡 UBAH NAMA INI MENJADI 'visualisasi_rak' JIKA SUDAH SELESAI UJI COBA
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
    # Filter sel kosong
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
                
            # PERBAIKAN BUG: Hapus sel kosong dan spasi sebelum menghitung jenis SKU
            prods = sub[sub[prod_col].astype(str).str.strip() != ""][prod_col].unique() if prod_col in sub.columns else []
