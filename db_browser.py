import os
import argparse
import yaml
import csv
from sqlalchemy import create_engine, inspect, MetaData, Table, select, asc, desc

def load_config(config_dir="config/default") -> dict:
    filepath = os.path.join(config_dir, ".config.yaml")
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Failed to parse {filepath}: {e}")
        return {}

def list_tables(inspector):
    tables = inspector.get_table_names()
    print("\n--- Tables in Database ---")
    for idx, table in enumerate(tables, 1):
        print(f"{idx}. {table}")
    print("--------------------------\n")
    return tables

def view_schema(inspector, table_name):
    columns = inspector.get_columns(table_name)
    print(f"\n--- Schema for table: {table_name} ---")
    print(f"{'Field Name':<30} | {'Field Type'}")
    print("-" * 50)
    for col in columns:
        print(f"{col['name']:<30} | {str(col['type'])}")
    print("-" * 50 + "\n")

def preview_table(engine, meta, table_name):
    table = Table(table_name, meta, autoload_with=engine)
    
    with engine.connect() as conn:
        pks = [c.name for c in table.primary_key]
        
        query_first = select(table)
        query_last = select(table)
        
        if pks:
            pk_col = getattr(table.c, pks[0])
            query_first = query_first.order_by(asc(pk_col))
            query_last = query_last.order_by(desc(pk_col))
        
        query_first = query_first.limit(10)
        query_last = query_last.limit(10)
        
        first_rows = conn.execute(query_first).fetchall()
        last_rows = conn.execute(query_last).fetchall()
        
        if pks:
            last_rows = last_rows[::-1]

    columns = [col.name for col in table.c]
    
    def print_rows(rows, title):
        print(f"\n--- {title} ({table_name}) ---")
        if not rows:
            print("No rows found.")
            return
            
        header = " | ".join(f"{str(c):<15}" for c in columns)
        print(header)
        print("-" * len(header))
        for row in rows:
            row_vals = []
            for val in row:
                val_str = str(val).replace('\n', ' ')
                if len(val_str) > 15:
                    val_str = val_str[:12] + "..."
                row_vals.append(f"{val_str:<15}")
            print(" | ".join(row_vals))
        print("-" * len(header) + "\n")

    print_rows(first_rows, "First 10 Rows")
    
    if len(first_rows) == 10:
        print_rows(last_rows, "Last 10 Rows (ordered by PK desc)")

def export_csv(engine, meta, table_name, out_file):
    table = Table(table_name, meta, autoload_with=engine)
    columns = [col.name for col in table.c]
    
    with engine.connect() as conn:
        result = conn.execute(select(table))
        
        with open(out_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            count = 0
            for row in result:
                writer.writerow(row)
                count += 1
                
    print(f"\nExported {count} rows to {out_file}\n")


def interactive_menu(engine):
    inspector = inspect(engine)
    meta = MetaData()
    while True:
        print("\n=== Database Browser ===")
        print("1. List tables")
        print("2. View table schema")
        print("3. Preview table contents")
        print("4. Export table to CSV")
        print("5. Exit")
        choice = input("Select an option: ").strip()
        
        if choice == '1':
            list_tables(inspector)
        elif choice == '2':
            tables = list_tables(inspector)
            idx = input("Select table number: ").strip()
            try:
                t_name = tables[int(idx)-1]
                view_schema(inspector, t_name)
            except (ValueError, IndexError):
                print("Invalid selection.")
        elif choice == '3':
            tables = list_tables(inspector)
            idx = input("Select table number: ").strip()
            try:
                t_name = tables[int(idx)-1]
                preview_table(engine, meta, t_name)
            except (ValueError, IndexError):
                print("Invalid selection.")
        elif choice == '4':
            tables = list_tables(inspector)
            idx = input("Select table number: ").strip()
            try:
                t_name = tables[int(idx)-1]
                out_path = input(f"Enter output file path (default: {t_name}.csv): ").strip()
                if not out_path:
                    out_path = f"{t_name}.csv"
                export_csv(engine, meta, t_name, out_path)
            except (ValueError, IndexError):
                print("Invalid selection.")
        elif choice == '5':
            print("Exiting...")
            break
        else:
            print("Invalid option. Try again.")

def main():
    parser = argparse.ArgumentParser(description="Database Browser Helper")
    parser.add_argument("--config-dir", default="config/default", help="Path to config directory")
    args = parser.parse_args()

    config = load_config(args.config_dir)
    db_url = config.get("database", {}).get("url", "sqlite:///data/trading_farm.db")
    
    print(f"Connecting to database at {db_url}")
    engine = create_engine(db_url)
    
    try:
        interactive_menu(engine)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
