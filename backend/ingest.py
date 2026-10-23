"""Parse local files without network access. Scans require local Tesseract."""
import argparse
import subprocess
import tempfile
from pathlib import Path
from backend.core import Store

def read_pages(path: Path) -> list[str]:
    if path.stat().st_size>25*1024*1024: raise ValueError('File exceeds 25 MiB')
    if path.suffix.lower() in ('.txt','.md'): return [path.read_text(encoding='utf-8-sig')]
    if path.suffix.lower()!='.pdf': raise ValueError('Supported formats: .txt, .md, .pdf')
    from pypdf import PdfReader
    reader=PdfReader(path)
    if len(reader.pages)>100: raise ValueError('PDF exceeds 100 pages')
    pages=[]
    for i,page in enumerate(reader.pages):
        text=page.extract_text(extraction_mode='layout') or ''
        if len(text.strip())<30:
            import pypdfium2 as pdfium
            with tempfile.TemporaryDirectory() as tmp:
                document=pdfium.PdfDocument(path)
                document[i].render(scale=2.5).to_pil().save(Path(tmp)/'page.png')
                document.close()
                try:
                    result=subprocess.run(['tesseract',str(Path(tmp)/'page.png'),'stdout','-l','rus+eng'],capture_output=True,text=True,encoding='utf-8',check=True,timeout=90)
                except (FileNotFoundError,subprocess.CalledProcessError) as e:
                    raise ValueError(f'Page {i+1} needs offline OCR with rus+eng language files') from e
                text=result.stdout
                if len(text.strip())<30: raise ValueError(f'Page {i+1} failed OCR quality gate')
        pages.append(text)
    return pages

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('file',type=Path); parser.add_argument('--db',default='data/knowledge.db'); parser.add_argument('--tenant',required=True); parser.add_argument('--roles',required=True)
    args=parser.parse_args()
    doc=Store(args.db).ingest(args.file.name,read_pages(args.file),args.tenant,args.roles.split(','))
    print('Ingested document:',doc)

if __name__=='__main__': main()
