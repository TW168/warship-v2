"""
database.py — Database connection factory for Warship.

Provides a SQLAlchemy engine connected to the MySQL warship database.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def connect_to_database(dbms: str = "mysql") -> Engine:
    """
    Connect to the Warship database using hardcoded connection information.

    Parameters:
        dbms (str): The database management system to use (default: 'mysql').

    Returns:
        sqlalchemy.engine.Engine: An engine object used to execute SQL queries.
    """
    # Hardcoded connection information for the Warship MySQL database
    user = "root"
    password = "n1cenclean"
    host = "172.17.15.228"
    port = 3306
    database = "warship"

    # Build the connection string using the specified DBMS and mysql-connector-python driver
    connection_string = f"{dbms}+mysqlconnector://{user}:{password}@{host}:{port}/{database}"

    # pool_pre_ping=True: test each pooled connection before use; silently reconnects
    # if MySQL closed it (e.g. after wait_timeout). Prevents the "works after reload"
    # 500-error pattern caused by stale connections in the pool.
    # pool_recycle=1800: force-recycle connections older than 30 min as an extra safeguard.
    engine = create_engine(
        connection_string,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    return engine
