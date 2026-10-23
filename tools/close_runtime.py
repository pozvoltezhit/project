"""Remove only this task's new Docker test namespace; preserve original assets."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NAMESPACE='course-remediation-20261020'
EVIDENCE=ROOT/'docs/remediation/evidence'


def docker(*args):
    return subprocess.run(['docker',*args],check=True,capture_output=True,text=True,encoding='utf-8').stdout


def main():
    before=json.loads(docker('inspect','portal_qdrant'))[0]
    volumes=docker('volume','ls','--filter','label=com.docker.compose.project='+NAMESPACE,'--format','{{.Name}}').splitlines()
    for volume in volumes:
        assert volume.startswith(NAMESPACE+'_')
        item=json.loads(docker('volume','inspect',volume))[0]
        assert item['Labels']['com.docker.compose.project']==NAMESPACE
    containers=docker('ps','-aq','--filter','label=com.docker.compose.project='+NAMESPACE).splitlines()
    for container in containers:
        item=json.loads(docker('inspect',container))[0]
        assert item['Config']['Labels']['com.docker.compose.project']==NAMESPACE
    override=ROOT.parents[2]/'tmp/remediation-20261020/compose.final.yaml'
    output=docker('compose','-p',NAMESPACE,'-f',str(ROOT/'infra/compose.yaml'),'-f',str(ROOT/'infra/compose.indexes.yaml'),
                  '-f',str(ROOT/'infra/compose.gpu.yaml'),'-f',str(override),'down','--volumes')
    after=json.loads(docker('inspect','portal_qdrant'))[0]
    report={'status':'PASS','removed_namespace':NAMESPACE,'test_containers':len(containers),'new_test_volumes':volumes,
            'remaining_test_containers':docker('ps','-aq','--filter','label=com.docker.compose.project='+NAMESPACE).splitlines(),
            'portal_qdrant':{'same_container':before['Id']==after['Id'],'same_started_at':before['State']['StartedAt']==after['State']['StartedAt'],
                             'running':after['State']['Running'],'health':after['State'].get('Health',{}).get('Status')},
            'original_assets':'No command targets original data, model weights, credentials, indices or other compose projects; tested image retained'}
    assert not report['remaining_test_containers']
    assert report['portal_qdrant']['same_container'] and report['portal_qdrant']['same_started_at']
    (EVIDENCE/'cleanup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),output)


if __name__=='__main__':main()
