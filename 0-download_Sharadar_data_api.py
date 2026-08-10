# -*- coding: utf-8 -*-
"""
API-based variant of 0-download_Sharadar_data.py — no browser required.

Downloads the same Sharadar datasets through the official Nasdaq Data Link
bulk-export API (qopts.export=true), which returns a link to the exact same
zip snapshot the website's "Download Now" button serves. Unzipping, renaming
and post-processing behavior is identical to the original script.

Steps:
1. Prepares a clean download directory by deleting all existing files.
2. Requests a bulk-export snapshot for every dataset (with retries).
3. Streams each dataset's latest snapshot zip to disk (optionally waiting
   up to FRESH_WAIT_MINS for a fully up-to-date snapshot first).
4. Unzips all downloaded .zip files into the main download folder.
5. Renames CSVs and writes Parquet/Excel outputs.
"""
import os
import sys
import time
import zipfile
import argparse
import yaml
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from timeit import default_timer as timer

# --- User-Defined Imports ---
# The API key lives in config.py. QUANDL_TOKEN is the Nasdaq Data Link key
# (Quandl is Nasdaq Data Link's former name).
try:
    from config import NASDAQ_API_KEY
except ImportError:
    from config import QUANDL_TOKEN as NASDAQ_API_KEY

start = timer()

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================

DATASETS_TO_DOWNLOAD = [
    'SHARADAR/SF1', 'SHARADAR/SF2', 'SHARADAR/SF3', 'SHARADAR/EVENTS',
    'SHARADAR/SF3A', 'SHARADAR/SF3B', 'SHARADAR/SEP', 'SHARADAR/TICKERS',
    'SHARADAR/INDICATORS', 'SHARADAR/DAILY', 'SHARADAR/SP500',
    'SHARADAR/ACTIONS', 'SHARADAR/SFP', 'SHARADAR/METRICS'
]

API_BASE = 'https://data.nasdaq.com/api/v3/datatables'

# ==============================================================================
# --- HOUSE KEEPING ---
# ==============================================================================

# --- 1. Argument Parsing ---
is_interactive = len(sys.argv) == 1 or sys.argv[0].endswith('ipykernel_launcher.py')
parser = argparse.ArgumentParser(description="Configurable Sharadar Data Processing Pipeline (API version).")
parser.add_argument('--config', type=str, help='Path to the configuration YAML file.')

if is_interactive:
    print("Running in interactive mode, using default config: 'config/local_config.yml'")
    args = parser.parse_args(['--config', 'config/local_config.yml'])
else:
    args = parser.parse_args()

# --- 2. Load Configuration ---
print(f"Loading configuration from: {args.config}")
with open(args.config, "r") as f:
    config = yaml.safe_load(f)

# --- 3. Initialize Settings from Config ---
output_folder_path = Path(config['output_path']).resolve()
input_folder_path = Path(config['input_path']).resolve()

output_folder_path.mkdir(parents=True, exist_ok=True)

program_config = config.get('0_download_sharadar_data', {})

# Optional override, mainly for testing a subset of tables.
DATASETS_TO_DOWNLOAD = program_config.get("datasets", DATASETS_TO_DOWNLOAD)

MAX_RETRIES = program_config.get("MAX_RETRIES", 3)
RETRY_WAIT_SECONDS = program_config.get("RETRY_WAIT_SECONDS", 60)

TOTAL_DOWNLOAD_TIMEOUT_MINS = program_config.get("TOTAL_DOWNLOAD_TIMEOUT_MINS", 30)
POLL_INTERVAL_SECONDS = program_config.get("POLL_INTERVAL_SECONDS", 30)
# How long to hold out for a 'fresh' snapshot before taking the latest
# completed one. 0 = download immediately, exactly what the website's
# download button serves (browser-equivalent behavior).
FRESH_WAIT_MINS = program_config.get("FRESH_WAIT_MINS", 0)

DOWNLOAD_DATA = program_config.get("DOWNLOAD_DATA", True)
UNZIP_DATA = program_config.get("UNZIP_DATA", True)
RENAME_DATA = program_config.get("RENAME_DATA", True)
CLEANUP_SOURCE_FILES = program_config.get("CLEANUP_SOURCE_FILES", False)

indicator_file_name = program_config.get("indicator_file_name", "SHARADAR_INDICATORS_2")
DOWNLOAD_DIR = output_folder_path / program_config.get("output_folder", 10)

print("------------------------------------------------------------------")

# ==============================================================================
# --- HELPER FUNCTIONS ---
# ==============================================================================


def request_export(dataset):
    """
    Asks the API for the dataset's bulk-export snapshot (triggering
    regeneration server-side if needed). Returns (status, link) where status
    is 'fresh', 'regenerating' or 'creating'.
    """
    url = f"{API_BASE}/{dataset}.json"
    response = requests.get(url, params={'qopts.export': 'true', 'api_key': NASDAQ_API_KEY},
                            timeout=(30, 120))
    response.raise_for_status()
    file_info = response.json()['datatable_bulk_download']['file']
    return file_info['status'], file_info['link']


def download_file(link, dest_dir):
    """
    Streams a zip from its signed S3 link into dest_dir, using a .part file
    until complete. The server's filename (e.g. SHARADAR_TICKERS_3_<hash>.zip)
    is kept so downstream unzip/rename behavior matches the browser version.
    """
    filename = Path(urlparse(link).path).name
    dest = dest_dir / filename
    tmp = dest.with_suffix(dest.suffix + '.part')
    with requests.get(link, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        with open(tmp, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    os.replace(tmp, dest)
    size_mb = dest.stat().st_size / (1 << 20)
    print(f"  ✅ Downloaded {dest.name} ({size_mb:.1f} MB)")
    return dest


def download_all_and_unzip(export_links, perform_unzip):
    """
    Downloads every dataset's snapshot. With FRESH_WAIT_MINS=0 (default) each
    link is downloaded immediately — the same latest-completed snapshot the
    website button serves. A positive FRESH_WAIT_MINS holds out that long for
    a 'fresh' (fully up-to-date) snapshot before settling for the latest
    completed one. Unzips on success, mirroring the original script's
    behavior and log output.
    """
    print("\n==============================================")
    print(f"Downloading exports (fresh-snapshot wait: {FRESH_WAIT_MINS} min, "
          f"overall timeout: {TOTAL_DOWNLOAD_TIMEOUT_MINS} min)...")

    start_time = time.perf_counter()
    timeout_seconds = TOTAL_DOWNLOAD_TIMEOUT_MINS * 60
    fresh_wait_seconds = FRESH_WAIT_MINS * 60
    number_of_expected_files = len(DATASETS_TO_DOWNLOAD)
    pending = dict(export_links)  # dataset -> last known link

    while pending:
        elapsed = time.perf_counter() - start_time
        if elapsed >= timeout_seconds:
            break
        for dataset in list(pending):
            try:
                status, link = request_export(dataset)
                pending[dataset] = link
            except requests.RequestException as e:
                print(f"  ⚠️ Transient error checking {dataset}: {e}")
                continue
            if status != 'fresh' and elapsed < fresh_wait_seconds:
                continue  # keep holding out for the regenerating snapshot
            if status != 'fresh':
                print(f"  Downloading latest completed snapshot of {dataset} (status: {status})...")
            else:
                print(f"  Downloading {dataset}...")
            try:
                download_file(link, DOWNLOAD_DIR)
                del pending[dataset]
            except requests.RequestException as e:
                print(f"  ⚠️ Download failed for {dataset}, will retry: {e}")
        if pending:
            elapsed_mins = (time.perf_counter() - start_time) / 60
            print(f"\n--- Status at {elapsed_mins:.1f} minutes ---")
            print(f"Waiting on {len(pending)} dataset(s): {sorted(pending)}")
            time.sleep(POLL_INTERVAL_SECONDS)

    zip_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith('.zip')]

    if len(zip_files) == number_of_expected_files:
        print(f"\n✅ Success! Found {len(zip_files)} completed zip files.")

        if perform_unzip:
            print("\nStarting unzipping process...")
            for filename in sorted(zip_files):
                file_path = DOWNLOAD_DIR / filename
                print(f"  Unzipping '{filename}'...")
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(DOWNLOAD_DIR)
                    print(f"  ✅ Successfully unzipped.")
                except zipfile.BadZipFile:
                    print(f"  ❌ Error: '{filename}' is not a valid zip file or is corrupted.")
                except Exception as e:
                    print(f"  ❌ An unexpected error occurred during unzipping: {e}")
        else:
            print("\nSkipping unzipping process as per configuration (UNZIP_DATA=False).")

        return True

    print("\n==============================================")
    print(f"⚠️ Failure: Only {len(zip_files)} of {number_of_expected_files} expected files downloaded.")
    return False


# ==============================================================================
# --- SCRIPT EXECUTION ---
# ==============================================================================

start_time = time.perf_counter()

if not NASDAQ_API_KEY:
    print("🚨 Error: No Nasdaq Data Link API key found. Set NASDAQ_API_KEY (or QUANDL_TOKEN) in config.py.")
else:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_folder_path.mkdir(parents=True, exist_ok=True)

    try:
        pre_processing_complete = False

        if DOWNLOAD_DATA:
            print("--- Running Download Step (DOWNLOAD_DATA=True) ---")
            print(f"Preparing download directory: {DOWNLOAD_DIR}")
            print("Deleting all pre-existing files in the download directory...")
            try:
                for item in DOWNLOAD_DIR.iterdir():
                    if item.is_file(): item.unlink()
            except Exception as e:
                print(f"  Could not complete cleanup. Error: {e}")

            # --- EXPORT INITIATION WITH RETRY LOGIC ---
            datasets_to_attempt = DATASETS_TO_DOWNLOAD[:]
            export_links = {}
            all_downloads_initiated = False

            for attempt in range(MAX_RETRIES):
                print("\n==============================================")
                print(f"Download Initiation: Attempt {attempt + 1} of {MAX_RETRIES}")
                print("==============================================")

                failed_this_attempt = []
                for dataset in datasets_to_attempt:
                    try:
                        status, link = request_export(dataset)
                        export_links[dataset] = link
                        print(f"  -> Export requested for {dataset} (snapshot status: {status})")
                    except Exception as loop_error:
                        print(f"  ❌ FAILED to request export for {dataset}: {loop_error}")
                        failed_this_attempt.append(dataset)

                if not failed_this_attempt:
                    print("\n✅ All downloads were initiated successfully!")
                    all_downloads_initiated = True
                    break
                else:
                    print(f"\n⚠️ Failed to initiate downloads for: {failed_this_attempt}")
                    datasets_to_attempt = failed_this_attempt
                    if attempt < MAX_RETRIES - 1:
                        print(f"Retrying in {RETRY_WAIT_SECONDS} seconds...")
                        time.sleep(RETRY_WAIT_SECONDS)

            if all_downloads_initiated:
                pre_processing_complete = download_all_and_unzip(export_links, UNZIP_DATA)
            else:
                print("\n❌ Aborting script: Could not initiate all downloads after multiple retries.")
                pre_processing_complete = False

        elif UNZIP_DATA or RENAME_DATA:
             print("--- Skipping Download Step (DOWNLOAD_DATA=False) ---")
             if UNZIP_DATA:
                 print("\n--- Running Unzip Step on existing files (UNZIP_DATA=True) ---")
                 zip_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith('.zip')]
                 if not zip_files:
                     print("No .zip files found to unzip.")
                 else:
                    for filename in sorted(zip_files):
                        file_path = DOWNLOAD_DIR / filename
                        print(f"  Unzipping '{filename}'...")
                        try:
                            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                                zip_ref.extractall(DOWNLOAD_DIR)
                            print(f"  ✅ Successfully unzipped.")
                        except Exception as e:
                            print(f"  ❌ Error unzipping {filename}: {e}")
             pre_processing_complete = True

        if pre_processing_complete and RENAME_DATA:
            print("\n--- Running Rename & Post-Processing Step (RENAME_DATA=True) ---")
            csv_file_list = [i for i in os.listdir(DOWNLOAD_DIR) if "SHARADAR_" in i and ".csv" in i]

            if not csv_file_list:
                print("No CSV files found to process. Make sure files were unzipped.")
            else:
                writer =pd.ExcelWriter( output_folder_path.joinpath("0_Sharadar_Data_sample.xlsx"), engine='xlsxwriter')
                for csv in csv_file_list:
                    old_csv = DOWNLOAD_DIR.joinpath(csv)
                    var = "_".join( csv.split("_")[:-1] )
                    new_csv = DOWNLOAD_DIR.joinpath( var + ".csv" )
                    print(f"Processing '{new_csv.name}'...")
                    if old_csv != new_csv and old_csv.exists():
                        os.rename(old_csv, new_csv)

                    df = pd.read_csv(new_csv, engine='pyarrow')
                    df.to_parquet( DOWNLOAD_DIR.joinpath( var+ ".parquet"))

                    if var == indicator_file_name:
                        df.set_index(["table","indicator"]).sort_index().to_excel(output_folder_path.joinpath( "0_Sharadar_Data_descriptions.xlsx"))

                    sheetname =  var.replace("SHARADAR_","")
                    df.head(300).to_excel(writer, sheet_name=sheetname)
                    worksheet = writer.sheets[sheetname]
                    worksheet.freeze_panes(1, 0)
                writer.close()
                print("✅ Post-processing complete.")

                if CLEANUP_SOURCE_FILES:
                    print("\n--- Running Cleanup (CLEANUP_SOURCE_FILES=True) ---")
                    print("🧹 Deleting source .zip and .csv files...")
                    files_to_delete = list(DOWNLOAD_DIR.glob('*.zip'))

                    if not files_to_delete:
                        print("No .zip or .csv files found to delete.")
                    else:
                        deleted_count = 0
                        for f in files_to_delete:
                            try:
                                f.unlink()
                                deleted_count += 1
                            except OSError as e:
                                print(f"  ❌ Error deleting file {f}: {e}")
                        print(f"✅ Cleanup complete. Deleted {deleted_count} files.")

        elif pre_processing_complete and not RENAME_DATA:
            print("\n--- Skipping Rename & Post-Processing Step (RENAME_DATA=False) ---")

    except Exception as e:
        print(f"\nAn unexpected error occurred during the main process: {e}")

    finally:
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        print("\n==============================================")
        print(f"Total script execution time: {int(minutes)} minute(s) and {seconds:.2f} seconds.")
