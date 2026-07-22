import psycopg2
import json
import os
import math

# Output path
OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 
    "../src/agents/agent2/resources/concept_priority_db.json"
)

# Connect to DB
try:
    conn = psycopg2.connect(
        host='localhost', port=5432, 
        dbname='postgres', user='postgres', password='mypass'
    )
    cur = conn.cursor()
    SCHEMA = 'synthea_cdm'
except Exception as e:
    print(f"DB Connection failed: {e}")
    exit(0) # Exit gracefully if no DB (e.g. CI/CD)

domains = {
    'Measurement': 'measurement',
    'Procedure': 'procedure_occurrence',
    'Condition': 'condition_occurrence',
    'Drug': 'drug_exposure'
}

stats = {}
MAX_BOOST = -0.15  # Max boost for most frequent concepts

print('--- Querying Synthea Concept Frequencies ---')
for domain, table in domains.items():
    concept_col = f'{table.split("_")[0]}_concept_id'
    if domain == 'Drug': concept_col = 'drug_concept_id'
    
    # Get top 500 concepts per domain
    query = f'''
        SELECT {concept_col}, COUNT(*) 
        FROM {SCHEMA}.{table} 
        WHERE {concept_col} != 0
        GROUP BY {concept_col} 
        ORDER BY COUNT(*) DESC 
        LIMIT 500
    '''
    try:
        cur.execute(query)
        rows = cur.fetchall()
        
        if not rows:
            continue
            
        max_count = rows[0][1]
        print(f"[{domain}] Found {len(rows)} concepts. Max count: {max_count}")
        
        for r in rows:
            cid = r[0]
            count = r[1]
            
            # Logarithmic scaling for boost
            # Score = -0.05 to -0.15 based on frequency bucket
            # Normalized against domain max
            ratio = math.log10(count) / math.log10(max_count) if max_count > 1 else 0
            boost = -0.05 - (0.1 * ratio) 
            
            stats[str(cid)] = round(boost, 3)
            
    except Exception as e:
        print(f'Error querying {domain}: {e}')

print(f'\nTotal concepts weighted: {len(stats)}')

# Create dir if not exists
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

with open(OUTPUT_FILE, "w") as f:
    json.dump(stats, f, indent=2)

print(f"Saved to {OUTPUT_FILE}")
