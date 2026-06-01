import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime, timedelta
import random
import os
import subprocess

DB_NAME = 'flight_tracker.db'

# ==========================================
# OPTIONAL: AUTO-INSTALLER (Commented Out)
# ==========================================
# If you want the Python script to automatically execute the commands inside 
# the "instructions.txt" file before running, you can uncomment this block:
#
# if os.path.exists("instructions.txt"):
#     with open("instructions.txt", "r") as f:
#         for line in f:
#             cmd = line.strip()
#             if cmd:
#                 subprocess.run(cmd, shell=True)

# ==========================================
# 1. DATABASE & MOCK DATA SETUP
# ==========================================
def init_db():
    """Initializes the database and populates it with sample data if empty."""
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
            stops INTEGER
        )
    ''')
    
    c.execute('SELECT COUNT(*) FROM flights')
    if c.fetchone()[0] == 0:
        _generate_mock_data(conn)
        
    conn.commit()
    return conn

def _generate_mock_data(conn):
    """Generates 48 hours of mock data running at 30-min intervals."""
    airlines = ['Etihad Airways', 'Air India', 'Qatar Airways', 'Emirates', 'British Airways', 'Delta']
    destinations = ['ATL', 'MIA', 'MCO', 'JAX']
    sources = ['Google Flights', 'Skyscanner', 'Momondo', 'Cheapflights']
    
    now = datetime.now()
    c = conn.cursor()
    
    for i in range(96):
        timestamp = now - timedelta(minutes=30 * (96 - i))
        for dest in destinations:
            for source in sources:
                price = random.uniform(950, 1500) if dest != 'JAX' else random.uniform(1300, 1800)
                price = price + random.uniform(-20, 20)
                bags = random.choice([0, 1, 2, 2])
                stops = random.choice([1, 2])
                airline = random.choice(airlines)
                
                c.execute('''
                    INSERT INTO flights (timestamp, airline, destination, source, price, checked_bags, stops)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (timestamp.strftime('%Y-%m-%d %H:%M:%S'), airline, dest, source, round(price, 2), bags, stops))

# ==========================================
# 2. DATA LOADING & FILTERING
# ==========================================
@st.cache_data(ttl=300)
def load_data():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM flights", conn)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    conn.close()
    return df

# ==========================================
# 3. STREAMLIT UI BUILDER
# ==========================================
st.set_page_config(page_title="Flight Price Tracker", page_icon="✈️", layout="wide")

init_db()
raw_df = load_data()

st.title("✈️ BLR to US Southeast Price Tracker")
st.markdown("Monitoring routes to ATL, MIA, MCO, and JAX for **Aug 2026** departures.")

# --- INSTRUCTIONS FILE READER ---
st.sidebar.header("System")
if os.path.exists("instructions.txt"):
    with open("instructions.txt", "r") as f:
        instructions_text = f.read()
    
    with st.sidebar.expander("🛠️ Installation Instructions", expanded=False):
        st.markdown("Required libraries to run this tracker:")
        st.code(instructions_text, language="bash")
else:
    with st.sidebar.expander("🛠️ Installation Instructions", expanded=False):
        st.warning("No 'instructions.txt' file found in the directory.")
        st.markdown("Standard requirements:")
        st.code("pip install streamlit pandas plotly", language="bash")

st.sidebar.divider()

# --- Sidebar Filters ---
st.sidebar.header("Filter Options")
selected_dests = st.sidebar.multiselect(
    "Destinations", 
    options=raw_df['destination'].unique(),
    default=raw_df['destination'].unique()
)

selected_sources = st.sidebar.multiselect(
    "Data Source (Aggregator)", 
    options=raw_df['source'].unique(),
    default=raw_df['source'].unique()
)

require_two_bags = st.sidebar.checkbox("🎒 Show 2+ Checked Bags Only", value=True)

filtered_df = raw_df[
    (raw_df['destination'].isin(selected_dests)) & 
    (raw_df['source'].isin(selected_sources))
]

if require_two_bags:
    filtered_df = filtered_df[filtered_df['checked_bags'] >= 2]

# ==========================================
# 4. DASHBOARD METRICS & CHARTS
# ==========================================
if filtered_df.empty:
    st.warning("No flight data matches your current filter criteria.")
else:
    latest_time = filtered_df['timestamp'].max()
    latest_data = filtered_df[filtered_df['timestamp'] == latest_time]
    
    col1, col2, col3 = st.columns(3)
    
    global_min = raw_df['price'].min()
    filtered_min = filtered_df['price'].min()
    current_min = latest_data['price'].min() if not latest_data.empty else None
    
    with col1:
        st.metric("All-Time Lowest (Any Bag/Dest)", f"${global_min:,.2f}")
    with col2:
        st.metric("Lowest Matching Filters", f"${filtered_min:,.2f}")
    with col3:
        if current_min:
            best_route = latest_data.loc[latest_data['price'].idxmin()]
            st.metric(f"Current Best ({best_route['destination']})", f"${current_min:,.2f}", 
                      delta=f"Found via {best_route['source']}", delta_color="off")

    st.divider()

    st.subheader("Price Trends (Last 48 Hours)")
    trend_df = filtered_df.groupby(['timestamp', 'destination'])['price'].min().reset_index()
    
    fig = px.line(
        trend_df, 
        x='timestamp', 
        y='price', 
        color='destination',
        markers=True,
        title="Lowest Available Price per Destination Over Time",
        labels={'price': 'Price (USD)', 'timestamp': 'Time Logged'}
    )
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    st.subheader(f"Top 5 Cheapest Flights (As of {latest_time.strftime('%I:%M %p')})")
    
    if not latest_data.empty:
        top_5 = latest_data.sort_values(by='price', ascending=True).head(5)
        
        display_df = top_5[['airline', 'destination', 'price', 'checked_bags', 'stops', 'source']].copy()
        display_df.columns = ['Airline', 'Destination', 'Price (USD)', 'Checked Bags', 'Stops', 'Source']
        display_df['Price (USD)'] = display_df['Price (USD)'].apply(lambda x: f"${x:,.2f}")
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No data available for the most recent interval with the current filters.")
