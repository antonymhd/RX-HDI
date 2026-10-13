import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import time
import re

st.set_page_config(
    page_title="Warehouse 2D Racking System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

NAMA_DATABASE = 'uji_coba_rak'

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

st.sidebar.header("🔄 Muat Ulang")
if st.sidebar.button("Refresh Layar Visualisasi", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.header("👁️ Mode Tampilan Grid")
mode_tampilan = st.sidebar.radio(
    "Angka pada kotak rak menunjukkan:",
    ["Variasi SKU (Jenis Barang)", "Sisa Slot Kosong"]
)

st.sidebar.divider()
st.sidebar.header("🔐 Akses Khusus Admin")
KUNCI_RAHASIA = "admin123"
kunci_input = st.sidebar.text_input("Kunci Rahasia:", type="password")

if kunci_input == KUNCI_RAHASIA:
    st.sidebar.success("✅ Akses Diberikan")
    uploaded_file = st.sidebar.file_uploader("Upload File Stok (.csv)", type=["csv"])

    if uploaded_file is not None:
        if st.sidebar.button("🚀 Sinkronisasi ke Firebase", use_container_width=True, type="primary"):
            with st.spinner("Mengirim data..."):
                try:
                    try: df_upload = pd.read_csv(uploaded_file, sep=";")
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
                                clean_records = [{str(k): (v if pd.notna(v) else "") for k, v in r.items()} for r in records]
                                batch.set(doc_ref, {'data': clean_records})
                        batch.commit()
                        st.sidebar.success("✅ Sinkronisasi berhasil!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Gagal: {e}")

    if st.sidebar.button("🧹 Bersihkan Data Anomali (Auto-Fix)", type="secondary", use_container_width=True):
        with st.spinner("Membersihkan database..."):
            try:
                docs = db.collection(NAMA_DATABASE).stream()
                batch = db.batch()
                for doc in docs:
                    doc_data = doc.to_dict().get('data', [])
                    cleaned_data = [d for d in doc_data if str(d.get('Part Number', '')).strip() not in ['', 'nan']]
                    from collections import defaultdict
                    baris_dict = defaultdict(list)
                    for d in cleaned_data: baris_dict[float(d.get('Baris', 0))].append(d)
                    final_data = []
                    for b, items in baris_dict.items():
                        items_sorted = sorted(items, key=lambda x: pd.to_numeric(x.get('Pallet Ke', 999), errors='coerce'))
                        for idx, item in enumerate(items_sorted):
                            item['Pallet Ke'] = float(idx + 1)
                            item['In'] = 1.0
                            final_data.append(item)
                    batch.set(doc.reference, {'data': final_data})
                batch.commit()
                st.sidebar.success("✅ Selesai dibersihkan!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Gagal: {e}")

st.title("📦 Visualisasi Grid Racking Gudang (WMS)")
st.caption(f"Terhubung ke database: {NAMA_DATABASE} (Cache Aktif 1 Jam)")

@st.cache_data(ttl=3600)
def load_data_from_firebase():
    try:
        docs = db.collection(NAMA_DATABASE).stream()
        all_data = []
        for doc in docs:
            doc_data = doc.to_dict()
            if 'data' in doc_data: all_data.extend(doc_data['data'])
        if all_data:
            df = pd.DataFrame(all_data)
            for col in ['Baris', 'Pallet Ke']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"🚨 Gagal memuat data: {e}")
        return None

df = load_data_from_firebase()
if df is None or df.empty:
    st.info("Data visualisasi masih kosong.")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'
daftar_barang = sorted(df[df[product_col].astype(str).str.strip() != ""][product_col].dropna().astype(str).unique().tolist())
pilihan_pencarian = st.sidebar.selectbox("Cari Nama Barang:", options=["-- Tampilkan Semua --"] + daftar_barang)
search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian

def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

def process_matrix_data(df, search_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    matrix_info = {}
    total_critical = total_kosong = 0
    lokasi_kritis = lokasi_kosong = []
    
    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {'exist': False}
                continue
            sub = df[(df['Kolom'] == k) & (float(b) == pd.to_numeric(df['Baris'], errors='coerce'))]
            is_all_box = False
            if 'Part Number' in sub.columns:
                p_nums = sub['Part Number'].dropna().astype(str).str.strip().str.upper()
                p_nums = p_nums[p_nums != ""]
                if not p_nums.empty: is_all_box = p_nums.str.endswith(('D', 'G')).all()
            
            max_slot = (32 if b <= 16 else 46) if is_all_box else (31 if b <= 16 else 44)
            prods = sub[sub['Part Number'].astype(str).str.strip() != ""]['Part Number'].unique() if 'Part Number' in sub.columns else []
            sku = len(prods)
            filled = sub['Part Number'].apply(lambda x: str(x).strip() != "" and pd.notna(x)).sum() if 'Part Number' in sub.columns else 0
            usable_space = max(0, max_slot - filled)
            
            is_match = False
            if search_term and prod_col in sub.columns:
                m_prod = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False, regex=False).any()
                m_part = sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False, regex=False).any() if 'Part Number' in sub.columns else False
                is_match = m_prod or m_part
            
            if sku >= 4: total_critical += 1
            elif sku == 0: total_kosong += 1
                
            matrix_info[(k, b)] = {
                'exist': True, 'sku_cnt': sku, 'filled': filled,
                'usable_space': usable_space, 'max_slot': max_slot, 'prods': prods,
                'df_sub': sub, 'is_match': is_match
            }
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list

matrix_info, total_critical, total_kosong, kolom_list, baris_list = process_matrix_data(df, search_query, product_col)

@st.dialog("📦 Rincian Detail Rak & Konversi Stok", width="large")
def show_rack_detail(k, b, info):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    c2.metric("Slot Terpakai", f"{info['filled']} / {info['max_slot']}")
    c3.metric("Space Kosong", f"{info['usable_space']} Slot")
    st.divider()
    
    if info['sku_cnt'] > 0:
        try:
            df_master = pd.read_csv("Master_Produk.csv", sep=";") if ";" in open("Master_Produk.csv").readline() else pd.read_csv("Master_Produk.csv", sep=",")
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        except: df_master = pd.DataFrame()

        df_terisi = info['df_sub'][info['df_sub']['Part Number'].astype(str).str.strip() != ""]
        rekap_data = []
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            prod_name = df_prod[product_col].iloc[0] if product_col in df_prod.columns else "-"
            jml_utuh = df_prod[~df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)].shape[0]
            
            pecahan_rows = df_prod[df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)]
            val_pecahan = val_eceran = 0
            if not pecahan_rows.empty:
                ket_str = str(pecahan_rows['Keterangan'].iloc[0]).lower()
                mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                if mp: val_pecahan = int(mp.group(1))
                me = re.search(r'eceran:\s*(\d+)', ket_str)
                if me: val_eceran = int(me.group(1))

            ip = pb = ps = 0
            pnc = part_num.upper()
            if not df_master.empty and pnc in df_master['Part Number Clean'].values:
                mr = df_master[df_master['Part Number Clean'] == pnc].iloc[0]
                ip = float(mr.get('Isi 1 Pallet (pcs)', 0) or 0)
                pb = float(mr.get('Box / Pallet', 0) or 0)
                ps = float(mr.get('Sac / Pallet', 0) or 0)

            sc = "Dus" if pnc.endswith('D') else "Sak"
            pss = pb if pnc.endswith('D') else ps
            
            if ip > 0:
                tot = (jml_utuh * ip) + (val_pecahan * pss) + val_eceran
                teks_rincian = f"{jml_utuh} Pallet * {ip:,.0f}"
                if val_pecahan > 0: teks_rincian += f" + {val_pecahan} {sc} * {pss:,.0f}"
                if val_eceran > 0: teks_rincian += f" + {val_eceran} Pcs"
                teks_rincian += f" = **Total {tot:,.0f} Pcs**"
            else:
                teks_rincian = f"{jml_utuh} Pallet"

            rekap_data.append({'Part Number': pnc, 'Nama Produk': prod_name, 'Pallet Utuh': jml_utuh, 'Konversi Total Pcs': teks_rincian})
        st.dataframe(pd.DataFrame(rekap_data), use_container_width=True, hide_index=True)

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Total Baris Aktif", "156 Baris")
col_m2.metric("Baris Kritis", f"{total_critical} Baris")
col_m3.metric("Baris Kosong", f"{total_kosong} Baris")
st.divider()

def render_grid_area(title, start_baris, end_baris):
    st.markdown(f"### {title}")
    for k in kolom_list:
        cols = st.columns([0.6] + [1] * 16, gap="small")
        with cols[0]: st.markdown(f"<div style='font-weight:900;'>{k}</div>", unsafe_allow_html=True)
        for idx, b in enumerate(list(range(start_baris, end_baris + 1))):
            info = matrix_info[(k, b)]
            with cols[idx + 1]:
                if info['exist']:
                    lbl = str(info['usable_space']) if mode_tampilan == "Sisa Slot Kosong" else str(info['sku_cnt'])
                    if st.button(lbl, key=f"btn_{k}_{b}", use_container_width=True): show_rack_detail(k, b, info)

render_grid_area("📍 Area 1 (Rak 1 - 16)", 1, 16)
render_grid_area("📍 Area 2 (Rak 17 - 28)", 17, 28)
