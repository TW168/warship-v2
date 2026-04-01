"""
Product Trend Analysis Service

Analyzes shipped product data via MySQL stored procedure sp_get_all_shipped_product()
to identify:
- Growth/decline trajectories
- Portfolio consolidation
- Top products and seasonality
- Volume trends and anomalies
"""

from datetime import datetime
from collections import defaultdict
from database import connect_to_database


def load_product_data_from_sp(
    site: str = 'AMJK',
    product_group: str = 'SW',
    start_date: str = '2010-01-01',
    end_date: str = '2026-03-31'
) -> list[dict]:
    """
    Load product shipment data via MySQL stored procedure sp_get_all_shipped_product().
    
    Returns list of dicts with columns:
    BL_Number, Truck_Appointment_Date, Site, Product_Group, 
    Product_Code, Unit_Freight, Carrier_ID, pallet_count, pick_weight
    """
    engine = connect_to_database()
    
    with engine.connect() as conn:
        dbapi_conn = conn.connection
        cursor = dbapi_conn.cursor(dictionary=True)
        
        # Call sp_get_all_shipped_product(site, product_group, start_date, end_date)
        cursor.callproc("sp_get_all_shipped_product", 
                       [site, product_group, start_date, end_date])
        
        rows = []
        for rs in cursor.stored_results():
            rows.extend(rs.fetchall())
        
        cursor.close()
    
    # Ensure numeric conversion
    for row in rows:
        if 'pick_weight' in row:
            row['pick_weight'] = int(row['pick_weight']) if row['pick_weight'] else 0
        if 'pallet_count' in row:
            row['pallet_count'] = int(row['pallet_count']) if row['pallet_count'] else 0
    
    return rows


def get_top_products(rows: list[dict], top_n: int = 10) -> list[dict]:
    """
    Get top N products by total weight across all time.
    
    Returns list of dicts:
    {
        'product_code': str,
        'total_weight': int,
        'shipment_count': int,
        'avg_weight': float
    }
    """
    product_stats = defaultdict(lambda: {
        'total_weight': 0, 'shipment_count': 0
    })
    
    for row in rows:
        product_code = row["Product_Code"]
        weight = row["pick_weight"]
        
        product_stats[product_code]['total_weight'] += weight
        product_stats[product_code]['shipment_count'] += 1
    
    # Add avg_weight and convert to list
    products = []
    for code, stats in product_stats.items():
        products.append({
            'product_code': code,
            'total_weight': stats['total_weight'],
            'shipment_count': stats['shipment_count'],
            'avg_weight': (
                stats['total_weight'] / stats['shipment_count']
            ) if stats['shipment_count'] > 0 else 0
        })
    
    # Sort by total_weight descending
    products.sort(key=lambda x: x['total_weight'], reverse=True)
    return products[:top_n]


def get_monthly_trend(rows: list[dict], product_code: str = None) -> list[dict]:
    """
    Get monthly trend data for a single product or all products combined.
    
    If product_code is None, aggregates all products by month.
    Otherwise returns monthly series for specific product.
    
    Returns list of dicts:
    {
        'year_month': str (YYYY-MM),
        'total_weight': int,
        'shipment_count': int,
        'avg_weight': float
    }
    """
    monthly = defaultdict(lambda: {
        'total_weight': 0, 'shipment_count': 0
    })
    
    for row in rows:
        if product_code and row["Product_Code"] != product_code:
            continue
        
        try:
            dt = datetime.strptime(row["Truck_Appointment_Date"], "%Y-%m-%d")
            year_month = dt.strftime("%Y-%m")
        except:
            continue
        
        weight = row["pick_weight"]
        monthly[year_month]['total_weight'] += weight
        monthly[year_month]['shipment_count'] += 1
    
    # Convert to sorted list
    result = []
    for month in sorted(monthly.keys()):
        stats = monthly[month]
        result.append({
            'year_month': month,
            'total_weight': stats['total_weight'],
            'shipment_count': stats['shipment_count'],
            'avg_weight': (
                stats['total_weight'] / stats['shipment_count']
            ) if stats['shipment_count'] > 0 else 0
        })
    
    return result


def get_product_diversity_over_time(rows: list[dict]) -> list[dict]:
    """
    Get count of unique products shipped per month.
    
    Returns list of dicts:
    {
        'year_month': str,
        'unique_products': int,
        'total_weight': int,
        'total_shipments': int
    }
    """
    monthly = defaultdict(lambda: {
        'products': set(),
        'total_weight': 0,
        'total_shipments': 0
    })
    
    for row in rows:
        try:
            dt = datetime.strptime(row["Truck_Appointment_Date"], "%Y-%m-%d")
            year_month = dt.strftime("%Y-%m")
        except:
            continue
        
        monthly[year_month]['products'].add(row["Product_Code"])
        monthly[year_month]['total_weight'] += row["pick_weight"]
        monthly[year_month]['total_shipments'] += 1
    
    result = []
    for month in sorted(monthly.keys()):
        stats = monthly[month]
        result.append({
            'year_month': month,
            'unique_products': len(stats['products']),
            'total_weight': stats['total_weight'],
            'total_shipments': stats['total_shipments']
        })
    
    return result


