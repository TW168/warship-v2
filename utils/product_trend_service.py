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


def aggregate_by_month_product(rows: list[dict]) -> dict:
    """
    Aggregate pick_weight and shipment_count by year_month + Product_Code.
    
    Returns dict:
    {
        'year_month': {
            'product_code': {
                'total_weight': int,
                'shipment_count': int,
                'avg_weight': float
            }
        }
    }
    """
    agg = defaultdict(lambda: defaultdict(lambda: {
        'total_weight': 0, 'shipment_count': 0
    }))
    
    for row in rows:
        # Parse date as YYYY-MM-DD, extract YYYY-MM
        try:
            dt = datetime.strptime(row["Truck_Appointment_Date"], "%Y-%m-%d")
            year_month = dt.strftime("%Y-%m")
        except:
            continue
        
        product_code = row["Product_Code"]
        weight = row["pick_weight"]
        
        agg[year_month][product_code]["total_weight"] += weight
        agg[year_month][product_code]["shipment_count"] += 1
    
    # Add avg_weight
    for month in agg:
        for product in agg[month]:
            agg[month][product]["avg_weight"] = (
                agg[month][product]["total_weight"] / 
                agg[month][product]["shipment_count"]
            ) if agg[month][product]["shipment_count"] > 0 else 0
    
    return dict(agg)


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


def get_product_growth_analysis(rows: list[dict], product_code: str) -> dict:
    """
    Analyze growth trajectory for a single product.
    
    Returns dict:
    {
        'product_code': str,
        'first_date': str (YYYY-MM-DD),
        'last_date': str (YYYY-MM-DD),
        'total_weight': int,
        'shipment_count': int,
        'early_6mo_weight': int,   # First 6 months
        'recent_6mo_weight': int,  # Last 6 months
        'growth_pct': float,
        'trend': 'growing' | 'stable' | 'declining'
    }
    """
    filtered = [r for r in rows if r["Product_Code"] == product_code]
    
    if not filtered:
        return None
    
    # Sort by date
    filtered.sort(key=lambda x: x["Truck_Appointment_Date"])
    
    first_date = filtered[0]["Truck_Appointment_Date"]
    last_date = filtered[-1]["Truck_Appointment_Date"]
    total_weight = sum(r["pick_weight"] for r in filtered)
    shipment_count = len(filtered)
    
    # Split into first/last 6 months
    first_cutoff = datetime.strptime(first_date, "%Y-%m-%d")
    early_cutoff = first_cutoff.replace(month=first_cutoff.month + 6) if first_cutoff.month <= 6 else first_cutoff.replace(year=first_cutoff.year + 1, month=first_cutoff.month - 6)
    
    early_6mo = sum(
        r["pick_weight"] for r in filtered
        if datetime.strptime(r["Truck_Appointment_Date"], "%Y-%m-%d") < early_cutoff
    )
    recent_6mo = sum(
        r["pick_weight"] for r in filtered
        if datetime.strptime(r["Truck_Appointment_Date"], "%Y-%m-%d") >= early_cutoff
    )
    
    growth_pct = 0
    if early_6mo > 0:
        growth_pct = ((recent_6mo - early_6mo) / early_6mo) * 100
    
    # Determine trend
    if growth_pct > 20:
        trend = "growing"
    elif growth_pct < -20:
        trend = "declining"
    else:
        trend = "stable"
    
    return {
        'product_code': product_code,
        'first_date': first_date,
        'last_date': last_date,
        'total_weight': total_weight,
        'shipment_count': shipment_count,
        'early_6mo_weight': early_6mo,
        'recent_6mo_weight': recent_6mo,
        'growth_pct': round(growth_pct, 1),
        'trend': trend
    }
