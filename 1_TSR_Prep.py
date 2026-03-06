# file path: /home/tony/warship/whsh/pages/1_TSR Prep.py

from datetime import datetime
import streamlit as st
import pandas as pd
from helper import extract_EZ_rpt_date_time, connect_to_database, clean_uploaded_IPG_EZ, avail_to_ship, convert_df_to_csv, avail_to_ship_AM
import numpy as np
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from sqlalchemy import text


engine = connect_to_database(dbms="mysql")

st.set_page_config(page_title="Warship-TSR Prep", page_icon="🚚", layout='wide')

st.markdown("# TSR Prep")
st.write(
    """ Update three times a day at approximately 8 AM, 12 PM, and 4 PM CST. """
)


with st.expander("Upload", expanded=True):
    with st.form("upload_form"):
        col1, col2 = st.columns(2)
        with col1:
            uploaded_file = st.file_uploader(
                'Choose a file (e.g. AmTopp Current Pickup Detail Report as of yyyy-m-dd H#M#.xlsx)', 
                accept_multiple_files=False, 
                type=["xlsx", "xls"], 
                key="uploaded_file_key", 
                help="This app only accept Excel file from IPG EZ Report / Inteplast Management Improvement <ezreport@inteplast.com>" 
            )
        with col2:
            pass

        submitted = st.form_submit_button("Upload")
        if submitted and uploaded_file is not None:
            file_name = uploaded_file.name
            file_size = uploaded_file.size
            # Check whether the file already exists using a temporary connection
            with engine.connect() as conn:
                result = conn.exec_driver_sql(
                    "SELECT * FROM ipg_ez WHERE file_name = %s AND file_size = %s", 
                    (file_name, file_size)
                ).fetchone()
            st.write(file_name)
            if result:
                st.error("This file has already been uploaded.")
            else:
                # Extract file data and process the file
                rpt_date_time = extract_EZ_rpt_date_time(file_name)
                rpt_run_date = datetime.strptime(rpt_date_time[0], "%Y-%m-%d").date()
                rpt_run_time = datetime.strptime(rpt_date_time[1], "%H:%M").time()
                current_time = datetime.now()
                df = pd.read_excel(uploaded_file)
                cleaned_df = clean_uploaded_IPG_EZ(
                    df, rpt_run_date, rpt_run_time, file_name, file_size, current_time
                )
                # Append the data to the MySQL table using the engine (to_sql handles its own connection)
                cleaned_df['file_name'] = file_name
                cleaned_df['file_size'] = file_size
                cleaned_df.to_sql('ipg_ez', con=engine, if_exists='append', index=False)
                
with st.container():
    with st.expander("Ship list", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
             with engine.connect() as conn:
                # Extract distinct site from ipg_ez convert result to list and display items in select box
                site_result = conn.execute(text("SELECT distinct Site FROM ipg_ez;")).fetchall()
                items = [str(item[0]) for item in site_result]
                selected_site = st.selectbox("Choose a Site", items)
            
                # Extract distinct group from ipg_ez, convert result to list and display items in select box
                group_result = conn.execute(text(("select distinct Product_Group from ipg_ez;"))).fetchall()
                items = [str(item[0]) for item in group_result]
                selected_group = st.selectbox("Choose a Group", items)
        with col2:
            # Use calendar to repesent  rpt_run_date from ipg_ez
            selected_date = st.date_input("Choose Report Date" )
            # Extract distinct rpt_run_time from ipg_ez, convert result to list and display items in select box
            selected_time = st.selectbox("Choose a time", options=["09:00:00", "12:00:00", "16:00:00"])
              
        avail_to_ship_df= avail_to_ship(selected_site, selected_group, selected_date, selected_time)
        sum_WGT = avail_to_ship_df['WGT'].sum()
        st.write(f"Availiable to ship {sum_WGT:,.0f} (lbs)")
        st.dataframe(avail_to_ship_df, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
            label="Download",
            data=convert_df_to_csv(avail_to_ship_df),
            file_name='TSR_Prep_List.csv',
            mime='text/csv',
            )
            with col2:
                pass
              
try:
    with st.container():
        with st.expander('Map (each blue circle is 50 miles radius)', expanded=True):
            def add_tooltip(row, marker):
                tooltip = "{}<br>{}<br>Weight: {}<br>Pallets: {}".format(
                    row["BL_Number"], row["Customer"], row["WGT"], row["PLT"])
                folium.Marker(location=[row["lat"], row["lon"]], tooltip=tooltip).add_to(marker)
                # Adding circle with 50 miles radius
                folium.Circle(location=[row["lat"], row["lon"]], radius=80467.2, color='blue', fill_opacity=0.1).add_to(m)
               
            df = avail_to_ship_df.dropna(subset=['lat', 'lon'])
            
            # Create the map
            m = folium.Map(location=[df["lat"].mean(), df["lon"].mean()], zoom_start=5)

            # Add marker cluster to the map
            marker_cluster = MarkerCluster().add_to(m)

            # Add each point to the marker cluster with tooltip
            for index, row in df.iterrows():
                if not pd.isna(row["lat"]) and not pd.isna(row["lon"]):
                    add_tooltip(row, marker_cluster)

            # Display the map in Streamlit
            st_data = st_folium(m, width=1200)
            
except Exception as e:
    print(e)
    st.warning(f"No data available or all shipment are scheduled")






