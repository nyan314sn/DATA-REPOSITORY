# -*- coding: utf-8 -*-
"""
This script automates the download and extraction of Sharadar financial datasets.

It performs the following steps:
1. Prepares a clean download directory by deleting all existing .zip files.
2. Logs into the Nasdaq Data Link website using Selenium.
3. Iterates through a predefined list of datasets to initiate all downloads,
   with a retry mechanism for any that fail to initiate.
4. Enters a monitoring phase, waiting until the count of downloaded files
   matches the number of requested datasets.
5. Unzips all found .zip files into the main download folder.
6. Reports the total execution time upon completion.
"""
import platform  
import pandas as pd
import os
import time
import zipfile
import random
from pathlib import Path
from selenium import webdriver
# from selenium.webdriver.firefox.service import Service
# from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import argparse
import yaml
# --- User-Defined Imports ---
from config import NASDAQ_EMAIL, NASDAQ_PASSWORD
from timeit import default_timer as timer
import sys 

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
# from webdriver_manager.core.os_manager import ChromeType # <--- NEW IMPORT


start = timer()


# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================



# --- Execution Control Flags ---

DATASETS_TO_DOWNLOAD = [
    'SHARADAR/SF1', 'SHARADAR/SF2', 'SHARADAR/SF3', 'SHARADAR/EVENTS',
    'SHARADAR/SF3A', 'SHARADAR/SF3B', 'SHARADAR/SEP', 'SHARADAR/TICKERS',
    'SHARADAR/INDICATORS', 'SHARADAR/DAILY', 'SHARADAR/SP500',
    'SHARADAR/ACTIONS', 'SHARADAR/SFP', 'SHARADAR/METRICS'
]

EMAIL = NASDAQ_EMAIL
PASSWORD = NASDAQ_PASSWORD

# manual url https://data.nasdaq.com/databases/SFA/usage/export
LOGIN_URL = 'https://data.nasdaq.com/login'
TABLES_BASE_URL = 'https://data.nasdaq.com/tables/SFA'










# ==============================================================================
# --- HOUSE KEEPING ---
# ==============================================================================


# --- 1. Argument Parsing ---
# This allows you to specify the config file from the command line.
is_interactive = len(sys.argv) == 1 or sys.argv[0].endswith('ipykernel_launcher.py')
parser = argparse.ArgumentParser(description="Configurable Sharadar Data Processing Pipeline.")
parser.add_argument('--config', type=str, help='Path to the configuration YAML file.')

if is_interactive:
    print("Running in interactive mode, using default config: 'config/local_config.yml'")
    # In Jupyter/IPython, it defaults to your local config.
    args = parser.parse_args(['--config', 'config/local_config.yml'])

else:
    # When running from the terminal, it parses the provided arguments.
    args = parser.parse_args()

# --- 2. Load Configuration ---
print(f"Loading configuration from: {args.config}")
with open(args.config, "r") as f:
    config = yaml.safe_load(f)

# --- 3. Initialize Settings from Config ---
output_folder_path = Path(config['output_path']).resolve()
# DOWNLOAD_DIR = Path(config['input_paths']['sharadar_data']).resolve()
input_folder_path = Path(config['input_path']).resolve()
    
output_folder_path.mkdir(parents=True, exist_ok=True)

program_config = config.get('0_download_sharadar_data', {})


# --- NEW: Retry Configuration ---
MAX_RETRIES =  program_config.get("MAX_RETRIES",3)
RETRY_WAIT_SECONDS =  program_config.get("RETRY_WAIT_SECONDS",60)

# # Monitoring Configuration
TOTAL_DOWNLOAD_TIMEOUT_MINS =  program_config.get("TOTAL_DOWNLOAD_TIMEOUT_MINS",30)
CHECK_INTERVAL_MINS =  program_config.get("CHECK_INTERVAL_MINS",10)

DOWNLOAD_DATA =  program_config.get("DOWNLOAD_DATA",True) # Set to False to skip web scraping and downloading
UNZIP_DATA =  program_config.get("UNZIP_DATA",True)    # Set to False to skip unzipping files
RENAME_DATA =  program_config.get("RENAME_DATA",True)   # Set to False to skip renaming and post-processing (Parquet/Excel)
CLEANUP_SOURCE_FILES =  program_config.get("CLEANUP_SOURCE_FILES",False)  # Set to True to delete source .zip and .csv files after processing

indicator_file_name =  program_config.get("indicator_file_name","SHARADAR_INDICATORS_2")  # Set to True to delete source .zip and .csv files after processing
DOWNLOAD_DIR = output_folder_path / program_config.get("output_folder",10)

print("------------------------------------------------------------------")

# ==============================================================================
# --- HELPER FUNCTIONS ---
# ==============================================================================


def setup_driver(download_path):
    """
    Configures and returns a headless Chrome WebDriver instance.
    Uses webdriver-manager for automatic chromedriver installation.
    Works on Windows, Linux, and Mac!
    """
    print("Setting up headless Chrome browser...")
    chrome_options = Options()
    
    # Convert to absolute path string (important for cross-platform compatibility)
    download_path_str = str(Path(download_path).resolve())
    
    # Core headless arguments
    chrome_options.add_argument("--headless=new")  # Use newer headless mode
    chrome_options.add_argument("--no-sandbox")  # Essential for Linux
    chrome_options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1200")
    
    # Stability improvements
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    # Download preferences (still needed as fallback, works reliably on Linux)
    prefs = {
        "download.default_directory": download_path_str,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    # Automatically downloads and manages chromedriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Force download directory via Chrome DevTools Protocol
    # This is essential for Windows where prefs are often ignored in headless mode
    # It's harmless on Linux where prefs already work
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": download_path_str
    })
    
    return driver



def perform_login(driver, wait):
    """Handles the entire login process."""
    print(f"Navigating to login page: {LOGIN_URL}")
    driver.get(LOGIN_URL)
    print("Waiting for page's JavaScript to render the form...")
    time.sleep(3)
    try:
        cookie_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='privacy-banner-accept']")))
        cookie_button.click()
        print("Cookie consent dismissed.")
    except TimeoutException:
        print("Cookie consent banner not found or already dismissed.")
    print("Finding email field...")
    email_input = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[data-testid='loginForm_email']")))
    print("Typing email address...")
    email_input.send_keys(EMAIL)
    print("Waiting for 'NEXT' button to become clickable...")
    next_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='loginForm_next']")))
    print("Clicking 'NEXT'...")
    next_button.click()
    print("Waiting for password field to appear...")
    password_input = wait.until(EC.visibility_of_element_located((By.ID, "password")))
    print("Entering password...")
    password_input.send_keys(PASSWORD)
    print("Waiting for final 'Login' button...")
    login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='loginForm_submit']")))
    print("Clicking final 'Login' button...")
    login_button.click()
    print("✅ Login submitted successfully!")
    time.sleep(5)

def monitor_downloads_and_unzip(perform_unzip):
    """
    Monitors the download directory by counting files and unzips them upon completion.
    The 'perform_unzip' flag controls whether unzipping occurs.
    """
    print("\n==============================================")
    print(f"Monitoring downloads for up to {TOTAL_DOWNLOAD_TIMEOUT_MINS} minutes...")
    
    start_time = time.perf_counter()
    timeout_seconds = TOTAL_DOWNLOAD_TIMEOUT_MINS * 60
    check_interval_seconds = CHECK_INTERVAL_MINS * 60
    
    number_of_expected_files = len(DATASETS_TO_DOWNLOAD)

    while time.perf_counter() - start_time < timeout_seconds:
        files_in_dir = os.listdir(DOWNLOAD_DIR)
        part_files = [f for f in files_in_dir if f.endswith('.part')]
        zip_files = [f for f in files_in_dir if f.lower().endswith('.zip')]

        if len(zip_files) == number_of_expected_files and not part_files:
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
            
            return True # Exit the function after successful monitoring

        elapsed_mins = (time.perf_counter() - start_time) / 60
        print(f"\n--- Status at {elapsed_mins:.1f} minutes ---")
        print(f"Found {len(zip_files)} of {number_of_expected_files} expected zip files.")
        if part_files:
            print(f"Found {len(part_files)} file(s) still in progress (.part): {part_files}")
        
        remaining_time = timeout_seconds - (time.perf_counter() - start_time)
        if remaining_time > check_interval_seconds:
            print(f"Checking again in {CHECK_INTERVAL_MINS} minutes...")
            time.sleep(check_interval_seconds)
        else:
            if remaining_time > 0:
                print(f"Timeout approaching. Final wait for {remaining_time:.0f} seconds...")
                time.sleep(remaining_time)
            break 

    print("\n==============================================")
    print(f"⚠️ Failure: Timeout of {TOTAL_DOWNLOAD_TIMEOUT_MINS} minutes reached.")
    final_zip_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith('.zip')]
    print(f"Found {len(final_zip_files)} out of {number_of_expected_files} expected files.")
    return False

# ==============================================================================
# --- SCRIPT EXECUTION ---
# ==============================================================================

start_time = time.perf_counter()

if not EMAIL or not PASSWORD or EMAIL == "your_email@example.com":
    print("🚨 Error: Please update NASDAQ_EMAIL and NASDAQ_PASSWORD in your config.py file before running.")
else:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_folder_path.mkdir(parents=True, exist_ok=True)

    
    driver = None
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

            driver = setup_driver(DOWNLOAD_DIR)
            wait = WebDriverWait(driver, 20)
            perform_login(driver, wait)

            # --- MODIFIED: DOWNLOAD INITIATION WITH RETRY LOGIC ---
            datasets_to_attempt = DATASETS_TO_DOWNLOAD[:] # Start with all datasets
            all_downloads_initiated = False

            for attempt in range(MAX_RETRIES):
                print("\n==============================================")
                print(f"Download Initiation: Attempt {attempt + 1} of {MAX_RETRIES}")
                print("==============================================")
                
                failed_this_attempt = []
                for dataset in datasets_to_attempt:
                    try:
                        table_code_for_url = dataset.replace('/', '-')
                        export_page_url = f'{TABLES_BASE_URL}/{table_code_for_url}/export'
                        driver.get(export_page_url)
                        download_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.download-button[data-test-download-button='active']")))
                        download_button.click()
                        print(f"  -> Clicked download for {dataset}")
                        time.sleep(random.uniform(10, 20)) # Wait after successful click
                    except (TimeoutException, WebDriverException) as loop_error:
                        print(f"  ❌ FAILED to initiate download for {dataset}.")
                        failed_this_attempt.append(dataset)
                
                if not failed_this_attempt:
                    print("\n✅ All downloads were initiated successfully!")
                    all_downloads_initiated = True
                    break # Exit the retry loop
                else:
                    print(f"\n⚠️ Failed to initiate downloads for: {failed_this_attempt}")
                    datasets_to_attempt = failed_this_attempt # Next attempt will only retry these
                    if attempt < MAX_RETRIES - 1:
                        print(f"Retrying in {RETRY_WAIT_SECONDS} seconds...")
                        time.sleep(RETRY_WAIT_SECONDS)
            
            if all_downloads_initiated:
                pre_processing_complete = monitor_downloads_and_unzip(UNZIP_DATA)
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
        

                # --- BLOCK MODIFIED/ADDED ---
                if CLEANUP_SOURCE_FILES:
                    print("\n--- Running Cleanup (CLEANUP_SOURCE_FILES=True) ---")
                    print("🧹 Deleting source .zip and .csv files...")
                    # files_to_delete = list(DOWNLOAD_DIR.glob('*.zip')) + list(DOWNLOAD_DIR.glob('*.csv'))
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
        if driver:
            screenshot_path = DOWNLOAD_DIR / 'error_screenshot.png'
            driver.save_screenshot(str(screenshot_path))
            print(f"A screenshot of the error has been saved to: {screenshot_path}")

    finally:
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        print("\n==============================================")
        print(f"Total script execution time: {int(minutes)} minute(s) and {seconds:.2f} seconds.")
        
        if driver:
            print("Closing browser.")
            driver.quit()