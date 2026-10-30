import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

st.set_page_config(page_title="Analisis Penggunaan Palet", page_icon="📈", layout="wide")

st.title("📈 Dashboard Analisis & Proyeksi Penggunaan Palet Warehouse")
st.caption("Visualisasi data harian (Kamis s.d. Minggu) terhadap kapasitas maksimal rak ideal.")

# 1. Dataframe Berdasarkan Tabel
data_warehouse = {
    "Hari": ["Kamis", "Jum'at", "Sabtu", "Minggu"],
    "Produksi Harian": [604, 597, 259, 259],
    "Output Delivery": [518, 493, 160, 0],
    "Pertambahan Finish Good": [86, 104, 99, 259],
    "Grand Total Pallet": [6106, 6210, 6309, 6568],
    "Sisa Rak Ideal": [442, 338, 239, -20]
}
df_wh = pd.DataFrame(data_warehouse)

# 2. Metrik Utama di Atas Grafik
m1, m2, m3, m4 = st.columns(4)
m1.metric("Stok Rak Hari Ini", "6.020 Pallet", "Efisiensi 91,9%")
m2.metric("Kapasitas Maksimal", "6.548 Pallet", "Full Capacity Ideal")
m3.metric("Proyeksi Puncak (Minggu)", "6.568 Pallet", "⚠️ Overcapacity", delta_color="inverse")
m4.metric("Min Sisa Rak (Minggu)", "-20 Slot", "Wajib Eksekusi Outbound!", delta_color="inverse")

st.divider()

# 3. Grafik 1: Tren Grand Total Pallet vs Batas Kapasitas Maksimal
st.subheader("📊 Proyeksi Lonjakan Grand Total Pallet (Kamis - Minggu)")
fig_trend = go.Figure()

# Garis Tren Grand Total
fig_trend.add_trace(go.Scatter(
    x=df_wh["Hari"], y=df_wh["Grand Total Pallet"],
    mode='lines+markers+text',
    name='Grand Total Pallet',
    text=df_wh["Grand Total Pallet"],
    textposition="top center",
    line=dict(color='#2563eb', width=4),
    marker=dict(size=10)
))

# Garis Batas Maksimal (Threshold Line)
fig_trend.add_trace(go.Scatter(
    x=df_wh["Hari"], y=[6548]*4,
    mode='lines',
    name='Batas Maksimal Rak Ideal (6.548)',
    line=dict(color='#ef4444', width=2, dash='dash')
))

fig_trend.update_layout(
    xaxis_title="Hari",
    yaxis_title="Jumlah Pallet",
    yaxis=dict(range=[6000, 6700]),
    template="plotly_white",
    hovermode="x unified"
)
st.plotly_chart(fig_trend, use_container_width=True)

# 4. Grafik 2: Perbandingan Produksi Harian vs Output Delivery (Bar Chart)
st.subheader("🏭 Perbandingan Produksi Masuk vs Output Delivery")
df_melted = df_wh.melt(id_vars=["Hari"], value_vars=["Produksi Harian", "Output Delivery"], 
                       var_name="Jenis Aktivitas", value_name="Jumlah Pallet")

fig_bar = px.bar(
    df_melted, x="Hari", y="Jumlah Pallet", color="Jenis Aktivitas",
    barmode="group",
    color_discrete_map={"Produksi Harian": "#f59e0b", "Output Delivery": "#10b981"},
    text_auto=True
)
fig_bar.update_layout(template="plotly_white")
st.plotly_chart(fig_bar, use_container_width=True)
