import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
import datetime

# --- Configuration & Static Data ---
st.set_page_config(page_title="Real Exchange Rate Observer", layout="wide")

# Standardized dictionary of a few major IMF ISO3 codes including G163 for Euro Area.
# Expand this dictionary as needed for a complete country list.
COUNTRY_CODES = {
    "United States": "USA",
    "Euro Area": "G163",
    "United Kingdom": "GBR",
    "Japan": "JPN",
    "Switzerland": "CHE",
    "Canada": "CAN",
    "Australia": "AUS",
    "Mexico": "MEX",
    "Brazil": "BRA",
    "South Korea": "KOR"
}

BASE_URL = "https://api.imf.org/external/sdmx/3.0/data/IFS/"

# --- Data Fetching Logic ---
@st.cache_data(ttl=86400)
def fetch_imf_data(iso3, indicator):
    """
    Fetches time series data from the IMF SDMX 3.0 API.
    Handles standard SDMX JSON response structure.
    """
if indicator == 'CPI':
        key = f"{iso3}.CPI._T.IX.M"
elif indicator == 'EXR':
        key = f"{iso3}.XDC_USD.PA_RT.M"
    else:
        return pd.Series(dtype=float)

    # Note: Depending on exact IMF endpoint configurations, the URL structure 
    # might require adjusting the flow (e.g., IFS) or the dimension order.
    url = f"{BASE_URL}{key}?startPeriod=1976-01"
    headers = {'Accept': 'application/vnd.sdmx.data+json;version=1.0.0-wd'}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Traverse the standard SDMX JSON response to extract periods and values
        # The exact path may vary based on the specific SDMX 3.0 implementation of the IMF
        series_data = data.get('data', {}).get('dataSets', [])[0].get('series', {})
        
        if not series_data:
            return pd.Series(dtype=float)
            
        # The first key in 'series' contains the observations
        obs = list(series_data.values())[0].get('observations', {})
        
        # Extract time periods from structure
        time_periods = data.get('data', {}).get('structure', {}).get('dimensions', {}).get('observation', [])[0].get('values', [])
        
        dates = []
        values = []
        
        for idx, obs_val in obs.items():
            dates.append(time_periods[int(idx)]['name'])
            values.append(float(obs_val[0]))
            
        df = pd.DataFrame({'Date': pd.to_datetime(dates), 'Value': values})
        df.set_index('Date', inplace=True)
        # Resample to ensure strict monthly frequency and sort
        return df['Value'].resample('MS').first()

    except Exception as e:
        st.warning(f"Failed to fetch {indicator} for {iso3}: {str(e)}")
        return pd.Series(dtype=float)

# --- Main Application ---
st.title("Real Exchange Rate (RER) Observer")

col1, col2 = st.columns(2)
with col1:
    c1_name = st.selectbox("Select Country 1 (Base Currency)", options=list(COUNTRY_CODES.keys()), index=0)
with col2:
    c2_name = st.selectbox("Select Country 2 (Target Currency)", options=list(COUNTRY_CODES.keys()), index=1)

c1_iso = COUNTRY_CODES[c1_name]
c2_iso = COUNTRY_CODES[c2_name]

if c1_iso == c2_iso:
    st.error("Please select two different countries.")
    st.stop()

with st.spinner("Fetching data from IMF API..."):
    # Fetch CPI and Exchange Rates
    # USD Exchange rate is naturally 1 for the US, handle programmatically if API returns empty for USA EXR
    c1_cpi = fetch_imf_data(c1_iso, 'CPI')
    c2_cpi = fetch_imf_data(c2_iso, 'CPI')
    
    c1_exr = pd.Series(1.0, index=c1_cpi.index) if c1_iso == "USA" else fetch_imf_data(c1_iso, 'EXR')
    c2_exr = pd.Series(1.0, index=c2_cpi.index) if c2_iso == "USA" else fetch_imf_data(c2_iso, 'EXR')

# Combine into a single DataFrame
df = pd.DataFrame({
    'C1_CPI': c1_cpi,
    'C2_CPI': c2_cpi,
    'C1_EXR': c1_exr,
    'C2_EXR': c2_exr
}).dropna(how='all')

# Ensure Date index is clean
df.index = pd.to_datetime(df.index)

# Calculate Nominal Exchange Rate S(t) = C2/C1
# IMF EXR is local currency per USD. 
# So, (C2/USD) / (C1/USD) = C2/C1
df['S_t'] = df['C2_EXR'] / df['C1_EXR']

# Calculate RER(t) = S(t) * (P1(t) / P2(t))
df['RER_t'] = df['S_t'] * (df['C1_CPI'] / df['C2_CPI'])

# Drop rows where we cannot compute RER or S(t) due to missing data
df = df.dropna(subset=['S_t', 'RER_t'])

if df.empty:
    st.error("Insufficient overlapping data for the selected countries to calculate RER.")
    st.stop()

# --- Date Selection ---
st.sidebar.header("Sample Period")
min_date = df.index.min().date()
max_date = df.index.max().date()

start_date = st.sidebar.date_input("Start Date", min_date, min_value=min_date, max_value=max_date)
end_date = st.sidebar.date_input("End Date", max_date, min_value=min_date, max_value=max_date)

if start_date > end_date:
    st.sidebar.error("Start date must be before End date.")
    st.stop()

# Filter dataframe based on selection
mask = (df.index.date >= start_date) & (df.index.date <= end_date)
df_filtered = df.loc[mask].copy()

if df_filtered.empty:
    st.warning("No valid data available for the selected date range.")
    st.stop()

# Calculate RER* (Average of RER over valid months in the selected period)
rer_star = df_filtered['RER_t'].mean()

# Calculate Real Index(t) = 100 * (RER(t) / RER*)
df_filtered['Real_Index'] = 100 * (df_filtered['RER_t'] / rer_star)

# --- Charting ---
st.sidebar.header("Chart Options")
chart_type = st.sidebar.radio("Display:", ["Real Index", "Nominal Exchange Rate", "Both"])

fig = make_subplots(specs=[[{"secondary_y": True}]])

if chart_type in ["Real Index", "Both"]:
    fig.add_trace(
        plotly_go.Scatter(x=df_filtered.index, y=df_filtered['Real_Index'], name="Real Index", line=dict(color='blue')),
        secondary_y=False,
    )
    fig.update_yaxes(title_text="Real Index (Base=100)", secondary_y=False)

if chart_type in ["Nominal Exchange Rate", "Both"]:
    # Display S(t) on secondary axis if "Both" is selected, otherwise primary
    is_secondary = True if chart_type == "Both" else False
    fig.add_trace(
        plotly_go.Scatter(x=df_filtered.index, y=df_filtered['S_t'], name=f"Nominal S(t) ({c2_iso}/{c1_iso})", line=dict(color='orange')),
        secondary_y=is_secondary,
    )
    if is_secondary:
         fig.update_yaxes(title_text=f"Nominal {c2_iso}/{c1_iso}", secondary_y=True)
    else:
         fig.update_yaxes(title_text=f"Nominal {c2_iso}/{c1_iso}", secondary_y=False)

fig.update_layout(
    title=f"Exchange Rate Dynamics: {c1_name} vs {c2_name}",
    xaxis_title="Date",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)

st.plotly_chart(fig, use_container_width=True)

# --- CSV Download ---
st.subheader("Data Export")
csv_data = df_filtered[['S_t', 'C1_CPI', 'C2_CPI', 'RER_t', 'Real_Index']].rename(columns={
    'S_t': f'Nominal_{c2_iso}_per_{c1_iso}',
    'C1_CPI': f'CPI_{c1_iso}',
    'C2_CPI': f'CPI_{c2_iso}',
    'RER_t': 'Raw_RER',
    'Real_Index': 'Real_Exchange_Rate_Index'
})

st.download_button(
    label="Download Selected Sample Data (CSV)",
    data=csv_data.to_csv().encode('utf-8'),
    file_name=f"RER_{c1_iso}_{c2_iso}_{start_date}_to_{end_date}.csv",
    mime="text/csv"
)
