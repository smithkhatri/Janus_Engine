import os
import json
import csv

def build_data():
    log_dir = "bot_logs"
    dashboard_dir = "dashboard"
    
    if not os.path.exists(log_dir):
        print("No bot_logs found.")
        return

    all_records = []
    for file in sorted(os.listdir(log_dir)):
        if file.startswith("executions_") and file.endswith(".csv"):
            file_path = os.path.join(log_dir, file)
            with open(file_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert numeric fields
                    for key in ['k_price', 'p_price', 'intended_qty', 'theoretical_profit', 
                              'k_fill_qty', 'k_fill_time_ms', 'p_fill_qty', 'p_fill_time_ms', 
                              'unwind_pnl', 'net_realized_pnl']:
                        if key in row and row[key]:
                            try:
                                row[key] = float(row[key])
                            except ValueError:
                                pass
                    all_records.append(row)
                    
    out_path = os.path.join(dashboard_dir, "data.json")
    with open(out_path, "w") as f:
        json.dump(all_records, f)
        
    print(f"✅ Successfully bundled {len(all_records)} trades into {out_path} for GitHub Pages.")

if __name__ == "__main__":
    build_data()
