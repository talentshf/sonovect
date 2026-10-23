"""Fail closed on incomplete actual-image release evidence; never publishes."""
import argparse
import json
import re
from pathlib import Path
from check_os_audit import classify as classify_os
from check_dependency_audit import classify as classify_python

ROOT = Path(__file__).resolve().parents[1]
ROLES = {'core', 'worker', 'native', 'vocal', 'provider', 'segmentation', 'asr', 'events', 'sound', 'measurements', 'qwen', 'analysis', 'analysis-measurements'}


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def validate(evidence, images, revision, version):
    if {row['role'] for row in images} != ROLES or len(images) != len(ROLES):
        raise ValueError('incomplete_or_duplicate_image_roles')
    statements = json.loads((ROOT/'docs/security/dependency-dispositions.json').read_text())['statements']
    records = []
    for image in images:
        role = image['role']; directory = evidence/role
        if image['source'] != revision or image['version'] != version or not re.fullmatch(r'sha256:[0-9a-f]{64}', image['image']):
            raise ValueError('image_identity_or_version_drift:'+role)
        facts = json.loads((directory/'facts.json').read_text())
        if facts.get('image_id') != image['image'] or facts.get('source_revision') != revision:
            raise ValueError('facts_identity_drift:'+role)
        os_result = classify_os(json.loads((directory/'os-audit.json').read_text()), facts)
        if os_result['unresolved_high_critical'] or os_result['unresolved_lower_severity']:
            raise ValueError('unreviewed_os_findings:'+role)
        audit = json.loads((directory/'python-audit.json').read_text())
        mapped = {'worker': 'media-worker', 'qwen': 'asr', 'analysis': 'vocal', 'analysis-measurements': 'measurements'}.get(role, role)
        python_result = classify_python(audit, statements, role=mapped, platform='linux')
        if python_result['unresolved'] or python_result['skipped']:
            raise ValueError('unreviewed_or_skipped_python:'+role)
        installed = json.loads((directory/'python-installed.json').read_text())
        expected = {normalized(x['name']): x['version'].split('+')[0] for x in installed
                    if normalized(x['name']) not in {'sonovect', 'moss-audio'}}
        observed = {normalized(x['name']): x['version'].split('+')[0] for x in audit['dependencies']}
        if observed != expected:
            raise ValueError('python_audit_coverage_drift:'+role)
        if any(x['version'] != version for x in installed if normalized(x['name']) == 'sonovect'):
            raise ValueError('installed_project_version_drift:'+role)
        if 'No broken requirements found.' not in (directory/'pip-check.log').read_text():
            raise ValueError('dependency_consistency_failed:'+role)
        inventory = json.loads((directory/'license-inventory.json').read_text())
        if inventory.get('image_id') != image['image'] or inventory.get('uid') != 10001 or not inventory.get('os_source_files'):
            raise ValueError('missing_source_or_license_inventory:'+role)
        names = {normalized(x['name']) for x in installed}
        if {normalized(x['name']) for x in inventory['python']} != names:
            raise ValueError('license_inventory_coverage_drift:'+role)
        if {normalized(x['name']): x['version'] for x in inventory['python']} != {normalized(x['name']): x['version'] for x in installed}:
            raise ValueError('license_inventory_version_drift:'+role)
        for item in inventory['python']:
            if item.get('declaration') or item.get('files'):
                continue
            # This exact NVIDIA metapackage ships only dist-info metadata, no code.
            files = item.get('installed_files', [])
            metadata_only = (normalized(item['name']) == 'cuda-toolkit' and item['version'] == '13.2.2'
                             and files and all('/' in f and '.dist-info/' in f for f in files)
                             and item.get('metadata_sha256'))
            if not metadata_only:
                raise ValueError('missing_python_license_metadata:'+role+':'+item['name'])
        if role == 'sound':
            required = {'upstream.tar', 'UPSTREAM-LICENSE-STATEMENT.md', 'README.md', 'pyproject.toml', 'prepare_runtime.py'}
            if not required <= {x['path'] for x in inventory.get('moss_source_files', [])} or inventory.get('source_archive_has_no_demo_media_or_weights') is not True:
                raise ValueError('missing_moss_corresponding_source_or_notice')
        if role in {'measurements', 'analysis-measurements'} and names & {'torch', 'torchaudio', 'funasr', 'transformers', 'moss-audio'}:
            raise ValueError('measurement_role_contains_model_framework')
        records.append({'role': role, 'image': image['image'], 'os_raw_matches': os_result['raw_matches'],
                        'python_packages': len(installed), 'source_license_inventory': True})
    return {'version': version, 'revision': revision, 'engineering_gate': 'passed',
            'publication': 'not_performed', 'roles': records,
            'component_sources': 'Optional component source and declaration records are informational and retained in the distribution.',
            'limitations': 'Eight reviewed OS service-boundary IDs remain; Chinese emotion is experimental and measured quality has a limited scope.'}


def validate_configuration(config):
    """Validate resolved standard recipes without printing environment values."""
    if not {'api', 'worker'} <= set(config['services']):
        raise ValueError('missing_api_or_worker')
    all_jobs, all_models = set(), set()
    for name, service in config['services'].items():
        if service.get('privileged') or 'ALL' not in service.get('cap_drop', []):
            raise ValueError('unsafe_container_privileges:'+name)
        if not any(x in {'no-new-privileges:true', 'no-new-privileges=true'} for x in service.get('security_opt', [])):
            raise ValueError('missing_no_new_privileges:'+name)
        if name != 'api' and service.get('ports'):
            raise ValueError('private_model_or_worker_port_published:'+name)
        user = service.get('user')
        if user and str(user) not in {'10001', '10001:10001'}:
            raise ValueError('unexpected_container_user:'+name)
        volumes = service.get('volumes', [])
        jobs, models = set(), set()
        for volume in volumes:
            if isinstance(volume, str):
                parts = volume.split(':'); source, target = parts[:2]
            else:
                source, target = volume.get('source'), volume['target']
            if target == '/data': jobs.add(source)
            if target == '/models' or target.startswith('/models/'): models.add(source)
        all_jobs.update(jobs); all_models.update(models)
        if jobs & models:
            raise ValueError('job_and_model_storage_overlap:'+name)
    if all_jobs & all_models:
        raise ValueError('job_and_model_storage_overlap_across_services')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--images', type=Path)
    parser.add_argument('--revision')
    parser.add_argument('--version', default='0.1.0')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compose-config', type=Path, help='Resolved standard Compose JSON; environment values are never printed')
    args = parser.parse_args()
    try:
        if not args.evidence or not args.images or not args.revision:
            raise ValueError('actual_image_evidence_images_and_revision_required')
        if args.compose_config:
            validate_configuration(json.loads(args.compose_config.read_text()))
        result = validate(args.evidence, json.loads(args.images.read_text()), args.revision, args.version)
        content = json.dumps(result, indent=2)+'\n'
        if args.output: args.output.write_text(content)
        else: print(content, end='')
        return 0
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({'gate': 'failed', 'reason': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
