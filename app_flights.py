import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime, timedelta
import random
import requests
import os

DB_NAME = 'flight_tracker.db'

# ==========================================
# 1. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            airline TEXT,
            destination TEXT,
            source TEXT,
            price REAL,
            checked_bags INTEGER,
            stops INTEGER,
            url TEXT
        )
    ''')
    
    c.execute('SELECT COUNT(*) FROM flights')
    if c.fetchone()[0] == 0:
        _generate_mock_data(conn)
        
    conn.commit()
    return conn

def _generate_mock_data(conn):
    """Generates baseline historical data."""
    airlines = ['Etihad Airways', 'Air India', 'Qatar Airways', 'British Airways']
    destinations = ['MIA', 'MCO', 'JAX'] 
    now = datetime.now()
    c = conn.cursor()
    for i in range(48):
        timestamp = now - timedelta(minutes=30 * (48 - i))
        for dest in destinations:
            price = random.uniform(950, 1500) if dest != 'JAX' else random.uniform(1300, 1800)
            dummy_url = f"https://www.google.com/travel/flights?q=Flights%20from%20BLR%20to%20{dest}"
            c.execute('''
                INSERT INTO flights (timestamp, airline, destination, source, price, checked_bags, stops, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp.strftime('%Y-%m-%d %H:%M:%S'), random.choice(airlines), dest, 'Google Flights', round(price, 2), 2, 1, dummy_url))

# ==========================================
# 2. LIVE API FETCHER (SERPAPI)
# ==========================================
def fetch_live_pricing(api_key):
    destinations = ['MIA', 'MCO', 'JAX']
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    progress_text = st.sidebar.empty()
    
    for dest in destinations:
        progress_text.text(f"Fetching BLR ➔ {dest}...")
        
        params = {
            "engine": "google_flights",
            "departure_id": "BLR",
            "arrival_id": dest,
            "outbound_date": "2026-08-20",
            "return_date": "2027-01-20",
            "currency": "USD",
            "hl": "en",
            "api_key": api_key
        }
        
        try:
            response = requests.get("https://serpapi.com/search", params=params)
            response.raise_for_status()
            data = response.json()
            
            # Combine Best and Other flights to ensure a robust pool
            best_flights = data.get('best_flights', [])
            other_flights = data.get('other_flights', [])
            all_flights = best_flights + other_flights
            
            if len(all_flights) > 0:
                # Remove flights with missing prices so the sorter doesn't crash
                valid_flights = [f for f in all_flights if isinstance(f.get('price'), (int, float))]
                
                # Sort the combined list by price BEFORE inserting into the DB
                sorted_flights = sorted(valid_flights, key=lambda x: x.get('price', float('inf')))
                
                # Extract the shareable Google Flights URL
                flight_url = data.get('search_metadata', {}).get('google_flights_url', f"https://www.google.com/travel/flights?q=Flights%20from%20BLR%20to%20{dest}")
                
                # Take the top 5 cheapest flights for this specific destination
                for flight in sorted_flights[:5]:
                    price = flight.get('price')
                    
                    flights_list = flight.get('flights', [])
                    if flights_list:
                        airline = flights_list[0].get('airline', 'Unknown Airline')
                        stops = len(flights_list) - 1 
                    else:
                        airline = 'Unknown Airline'
                        stops = 1
                    
                    c.execute('''
                        INSERT INTO flights (timestamp, airline, destination, source, price, checked_bags, stops, url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (now, airline, dest, 'Google Flights', price, 2, stops, flight_url))
            else:
                st.sidebar.warning(f"No flights found for {dest}.")
                
        except Exception as e:
            st.sidebar.error(f"Error fetching {dest}: {e}")
            
    progress_text.text("✅ Live fetch complete!")
    conn.commit()
    conn.close()

# ==========================================
# 3. DATA LOADING (SELF-HEALING)
# ==========================================
@st.cache_data(ttl=300)
def load_data():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM flights", conn)
    
    # --- SELF-HEALING SCHEMA ---
    # If the user's DB is from an older version and missing the 'url' column, add it!
    if 'url' not in df.columns:
        df['url'] = "https://www.google.com/travel/flights"
        try:
            c = conn.cursor()
            c.execute("ALTER TABLE flights ADD COLUMN url TEXT DEFAULT 'https://www.google.com/travel/flights'")
            conn.commit()
        except Exception:
            pass # Ignore if it somehow fails
            
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        # Safely apply timezone conversions
        try:
            df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
        except Exception:
            pass
            
    conn.close()
    return df

# ==========================================
# 4. MAIN APPLICATION RENDER
# ==========================================
st.set_page_config(page_title="Flight Price Tracker", page_icon="✈️", layout="wide")

init_db()
raw_df = load_data()

st.title("✈️ BLR to Florida Price Tracker")
st.markdown("Monitoring routes to MIA, MCO, and JAX for **Aug 2026** departures.")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ API Configuration")
has_secret_key = "SERPAPI_KEY" in st.secrets

if not has_secret_key:
    manual_api_key = st.sidebar.text_input("SerpApi Key", type="password", placeholder="Paste your key here...")
else:
    st.sidebar.success("✅ API Key safely loaded from Secrets.")
    manual_api_key = None

st.sidebar.divider()
st.sidebar.header("🔄 Live Controls")

if st.sidebar.button("Fetch Live Prices Now", use_container_width=True, type="primary"):
    active_key = st.secrets["SERPAPI_KEY"] if has_secret_key else manual_api_key
    if not active_key:
        st.sidebar.error("⚠️ Please enter your SerpApi key or add it to your secrets.")
    else:
        fetch_live_pricing(active_key)
        st.cache_data.clear()      
        st.rerun()                 

# --- DATABASE RESET ---
st.sidebar.divider()
st.sidebar.header("⚠️ System")
if st.sidebar.button("🗑️ Reset Database", use_container_width=True):
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        st.cache_data.clear()
        st.rerun()

# --- SIDEBAR FILTERS ---
st.sidebar.divider()
st.sidebar.header("📊 Filter Options")
if not raw_df.empty:
    selected_dests = st.sidebar.multiselect("Destinations", options=raw_df['destination'].unique(), default=raw_df['destination'].unique())
else:
    selected_dests = []
    
require_two_bags = st.sidebar.checkbox("🎒 Show 2+ Checked Bags Only", value=True)

filtered_df = raw_df[(raw_df['destination'].isin(selected_dests))]
if require_two_bags and not filtered_df.empty:
    filtered_df = filtered_df[filtered_df['checked_bags'] >= 2]

# ==========================================
# 5. DASHBOARD METRICS & CHARTS
# ==========================================
if filtered_df.empty:
    st.warning("No flight data matches your current filter criteria. Try fetching live prices!")
else:
    latest_time = filtered_df['timestamp'].max()
    latest_data = filtered_df[filtered_df['timestamp'] == latest_time]
    
    col1, col2, col3 = st.columns(3)
    global_min = raw_df['price'].min()
    filtered_min = filtered_df['price'].min()
    current_min = latest_data['price'].min() if not latest_data.empty else None
    
    with col1:
        st.metric("All-Time Lowest", f"${global_min:,.2f}")
    with col2:
        st.metric("Lowest Matching Filters", f"${filtered_min:,.2f}")
    with col3:
        if current_min:
            best_route = latest_data.loc[latest_data['price'].idxmin()]
