"""Local YAML and shell syntax validation; never claims remote CI execution."""
import json
import subprocess
from pathlib import Path

import yaml

workflow = yaml.safe_load(Path('.github/workflows/verify.yml').read_text())
assert workflow.get('on', workflow.get(True))
steps = workflow['jobs']['cpu']['steps']
results = []
for step in steps:
    if 'run' in step:
        result = subprocess.run(['bash','-n'],input=step['run'],capture_output=True,text=True)
        results.append({'step':step.get('name','shell'),'syntax_exit_code':result.returncode})
        assert result.returncode == 0, result.stderr
Path('/evidence/workflow-local.json').write_text(json.dumps({
    'yaml_and_shell_syntax':'PASS','steps':results,'remote_actions':'NOT RUN',
    'artifact_execution':'Runtime bundle equality, real CPU/GPU checks and unit reports are separate evidence',
    'not_tested':'GitHub runner permissions, action downloads, remote credentials and hosted GPU runner'},indent=2))
