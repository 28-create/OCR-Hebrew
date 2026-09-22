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
EXPECTED = {
    'downloads/tesseract-setup.exe': 'f3fc4236425b690c8be756f35793f77394ee004be0a6460a440c754d892f68bc',
    'tesseract/tessdata/heb.traineddata': 'dbaa827aea6bc21215638447f17783a1004987c2d0bf5573d111fee397abdae5',
    'tesseract/tessdata/eng.traineddata': '8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba',
    'tesseract/tessdata/fra.traineddata': '907743d98915c91a3906dfbf6e48b97598346698fe53aaa797e1a064ffcac913',
    'tesseract/tessdata/heb_rashi.traineddata': 'c3bdf2c4188e037838e027de419e6e8ca663f1168fef3d09df1a3a46afab6c50',
    'licenses/tessdata-LICENSE.txt': 'a6cba85bc92e0cff7a450b1d873c0eaa2e9fc96bf472df0247a26bec77bf3ff9',
    'licenses/Rashi-TRAINING.md': '1ee4724d29e5443adeb43b2e3f1ac89c4e93ac44063162dc935c0b16489c3130',
    'licenses/rashi-LICENSE.txt': 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4',
    'licenses/tesseract-LICENSE.txt': 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30',
}
CTX = ssl.create_default_context()
# The workspace proxy CA predates OpenSSL's strict Basic Constraints requirement.
# Trust-chain validation and hostname verification remain enabled.
CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

def download(url, relative):
    if relative not in EXPECTED:
        raise RuntimeError(f'No versioned SHA-256 for {relative}')
    target = ASSETS / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with urllib.request.urlopen(url, context=CTX, timeout=120) as response:
            with target.open('wb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != EXPECTED[relative]:
        target.unlink(missing_ok=True)
        raise RuntimeError(f'SHA-256 mismatch for {relative}: expected {EXPECTED[relative]}, got {digest}')
    record = {'file': relative, 'url': url, 'size': target.stat().st_size, 'sha256': digest}
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
