"""Development-only dependency download. The shipped application has no network code."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'aleph' / 'assets'
CTX = ssl.create_default_context()
# The workspace proxy CA predates OpenSSL's strict Basic Constraints requirement.
# Trust-chain validation and hostname verification remain enabled.
CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

def download(url, relative):
    target = ASSETS / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with urllib.request.urlopen(url, context=CTX, timeout=120) as response:
            with target.open('wb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
    record = {'file': relative, 'url': url, 'size': target.stat().st_size,
              'sha256': hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()}
    print(json.dumps(record), flush=True)
    return record

def main():
    jobs = [
        ('https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe', 'downloads/tesseract-setup.exe'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/heb.traineddata', 'tesseract/tessdata/heb.traineddata'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/eng.traineddata', 'tesseract/tessdata/eng.traineddata'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/fra.traineddata', 'tesseract/tessdata/fra.traineddata'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_contrib/dfae088deccd8a1b2b16027f8ff4fec782099e4e/heb_rashi/best/heb_rashi.traineddata', 'tesseract/tessdata/heb_rashi.traineddata'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/LICENSE', 'licenses/tessdata-LICENSE.txt'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_contrib/dfae088deccd8a1b2b16027f8ff4fec782099e4e/heb_rashi/TRAINING.md', 'licenses/Rashi-TRAINING.md'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_contrib/dfae088deccd8a1b2b16027f8ff4fec782099e4e/LICENSE', 'licenses/rashi-LICENSE.txt'),
        ('https://raw.githubusercontent.com/tesseract-ocr/tesseract/5.5.0/LICENSE', 'licenses/tesseract-LICENSE.txt'),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda job: download(*job), jobs))
    (ASSETS / 'sources.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    subprocess.run([r'C:\Program Files\7-Zip\7z.exe', 'x', str(ASSETS / 'downloads/tesseract-setup.exe'),
                    '-o' + str(ASSETS / 'tesseract'), '-y', '-xr!tessdata'], check=True)

if __name__ == '__main__':
    main()
