# Real Exchange Rate (RER) Observer

A Streamlit application designed to fetch, calculate, and visualize the Real Exchange Rate (RER) and Nominal Exchange Rate $S(t)$ between two selected countries utilizing monthly CPI and Exchange Rate data from the International Monetary Fund (IMF) SDMX 3.0 API.

## Features
- **Dynamic Data Sourcing:** Pulls monthly CPI and local-currency-per-USD data directly from the IMF API starting from January 1976.
- **RER Calculation:** Computes the structural real exchange rate as $RER(t) = S(t) \times (P_1(t) / P_2(t))$.
- **Real Index Normalization:** Automatically calculates $RER^*$ (the average over your user-selected date range) and plots the Real Index scaled to 100.
- **Interactive Visualizations:** View Real, Nominal, or Both indices concurrently using dual-axis interactive Plotly charts.
- **Data Export:** Download the precise calculations for the filtered sample period natively as a CSV.

## Prerequisites
- Python 3.12 
- Git (for version control and deployment)

## Installation

1. **Clone the repository:**
   ```bash
   git clone <your-repository-url>
   cd <your-repository-directory>
