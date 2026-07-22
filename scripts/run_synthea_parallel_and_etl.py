import concurrent.futures
import subprocess
import os
import shutil
import glob
import time

SYNTHEA_DIR = "/Users/kyh/Workspace/Broadsea/data/synthea/synthea"
FINAL_OUT_DIR = os.path.join(SYNTHEA_DIR, "output", "csv")
NUM_PATIENTS_TOTAL = 10000
NUM_WORKERS = 10

def run_batch(batch_id):
    num_patients = NUM_PATIENTS_TOTAL // NUM_WORKERS
    out_dir = os.path.join(SYNTHEA_DIR, f"output_parallel_{batch_id}")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    print(f"Starting batch {batch_id} for {num_patients} patients...")
    cmd = [
        "java",
        "-Xmx2g",
        "-jar", "build/libs/synthea-with-dependencies.jar",
        "-m", "artemis_leader", 
        "-p", str(num_patients),
        "--exporter.csv.export=true",
        "--exporter.fhir.export=false",
        "--exporter.hospital.fhir.export=false",
        "--exporter.practitioner.fhir.export=false",
        f"--exporter.baseDirectory={out_dir}"
    ]
    subprocess.run(cmd, cwd=SYNTHEA_DIR, check=True)
    return out_dir

def merge_csvs(dirs, final_dir):
    print("Merging CSVs...")
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    os.makedirs(final_dir, exist_ok=True)
    
    csv_types = set()
    for d in dirs:
        for f in glob.glob(os.path.join(d, "csv", "*.csv")):
            csv_types.add(os.path.basename(f))
            
    for csv_file in csv_types:
        final_path = os.path.join(final_dir, csv_file)
        with open(final_path, 'w') as fout:
            header_written = False
            for d in dirs:
                path = os.path.join(d, "csv", csv_file)
                if not os.path.exists(path):
                    continue
                with open(path, 'r') as fin:
                    lines = fin.readlines()
                    if not lines:
                        continue
                    if not header_written:
                        fout.write(lines[0])
                        header_written = True
                    fout.writelines(lines[1:])
    print(f"Merged CSVs saved to {final_dir}")

def run_etl():
    print("Copying to Docker...")
    subprocess.run(["docker", "exec", "broadsea-atlasdb", "rm", "-rf", "/tmp/synthea_csv"], check=True)
    subprocess.run(["docker", "cp", f"{SYNTHEA_DIR}/output/csv", "broadsea-atlasdb:/tmp/synthea_csv"], check=True)
    
    print("Loading into Native Tables...")
    with open("/Users/kyh/Workspace/Broadsea/artemis/scripts/load_synthea_benchmark.sql", "r") as f:
        subprocess.run(["docker", "exec", "-i", "broadsea-atlasdb", "psql", "-U", "postgres", "-d", "postgres"], stdin=f, check=True)
        
    print("Running full OMOP ETL conversion...")
    subprocess.run(["bash", "scripts/run_etl_full.sh"], cwd="/Users/kyh/Workspace/Broadsea/artemis", check=True)

if __name__ == "__main__":
    start_time = time.time()
    
    # Run Synthea in parallel
    dirs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = [executor.submit(run_batch, i) for i in range(NUM_WORKERS)]
        for f in concurrent.futures.as_completed(futures):
            dirs.append(f.result())
            
    # Merge
    merge_csvs(dirs, FINAL_OUT_DIR)
    
    # Clean up temp dirs
    for d in dirs:
        shutil.rmtree(d)
        
    print(f"Synthea generation complete in {time.time() - start_time:.2f} seconds.")
    
    # ETL
    run_etl()
    print(f"Total time including ETL: {time.time() - start_time:.2f} seconds.")
