import os
import sys
import zipfile
import io
import subprocess
from pathlib import Path

# Use the hosted URL by default
SERVER_URL = "https://broadcastapp.vercel.app"

def run_local_link():
    print("========================================")
    print("   WhatsApp Local Linking & Sync Tool")
    print("========================================")
    
    session_id = input("\nEnter a Session Name (e.g. my-whatsapp): ").strip()
    if not session_id:
        print("Error: Session Name is required.")
        return

    # 1. Setup paths
    bridge_dir = Path("slik-bridge")
    auth_dir = Path("app/slik-session") / session_id
    auth_dir.mkdir(parents=True, exist_ok=True)

    # 2. Check Node dependencies
    if not (bridge_dir / "node_modules").exists():
        print("\nInstalling bridge dependencies (npm install)...")
        subprocess.run("npm install", cwd=bridge_dir, shell=True)

    # 3. Run Linking
    print(f"\n>>> Starting QR Scan for '{session_id}'")
    print(">>> SCAN THE QR CODE THAT APPEARS IN THE TERMINAL")
    
    # We use the local bridge's link script
    try:
        cmd = ["node", "link.js", str(auth_dir.absolute())]
        subprocess.run(cmd, cwd=bridge_dir, shell=True, check=True)
    except Exception as e:
        print(f"\nLinking failed: {e}")
        return

    # 4. Zip the results
    print("\n>>> Linking successful locally! Packing session...")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(auth_dir):
            for file in files:
                p = Path(root) / file
                zf.write(p, p.relative_to(auth_dir))
    
    # 5. Upload to Cloud
    print(f"\n>>> Syncing to Cloud ({SERVER_URL})...")
    try:
        import requests
    except ImportError:
        print("Installing requests library for sync...")
        subprocess.run([sys.executable, "-m", "pip", "install", "requests"], check=True)
        import requests

    upload_url = f"{SERVER_URL}/api/slik-accounts/upload"
    files = {
        'file': (f"{session_id}.zip", zip_buffer.getvalue(), 'application/zip')
    }
    
    response = requests.post(upload_url, files=files)
    
    if response.status_code < 400:
        print("\nSUCCESS! Your session is now synced to the cloud.")
        print("You can now send messages from the website and it will stay connected.")
    else:
        print(f"\nSync Failed (Error {response.status_code})")
        print(response.text)

if __name__ == "__main__":
    try:
        run_local_link()
    except KeyboardInterrupt:
        print("\nCancelled.")
    input("\nPress Enter to exit...")
