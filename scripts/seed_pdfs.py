import os
import requests
import json
import glob
import time

API_URL = os.environ.get("REGINTEL_API_URL", "http://localhost:8000/api/v1")

def login():
    # Local-dev seeding script. Credentials come from env so no password
    # lives in git; the defaults only work against a local dev backend.
    email = os.environ.get("REGINTEL_SEED_EMAIL", "admin@regintel.ai")
    password = os.environ.get("REGINTEL_SEED_PASSWORD", "Admin@123")
    res = requests.post(
        f"{API_URL}/security/auth/login",
        json={"email": email, "password": password}
    )
    if res.status_code == 200:
        return res.json()["access_token"]
    print(f"Login failed: {res.text}")
    return None

def upload_pdfs(token):
    headers = {"Authorization": f"Bearer {token}"}
    pdf_files = glob.glob("storage/RBI/*.pdf") + glob.glob("storage/SEBI/*.pdf")
    
    # We will just upload 5 of them as a demonstration to avoid taking hours.
    # The user can run it for all if they want, but let's do 5 first.
    # Actually, I'll ingest all of them. The background task might queue them up nicely.
    
    print(f"Found {len(pdf_files)} PDFs. Starting upload...")
    
    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        source = "RBI" if "RBI" in pdf_path else "SEBI"
        
        with open(pdf_path, 'rb') as f:
            files = {
                'file': (filename, f, 'application/pdf')
            }
            data = {
                'title': filename.replace('.pdf', ''),
                'document_type': 'Regulatory Guideline',
                'source': source
            }
            print(f"Uploading {filename}...")
            res = requests.post(f"{API_URL}/documents/upload", headers=headers, files=files, data=data)
            if res.status_code == 201:
                print(f"  -> Uploaded successfully: {res.json()['document_id']}")
            else:
                print(f"  -> Failed: {res.status_code} - {res.text}")

if __name__ == "__main__":
    print("Getting token...")
    token = login()
    if token:
        upload_pdfs(token)
