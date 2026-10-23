param(
  [Parameter(Mandatory=$true)][string]$ImageId,
  [string]$Evidence = 'docs/remediation/evidence'
)
$ErrorActionPreference='Stop'
if ($ImageId -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Use tested immutable local image ID, never a mutable tag' }
$projectRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path.Replace('\','/')
$evidenceRoot=(Resolve-Path -LiteralPath (Join-Path $projectRoot $Evidence)).Path.Replace('\','/')
# Manifest generation does not rebuild/tag/push/deploy an image.
docker run --rm --network none --mount "type=bind,source=$evidenceRoot,target=/evidence" --entrypoint python $ImageId -m backend.release --image-digest $ImageId --eval /evidence/eval-gpu.json --unit /evidence/verification.json --cpu /evidence/integration-cpu.json --gpu /evidence/integration-gpu.json --gpu-regression /evidence/gpu-regression.json --output /evidence/release-manifest.json
exit $LASTEXITCODE
