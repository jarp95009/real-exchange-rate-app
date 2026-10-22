import io
import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- Page Configuration ---
st.set_page_config(page_title="Real Exchange Rate Observer", layout="wide")

# Comprehensive list of IMF countries (ISO3) and the Euro Area (G163)
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
    "South Korea": "KOR",
    "China": "CHN",
    "India": "IND",
    "Argentina": "ARG",
    "Chile": "CHL",
    "Colombia": "COL",
    "Peru": "PER",
    "South Africa": "ZAF",
    "Sweden": "SWE",
    "Norway": "NOR",
    "Denmark": "DNK",
    "New Zealand": "NZL",
    "Singapore": "SGP",
    "Thailand": "THA",
    "Indonesia": "IDN",
    "Malaysia": "MYS",
    "Philippines": "PHL",
    "Turkey": "TUR",
    "Poland": "POL",
    "Hungary": "HUN",
    "Czechia": "CZE",
    "Israel": "ISR"
}

BASE_API_URL = "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA"


def _parse_imf_dates(date_series: pd.Series) -> pd.Series:
    """
    Converts IMF monthly date strings (e.g., '1976-M01' or '1976-01')
    into standard pandas Timestamps aligned to the start of the month.
    """
    cleaned = date_series.astype(str).str.replace("-M", "-", regex=False)
    return pd.to_datetime(cleaned, format="%Y-%m", errors="coerce")


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_imf_series(iso3: str, indicator: str) -> pd.Series:
    """
    Fetches monthly CPI or Exchange Rate series from the IMF SDMX 3.0 API
    starting from January 1976.
    - CPI key: {ISO3}.CPI._T.IX.M (Dataflow: CPI)
    - EXR key: {ISO3}.XDC_USD.PA_RT.M (Dataflow: ER)
    """
    if indicator == "CPI":
        dataflow = "CPI"
        key = f"{iso3}.CPI._T.IX.M"
    elif indicator == "EXR":
        dataflow = "ER"
        key = f"{iso3}.XDC_USD.PA_RT.M"
    else:
        return pd.Series(dtype=float)

    # SDMX 3.0 canonical URL structure with version wildcard (~) and time constraint
    url = f"{BASE_API_URL}/{dataflow}/~/{key}?c[TIME_PERIOD]=ge:1976-M01"

    # Attempt 1: Request clean SDMX-CSV directly
    try:
        resp = requests.get(
            url,
            headers={"Accept": "text/csv", "User-Agent": "Python-Streamlit-RER-App/1.0"},
            timeout=25
        )
        if resp.status_code == 200 and "TIME_PERIOD" in resp.text:
            df_raw = pd.read_csv(io.StringIO(resp.text))
            if not df_raw.empty and "OBS_VALUE" in df_raw.columns:
                df_raw["Date"] = _parse_imf_dates(df_raw["TIME_PERIOD"])
                df_raw["Value"] = pd.to_numeric(df_raw["OBS_VALUE"], errors="coerce")
                df_raw = df_raw.dropna(subset=["Date", "Value"]).sort_values("Date")
                series = df_raw.set_index("Date")["Value"]
                # Deduplicate if multiple series versions exist and enforce monthly start
                series = series[~series.index.duplicated(keep="last")].resample("MS").first()
                return series
    except Exception:
        pass

    # Attempt 2: Fallback to SDMX-JSON (v2.0.0 / v1.0.0) if CSV header is rejected
    try:
        headers_json = {
            "Accept": "application/vnd.sdmx.data+json;version=2.0.0, application/json",
            "User-Agent": "Python-Streamlit-RER-App/1.0"
        }
        resp = requests.get(url, headers=headers_json, timeout=25)
        resp.raise_for_status()
        payload = resp.json()

        data_block = payload.get("data", payload)
        datasets = data_block.get("dataSets", [])
        if not datasets:
            return pd.Series(dtype=float)

        series_dict = datasets[0].get("series", {})
        if not series_dict:
            return pd.Series(dtype=float)

        obs_dict = next(iter(series_dict.values())).get("observations", {})

        # Locate time period dimension in SDMX 3.0 or 2.1 structure
        structures = data_block.get("structures", [data_block.get("structure", {})])
        obs_dims = structures[0].get("dimensions", {}).get("observation", [])
        time_values = []
        for dim in obs_dims:
            if dim.get("id") == "TIME_PERIOD" or "values" in dim:
                time_values = dim.get("values", [])
                break

        records = []
        for idx_str, val_list in obs_dict.items():
            idx = int(idx_str)
            if idx < len(time_values) and val_list and val_list[0] is not None:
                period_str = time_values[idx].get("id") or time_values[idx].get("name")
                records.append((period_str, float(val_list[0])))

        if not records:
            return pd.Series(dtype=float)

        df_json = pd.DataFrame(records, columns=["TIME_PERIOD", "Value"])
        df_json["Date"] = _parse_imf_dates(df_json["TIME_PERIOD"])
        df_json = df_json.dropna(subset=["Date", "Value"]).sort_values("Date")
        series = df_json.set_index("Date")["Value"]
        return series[~series.index.duplicated(keep="last")].resample("MS").first()

    except Exception as e:
        st.warning(f"Could not retrieve {indicator} data for {iso3}: {e}")
        return pd.Series(dtype=float)


# --- UI Header & Country Selection ---
st.title("Real Exchange Rate (RER) Observer")
st.markdown(
    "Analyze monthly **Nominal** and **Real Exchange Rates** using IMF SDMX 3.0 data "
    "(from January 1976 where available)."
)

col1, col2 = st.columns(2)
country_list = list(COUNTRY_CODES.keys())

with col1:
    c1_name = st.selectbox("Country 1 (Base Currency)", options=country_list, index=0)
with col2:
    c2_name = st.selectbox("Country 2 (Quote / Target Currency)", options=country_list, index=1)

c1_iso = COUNTRY_CODES[c1_name]
c2_iso = COUNTRY_CODES[c2_name]

if c1_iso == c2_iso:
    st.error("Please select two different countries to compare.")
    st.stop()

# --- Fetch & Align Data ---
with st.spinner(f"Fetching monthly CPI and Exchange Rate data for {c1_name} and {c2_name}..."):
    p1_series = fetch_imf_series(c1_iso, "CPI")
    p2_series = fetch_imf_series(c2_iso, "CPI")

    # Local currency per USD. For USA, 1 USD = 1 USD exactly, with fallback to API.
    exr1_series = fetch_imf_series(c1_iso
