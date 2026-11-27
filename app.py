import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re
import io
from datetime import datetime, timedelta
import plotly.express as px

# ==========================================================
# 1. KONFIGURASI HALAMAN
# ==========================================================
st.set_page_config(
    page_title="Warehouse 2D Racking", 
    page_icon="📦", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# ==========================================================
# 2. INIT FIREBASE (DATABASE UJI COBA)
# ==========================================================
NAMA_DATABASE = 'uji_coba_rak'

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# 3. FUNGSI LOAD DATA (SMART CACHE & MASTER PRODUK)
# ==========================================================
@st.cache_data(ttl=300)
def load_data_from_firebase():
    docs = db.collection(NAMA_DATABASE).stream()
    semua_data = []
    
    for doc in docs:
        doc_data = doc.to_dict()
        if 'data' in doc_data:
            semua_data.extend(doc_data['data'])
            
    if not semua_data: 
        return pd.DataFrame()
        
    df = pd.DataFrame(semua_data)
    for c in df.columns:
        if c.strip().lower() in ['palet ke', 'pallet ke']:
            df.rename(columns={c: 'Pallet Ke'}, inplace=True)
            
    for col in ['Baris', 'Pallet Ke']:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            
    # Filter eksklusif hanya kolom Shuttle Racking (A - G)
    if 'Kolom' in df.columns:
        df['Kolom'] = df['Kolom'].astype(str).str.strip().str.upper()
        df = df[df['Kolom'].isin(['A', 'B', 'C', 'D', 'E', 'F', 'G'])].copy()
            
    return df

@st.cache_data(ttl=3600)
def load_master_produk():
    try:
        try: 
            df_master = pd.read_csv("Master_Produk.csv", sep=";", encoding='utf-8-sig')
        except: 
            df_master = pd.read_csv("Master_Produk.csv", sep=",", encoding='utf-8-sig')
        
        df_master.columns = df_master.columns.str.strip()
        if 'Part Number' in df_master.columns:
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        return df_master
    except:
        return pd.DataFrame()

# Optimasi RAM: Dictionary O(1) Lookup
df_master_global = load_master_produk()
master_dict = {}
if not df_master_global.empty and 'Part Number Clean' in df_master_global.columns:
    kat_cols = [c for c in df_master_global.columns if any(k in c.lower() for k in ['kategori', 'jenis', 'group', 'tipe', 'nama'])]
    for _, row in df_master_global.iterrows():
        pn = row['Part Number Clean']
        ip = pd.to_numeric(row.get('Isi 1 Pallet (pcs)', 0), errors='coerce')
        pb = pd.to_numeric(row.get('Box / Pallet', 0), errors='coerce')
        ps = pd.to_numeric(row.get('Sac / Pallet', 0), errors='coerce')
        meta_text = " ".join([str(row.get(c, '')) for c in kat_cols if pd.notna(row.get(c, ''))]).upper()
        master_dict[pn] = {
            'ip': 0 if pd.isna(ip) else float(ip),
            'pb': 0 if pd.isna(pb) else float(pb),
            'ps': 0 if pd.isna(ps) else float(ps),
            'meta': meta_text
        }

# ==========================================================
# FUNGSI HELPER, PARSER STOK AKURAT, & KLASIFIKASI PRODUK
# ==========================================================
def get_waktu_jkt():
    return datetime.utcnow() + timedelta(hours=7)

def parse_lot_date(lot_str):
    cleaned = str(lot_str).strip()
    if len(cleaned) >= 6:
        date_str = cleaned[-6:]
        shift_char = cleaned[-7] if len(cleaned) >= 7 and cleaned[-7].isdigit() else '9'
        shift_num = int(shift_char)
        
        try:
            day = int(date_str[0:2])
            month = int(date_str[2:4])
            year = int('20' + date_str[4:6])
            return datetime(year, month, day, hour=shift_num)
        except:
            return datetime(2099, 12, 31, hour=23)
    return datetime(2099, 12, 31, hour=23)

def format_compact_number(num):
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M".replace('.0M', 'M')
    elif num >= 1_000:
        return f"{num/1_000:.1f}k".replace('.0k', 'k')
    return str(int(num))

def parse_keterangan_stok(row_ket):
    ket_str = str(row_ket).strip().lower()
    if not ket_str or ket_str in ['nan', 'none', '-', 'utuh', 'full']:
        return 1, 0, 0

    if 'pecahan' not in ket_str and 'eceran' not in ket_str and 'dus' not in ket_str and 'sak' not in ket_str and 'pcs' not in ket_str:
        return 1, 0, 0

    val_pecahan = 0
    val_eceran = 0

    mp = re.search(r'pecahan\s*:?\s*(\d+)', ket_str)
    if mp:
        val_pecahan += int(mp.group(1))
    else:
        mp_unit = re.search(r'(\d+)\s*(?:dus|box|sak|sac)', ket_str)
        if mp_unit:
            val_pecahan += int(mp_unit.group(1))

    me = re.search(r'eceran\s*:?\s*(\d+)', ket_str)
    if me:
        val_eceran += int(me.group(1))
    else:
        me_unit = re.search(r'(\d+)\s*pcs', ket_str)
        if me_unit:
            val_eceran += int(me_unit.group(1))

    if val_pecahan == 0 and val_eceran == 0 and 'pecahan' in ket_str:
        nums = re.findall(r'\d+', ket_str)
        if nums:
            val_pecahan += int(nums[0])

    return 0, val_pecahan, val_eceran

def hitung_pcs_baris(row_ket, part_num):
    pn = str(part_num).strip().upper()
    jml_utuh, val_pecahan, val_eceran = parse_keterangan_stok(row_ket)
        
    master_info = master_dict.get(pn, {'ip': 0, 'pb': 0, 'ps': 0})
    pss = master_info['pb'] if pn.endswith(('D', 'G')) else master_info['ps']
    
    return (jml_utuh * master_info['ip']) + (val_pecahan * pss) + val_eceran

def klasifikasi_kategori_palet(part_num, nama_produk, baris=0):
    pn = str(part_num).strip().upper()
    prod = str(nama_produk).strip().upper()
    meta = master_dict.get(pn, {}).get('meta', '')
    combined = f"{pn} {prod} {meta}"

    if "MOUNTEA" in combined and re.search(r'2[.,]9|3[.,]1', combined):
        return "Cup Color"

    if "PREFORM" in combined or "PFM" in combined or (1 <= int(baris) <= 16 and "CUP" not in combined):
        return "All Preform"

    if "PRINTING" in combined or "PRINT" in combined or "PRT" in combined:
        return "Cup Printing"

    warna_keywords = [
        "COLOR", "COLOUR", "MERAH", "BIRU", "HIJAU", "KUNING", 
        "COKLAT", "COKELAT", "PUTIH", "HITAM", "ORANGE", "UNGU", 
        "PINK", "GOLD", "SILVER", "TOSCA", "MAROON", "RED", "BLUE", "GREEN", "YELLOW"
    ]
    if any(re.search(rf'\b{w}\b', combined) for w in warna_keywords):
        return "Cup Color"

    return "Cup Natural"

@st.cache_data(ttl=300)
def hitung_distribusi_produk_palet(df, prod_col, kapasitas_total=6548):
    if df.empty or 'Part Number' not in df.columns:
        return pd.DataFrame({
            'Kategori': ['Free Space'],
            'Jumlah Palet': [kapasitas_total]
        }), 0

    valid_mask = ~df['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])
    df_valid = df[valid_mask].copy()
    total_terisi = len(df_valid)

    if total_terisi == 0:
        return pd.DataFrame({
            'Kategori': ['Free Space'],
            'Jumlah Palet': [kapasitas_total]
        }), 0

    kategori_series = [
        klasifikasi_kategori_palet(
            row.get('Part Number', ''),
            row.get(prod_col, '') if prod_col in df_valid.columns else '',
            row.get('Baris', 0)
        )
        for _, row in df_valid.iterrows()
    ]

    counts = pd.Series(kategori_series).value_counts().to_dict()
    free_space = max(0, kapasitas_total - total_terisi)

    urutan_label = ['All Preform', 'Cup Printing', 'Cup Natural', 'Cup Color', 'Free Space']
    data_pie = []
    for lbl in urutan_label:
        val = free_space if lbl == 'Free Space' else counts.get(lbl, 0)
        if val > 0:
            data_pie.append({'Kategori': lbl, 'Jumlah Palet': int(val)})

    return pd.DataFrame(data_pie), total_terisi

def build_picking_cards(kolom, baris, df_sub, prod_col):
    lokasi_str = f"{kolom}-{baris}"
    area_str = "Area 1 (1–16)" if baris <= 16 else "Area 2 (17–28)"
    
    if df_sub.empty or 'Part Number' not in df_sub.columns:
        return [{
            'Lokasi': lokasi_str, 'Area': area_str, 'Part Number': '-',
            'Nama Produk': 'RAK KOSONG', 'Total Fisik': '0', 'Total Pcs': 0,
            'Rumus Konversi': '-', 'Detail Lot': [], 'Is_Empty': True
        }]
        
    valid_df = df_sub[~df_sub['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])].copy()
    if valid_df.empty:
        return [{
            'Lokasi': lokasi_str, 'Area': area_str, 'Part Number': '-',
            'Nama Produk': 'RAK KOSONG', 'Total Fisik': '0', 'Total Pcs': 0,
            'Rumus Konversi': '-', 'Detail Lot': [], 'Is_Empty': True
        }]

    valid_df['PN_Clean'] = valid_df['Part Number'].astype(str).str.strip().str.upper()
    if 'Pallet Ke' in valid_df.columns:
        valid_df = valid_df.sort_values(by='Pallet Ke', ascending=True)

    pn_order = valid_df.groupby('PN_Clean')['Pallet Ke'].min().sort_values().index.tolist()
    cards = []

    for pn in pn_order:
        df_item = valid_df[valid_df['PN_Clean'] == pn].copy()
        prod_name = str(df_item[prod_col].dropna().values[0]).strip() if prod_col in df_item.columns and len(df_item[prod_col].dropna().values) > 0 else "-"
        
        master_info = master_dict.get(pn, {'ip': 0, 'pb': 0, 'ps': 0})
        pss = master_info['pb'] if pn.endswith(('D', 'G')) else master_info['ps']
        satuan_pecahan = "Dus" if pn.endswith(('D', 'G')) else "Sak"

        df_item['Lot_Clean'] = df_item['Lot Number'].fillna('-').astype(str).str.strip()
        df_item['Tgl_Sort'] = df_item['Lot_Clean'].apply(parse_lot_date)
        df_item = df_item.sort_values(by=['Tgl_Sort', 'Pallet Ke'], ascending=[True, True])

        lot_details = []
        tot_item_utuh, tot_item_pecahan, tot_item_eceran, tot_item_pcs = 0, 0, 0, 0

        for lot_val, grp_lot in df_item.groupby('Lot_Clean', sort=False):
            pallets = sorted(grp_lot['Pallet Ke'].tolist())
            plt_range = f"{pallets[0]}–{pallets[-1]}" if len(pallets) > 1 else str(pallets[0])
            
            u, p_val, e_val = 0, 0, 0
            catatan_set = set()
            for _, r in grp_lot.iterrows():
                du, dp, de = parse_keterangan_stok(r.get('Keterangan', ''))
                u += du
                p_val += dp
                e_val += de
                
                cat_str = str(r.get('Catatan', '')).strip()
                if cat_str and cat_str.lower() not in ['nan', 'none', '']:
                    catatan_set.add(cat_str)

            pcs_lot = (u * master_info['ip']) + (p_val * pss) + e_val
            tot_item_utuh += u
            tot_item_pecahan += p_val
            tot_item_eceran += e_val
            tot_item_pcs += pcs_lot

            qty_parts = []
            if u > 0: qty_parts.append(f"{u} Plt")
            if p_val > 0: qty_parts.append(f"{p_val} {satuan_pecahan}")
            if e_val > 0: qty_parts.append(f"{e_val} Pcs")
            qty_str = " + ".join(qty_parts) if qty_parts else "0"

            rumus_lot_parts = []
            if u > 0 and master_info['ip'] > 0:
                rumus_lot_parts.append(f"{u}×{master_info['ip']:,.0f}".replace(',', '.'))
            if p_val > 0 and pss > 0:
                rumus_lot_parts.append(f"{p_val}×{pss:,.0f}".replace(',', '.'))
            if e_val > 0:
                rumus_lot_parts.append(f"{e_val:,.0f} ecer".replace(',', '.'))
            rumus_lot_str = " + ".join(rumus_lot_parts) if rumus_lot_parts else "-"

            tgl_dt = parse_lot_date(lot_val)
            tgl_str = tgl_dt.strftime('%d-%m-%Y') if tgl_dt.year != 2099 else "-"

            lot_details.append({
                'lot': lot_val,
                'tgl': tgl_str,
                'pallet_range': plt_range,
                'qty_str': qty_str,
                'rumus_lot': rumus_lot_str,
                'pcs': int(pcs_lot),
                'catatan': ", ".join(sorted(catatan_set)) if catatan_set else "-"
            })

        tot_parts = []
        if tot_item_utuh > 0: tot_parts.append(f"{tot_item_utuh} Plt")
        if tot_item_pecahan > 0: tot_parts.append(f"{tot_item_pecahan} {satuan_pecahan}")
        if tot_item_eceran > 0: tot_parts.append(f"{tot_item_eceran} Pcs")

        rumus_tot_parts = []
        if tot_item_utuh > 0 and master_info['ip'] > 0:
            rumus_tot_parts.append(f"{tot_item_utuh} Plt × {master_info['ip']:,.0f}".replace(',', '.'))
        if tot_item_pecahan > 0 and pss > 0:
            rumus_tot_parts.append(f"{tot_item_pecahan} {satuan_pecahan} × {pss:,.0f}".replace(',', '.'))
        if tot_item_eceran > 0:
            rumus_tot_parts.append(f"{tot_item_eceran:,.0f} Pcs Eceran".replace(',', '.'))
        rumus_konversi_str = " + ".join(rumus_tot_parts) if rumus_tot_parts else "-"

        cards.append({
            'Lokasi': lokasi_str,
            'Area': area_str,
            'Part Number': pn,
            'Nama Produk': prod_name,
            'Total Fisik': " + ".join(tot_parts) if tot_parts else "0",
            'Total Pcs': int(tot_item_pcs),
            'Rumus Konversi': rumus_konversi_str,
            'Detail Lot': lot_details,
            'Is_Empty': False
        })

    return cards

def render_print_html(cards, judul_dok, waktu_cetak):
    cards_html = ""
    for c in cards:
        if c['Is_Empty']:
            cards_html += f"""
            <div class="card empty-card">
                <div class="card-header">
                    <div class="loc-badge">{c['Lokasi']}</div>
                    <div class="area-tag">{c['Area']} — RAK KOSONG (Siap Diisi Inbound)</div>
                </div>
                <div class="card-footer">
                    <span>Dicetak: {waktu_cetak}</span>
                    <span>Paraf Operator: ______________________</span>
                </div>
            </div>
            """
        else:
            rows_html = ""
            for idx, ld in enumerate(c['Detail Lot'], start=1):
                pcs_fmt = f"{ld['pcs']:,.0f}".replace(',', '.') if ld['pcs'] > 0 else "-"
                cat_badge = f" <span class='cat-warn'>[{ld['catatan']}]</span>" if ld['catatan'] != "-" else ""
                rows_html += f"""
                <tr>
                    <td class="center">{idx}</td>
                    <td class="bold">{ld['lot']}{cat_badge}</td>
                    <td class="center">{ld['tgl']}</td>
                    <td class="center bold">{ld['pallet_range']}</td>
                    <td class="right bold">{ld['qty_str']}</td>
                    <td class="right muted">{ld['rumus_lot']}</td>
                    <td class="right bold">{pcs_fmt}</td>
                </tr>
                """
            tot_pcs_fmt = f"{c['Total Pcs']:,.0f}".replace(',', '.')
            cards_html += f"""
            <div class="card">
                <div class="card-header">
                    <div class="loc-badge">{c['Lokasi']}</div>
                    <div class="prod-box">
                        <div class="pn-text">{c['Part Number']}</div>
                        <div class="prod-name">{c['Nama Produk']}</div>
                    </div>
                    <div class="header-total-box">
                        <div class="header-total-label">TOTAL KUANTITAS</div>
                        <div class="header-total-val">{tot_pcs_fmt} Pcs</div>
                    </div>
                </div>
                <table class="lot-table">
                    <thead>
                        <tr>
                            <th style="width:5%;">#</th>
                            <th style="width:20%;">Lot Number</th>
                            <th style="width:13%;">Tgl Prod</th>
                            <th style="width:11%;">Plt Ke</th>
                            <th style="width:18%;">Qty Fisik</th>
                            <th style="width:19%;">Rincian Konversi</th>
                            <th style="width:14%;">Total Pcs</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                    <tfoot>
                        <tr>
                            <td colspan="4" class="right bold">TOTAL KESELURUHAN:</td>
                            <td class="right bold">{c['Total Fisik
