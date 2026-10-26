"""Run actual checks and bind machine-readable results to the tested tree."""
import argparse
import ast
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.bundle import identity


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('data/verification/verification.json'))
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    evidence=args.output.parent
    bundle=identity()['tree_sha256']
    commands={
        'lint':['ruff','check','backend','tests','eval','tools'],
        'types':['mypy','backend/budget.py','backend/grounding.py','backend/backup.py','backend/evaluate.py','backend/finops.py','backend/release.py'],
        'unit':[sys.executable,'-m','pytest','-q','--junitxml='+str(evidence/'junit.xml'),
                '--cov=backend','--cov-report=term-missing','--cov-report=json:'+str(evidence/'coverage.json'),'-p','no:cacheprovider'],
        'existing_check':[sys.executable,'-m','backend.check'],
    }
    phases={}
    for name,command in commands.items():
        process=subprocess.run(command,capture_output=True,text=True)
        (evidence/(name+'.log')).write_text(process.stdout+process.stderr,encoding='utf-8')
        phases[name]=process.returncode
        print(name,process.returncode,flush=True)
    secret_findings=[]
    for path in Path('backend').glob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                if len(node.value.value)>24 and any(isinstance(t,ast.Name) and t.id.lower() in ('password','api_key','token','secret') for t in node.targets):
                    secret_findings.append(str(path)+':'+str(node.lineno))
    phases['literal_secret_scan']=int(bool(secret_findings))
    phases['tree_unchanged']=int(identity()['tree_sha256']!=bundle)
    tests=0
    if (evidence/'junit.xml').exists():
        root=ET.parse(evidence/'junit.xml').getroot()
        tests=sum(int(s.attrib.get('tests',0)) for s in root.iter('testsuite'))
    report={'bundle_hash':bundle,'timestamp':time.time(),'phases':phases,'tests':tests,
            'exit_code':int(any(phases.values())),'secret_scan':'Local AST literal scan only, not a CVE/security certification'}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report['exit_code']


if __name__=='__main__': raise SystemExit(main())
