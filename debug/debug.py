from playwright.sync_api import sync_playwright
import os

# --- Configuration ---
# This is already the correct URL for your local server
server_url = 'https://www.flipkart.com/xbey-8-ribs-umbrella-rain-uv-protection-specially-man-woman-child-1pc/p/itm11ec6e82d40b7?pid=UMBGZW2PFWN9HAZK&lid=LSTUMBGZW2PFWN9HAZKZHQCW6&marketplace=FLIPKART&store=all%2Fh1m%2Fiee%2Fkjp&srno=b_1_4&otracker=browse&fm=organic&iid=0b280760-f99f-4a3d-ab6e-4f95140ca84d.UMBGZW2PFWN9HAZK.SEARCH&ppt=hp&ppn=homepage&ssid=u3tudv87dc0000001758857955949'
output_filename = 'debug_screenshot.png'

# --- Main Script ---
def capture_screenshot(url: str, output_path: str):
    """
    Launches Playwright, navigates to a URL, waits for the page
    to be fully loaded, and saves a screenshot.
    """
    try:
        with sync_playwright() as p:
            print("Launching browser...")
            # Changed to headless=True for automation, set to False if you want to see the browser
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            
            print(f"Navigating to: {url}")
            page.goto(url, timeout=60000)
            
            # This is the crucial step: waits for API calls to finish
            print("Waiting for network to be idle...")
            page.wait_for_load_state("domcontentloaded")
            
            print(f"Capturing screenshot and saving to {output_path}...")
            page.screenshot(path=output_path, full_page=True,clip={
                "x": 300,
                "y": 200,
                "width": 600,
                "height": 400
            })
            
            browser.close()
            print("Screenshot captured successfully!")
            print(f"Screenshot saved as '{os.path.abspath(output_path)}'")

    except Exception as e:
        print(f"\n--- An error occurred: {e} ---")
        print("\nPlease check the following:")
        print("1. Is the local server (`server.py`) running in a separate terminal?")
        print(f"2. Can you open {url} in your browser manually?")
        print("3. Is Playwright installed correctly?")

# --- CORRECTED EXECUTION BLOCK ---
if __name__ == "__main__":
    # ✅ FIX: Call the function directly with the server_url.
    # No file path conversion is needed.
    capture_screenshot(server_url, output_filename)

