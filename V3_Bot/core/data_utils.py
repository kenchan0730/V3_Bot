import pandas as pd


def normalize_columns(df):
    """Convert all column names to lowercase and return the transformed DataFrame."""
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(col).lower() for col in df.columns]
    return df
