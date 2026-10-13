import json
import csv
import os
from datetime import datetime

def export_results_to_csv(json_file, csv_file):
    # Read the JSON file
    with open(json_file, 'r') as f:
        results = json.load(f)
    
    # Define CSV headers
    headers = [
        'task_id',
        'task_type',
        'reward',
        'total_cost',
        'num_turns',
        'total_tokens',
        'prompt_tokens',
        'completion_tokens',
        'success_rate'
    ]
    
    # Prepare data for CSV
    rows = []
    for result in results:
        # Calculate total tokens
        total_tokens = sum(result['agent_info']['usage']['total_tokens'])
        prompt_tokens = sum(result['agent_info']['usage']['prompt_tokens'])
        completion_tokens = sum(result['agent_info']['usage']['completion_tokens'])
        
        row = {
            'task_id': result['task_id'],
            'task_type': result['task_type'],
            'reward': result['reward'],
            'total_cost': result['agent_info']['total_cost'],
            'num_turns': result['agent_info']['num_turns'],
            'total_tokens': total_tokens,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'success_rate': 'Yes' if result['reward'] == 1 else 'No'
        }
        rows.append(row)
    
    # Write to CSV
    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"Results exported to {csv_file}")

def main():
    # Get all JSON files in the results directory
    results_dir = "results_tc_natural_1002"
    if not os.path.exists(results_dir):
        print(f"Directory {results_dir} not found")
        return
    
    # Create stats directory if it doesn't exist
    stats_dir = "stats"
    if not os.path.exists(stats_dir):
        os.makedirs(stats_dir)
    
    # Process each JSON file
    for filename in os.listdir(results_dir):
        if filename.endswith('.json'):
            json_path = os.path.join(results_dir, filename)
            csv_filename = f"{os.path.splitext(filename)[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            csv_path = os.path.join(stats_dir, csv_filename)
            export_results_to_csv(json_path, csv_path)

if __name__ == "__main__":
    main() 