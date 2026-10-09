import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# ==========================================================
# 1. KONFIGURASI WEB
# ==========================================================
st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================================
# 2. INISIALISASI FIREBASE
# ==========================================================
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

st.title("📦 Visualisasi Grid Racking Gudang (Firebase)")
st.caption("Mode Mandiri (Stand-alone). Data ditarik dan disimpan di Firebase.")

# ==========================================================
# 3. UPLOADER DATA (PENGGANTI GOOGLE SHEETS)
# ==========================================================
st.sidebar.header("📤 Update Data Harian")
st.sidebar.caption("Upload file CSV dari susunan Excel Anda untuk memperbarui visualisasi.")

uploaded_file = st.sidebar.file_uploader("Upload File Stok (.csv)", type=["csv"])

if uploaded_file is not None:
    if st.sidebar.button("🚀 Sinkronisasi ke Firebase", use_container_width=True, type="primary"):
        with st.spinner("Mengirim ratusan data ke Firebase..."):
            try:
                # Coba baca dengan pemisah titik koma (;) dulu, jika gagal pakai koma (,)
                try:
                    df_upload = pd.read_csv(uploaded_file, sep=";")
                except Exception:
                    uploaded_file.seek(0)
                    df_upload = pd.read_csv(uploaded_file, sep=",")
                
                # Bersihkan nama kolom dari spasi dan karakter aneh bawaan Excel (\ufeff)
                df_upload.columns = df_upload.columns.str.replace('\ufeff', '').str.strip()
                
                batch = db.batch()
                count = 0
                
                for index, row in df_upload.iterrows():
                    kolom = str(row.get('Kolom', '')).strip()
                    baris = row.get('Baris')
                    pallet = row.get('Pallet Ke')
                    
                    if pd.notna(kolom) and pd.notna(baris) and pd.notna(pallet):
                        try:
                            b_int = int(float(baris))
                            p_int = int(float(pallet))
                            doc_id = f"{kolom}{b_int}-{p_int}"
                            
                            # Simpan ke collection khusus visualisasi
                            doc_ref = db.collection('visualisasi_rak').document(doc_id)
                            
                            # Mengubah baris menjadi dictionary yang bersih
                            data_dict = {str(k): (v if pd.notna(v) else "") for k, v in row.to_dict().items()}
                            batch.set(doc_ref, data_dict)
                            
                            count += 1
                            # Potong batch per 400 dokumen agar tidak overlimit
                            if count % 400 == 0:
                                batch.commit()
                                batch = db.batch()
                        except ValueError:
                            continue # Lewati jika baris/pallet bukan angka
                            
                # Commit sisa datanya
                batch.commit()
                st.sidebar.success(f"✅ {count} Pallet berhasil di-update!")
                st.cache_data.clear() # Paksa Streamlit refresh data
            except Exception as e:
                st.sidebar.error(f"Gagal mengunggah data: {e}")

st.sidebar.divider()

# ==========================================================
# 4. LOAD DATA DARI FIREBASE
# ==========================================================
@st.cache_data(ttl=5)
def load_data_from_firebase():
    docs = db.collection('visualisasi_rak').stream()
    data = [doc.to_dict() for doc in docs]
    if data:
        df = pd.DataFrame(data)
        for col in ['Baris', 'Pallet Ke', 'In', 'Out', 'Sisa']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    else:
        return pd.DataFrame()

df = load_data_from_firebase()

if df.empty:
    st.warning("Data visualisasi masih kosong. Silakan upload file CSV Anda di menu samping kiri.")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# ==========================================================
# 5. SIDEBAR PENCARIAN & FILTER
# ==========================================================
st.sidebar.header("🔍 Pencarian & Filter")
if product_col in df.columns:
    daftar_barang = sorted(df[product_col].dropna().astype(str).unique().tolist())
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
# 6. KONDISI RAK & PEMROSESAN MATRIKS
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
                
            max
