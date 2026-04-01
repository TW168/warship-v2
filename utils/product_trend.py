import pandas as pd
from datetime import datetime
from pathlib import Path

def build_product_trend_model(csv_path: str) -> pd.DataFrame:
    """
    Build a product weight trend model from product_3y.csv.
    
    Returns:
        DataFrame with columns: year_month, product_code, total_weight_lbs, shipment_count
    """
    # Read CSV [Source: raw_data/product_3y.csv]
    df = pd.read_csv(csv_path)
    
    # Parse date and extract year-month
    df['Truck_Appointment_Date'] = pd.to_datetime(df['Truck_Appointment_Date'])
    df['year_month'] = df['Truck_Appointment_Date'].dt.strftime('%Y-%m')
    
    # Group by year_month and product_code, aggregate weight and BL count
    trend = df.groupby(['year_month', 'Product_Code']).agg({
        'pick_weight': 'sum',
        'BL_Number': 'count'
    }).reset_index()
    
    trend.columns = ['year_month', 'product_code', 'total_weight_lbs', 'shipment_count']
    
    # Sort by date, then by weight descending
    trend = trend.sort_values(['year_month', 'total_weight_lbs'], ascending=[True, False])
    
    return trend


def get_top_products_by_month(csv_path: str, top_n: int = 5) -> dict:
    """
    Get top N products by weight for each month.
    
    Returns:
        Dict: {year_month: [list of top products]}
    """
    trend = build_product_trend_model(csv_path)
    
    result = {}
    for month in trend['year_month'].unique():
        month_data = trend[trend['year_month'] == month].head(top_n)
        result[month] = month_data[['product_code', 'total_weight_lbs', 'shipment_count']].to_dict('records')
    
    return result


def get_product_trend_over_time(csv_path: str, product_code: str) -> pd.DataFrame:
    """
    Get weight trend for a specific product across all months.
    """
    trend = build_product_trend_model(csv_path)
    product_trend = trend[trend['product_code'] == product_code].sort_values('year_month')
    return product_trend


# Usage example
if __name__ == '__main__':
    csv_file = 'raw_data/product_3y.csv'
    
    # Build full trend
    trend_df = build_product_trend_model(csv_file)
    print("Full Product Trend by Year-Month:")
    print(trend_df.to_string())
    
    # Get top 5 products each month
    top_products = get_top_products_by_month(csv_file, top_n=5)
    print("\n\nTop 5 Products by Weight Each Month:")
    for month, products in top_products.items():
        print(f"\n{month}:")
        for p in products:
            print(f"  {p['product_code']}: {p['total_weight_lbs']:,} lbs ({p['shipment_count']} shipments)")
    
    """ # Example: track specific product
    product_to_track = 'ELB0401979000AM-40EX'
    print(f"\n\nTrend for {product_to_track}:")
    single_product = get_product_trend_over_time(csv_file, product_to_track)
    print(single_product.to_string()) """