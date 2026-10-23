"""Install pinned Python dependencies into a fresh venv with networking disabled."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from wheelhouse import inventory


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--wheels',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    current=inventory(args.wheels,Path('requirements-lock.txt'))
    if current!=json.loads((args.wheels/'manifest.json').read_text()):raise ValueError('Wheel integrity failure')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);environment=root/'venv'
        subprocess.run([sys.executable,'-m','venv',str(environment)],check=True)
        python=environment/'bin/python'
        subprocess.run([str(python),'-m','pip','install','--no-index','--find-links',str(args.wheels),'-r','requirements-lock.txt'],check=True)
        env={**os.environ,'DB_PATH':str(root/'isolated.db'),'PYTHONDONTWRITEBYTECODE':'1'}
        subprocess.run([str(python),'-m','backend.check'],env=env,check=True)
    args.output.write_text(json.dumps({'status':'PASS','scope':'Python dependency install from verified wheels into fresh Linux/Python3.12 venv without network',
                                     'limitations':'OS image and OCR packages supplied by prepared staging image; not a fresh offline apt/base-image build',
                                     'wheel_count':len(current['files']),'lock_sha256':current['lock_sha256']},indent=2))


if __name__=='__main__':main()
