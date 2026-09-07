"""Translate legacy project settings and identify files requiring review."""

from copy import deepcopy
import json
import re
import tomllib

import yaml

from transaction import read_state, validate_path

FIELDS = set('''projectName odooVersion python postgres ports dbName dbUser dbPasswordFile
projectDirVar editor editorSettings useQueueJob defaultRepoPattern customRepoPattern
customRepoName useClaudeCode modulePrefix ticketPrefix readmeGenSource statusMcp ticketsMcp
odooProdUrl usePipeline backupS3Bucket prodSshHost prodSshUser prodWebUrl prodRemoteProjectDir
prodRemoteOdooConf prodDbName prodLinkAddonsCmd testSshHost testSshUser testSshPort
 testLocalForward testWebUrl serviceSuffix frameworkSource repositories'''.split())
COMPUTED = {'derived', 'odooMajor', 'odooCmd', 'nixProfileRel', 'nixProfileFlag'}
PORTS = {'odoo_http_port': 'http', 'odoo_gevent_port': 'gevent', 'nginx_port': 'nginx', 'postgres_port': 'pg'}
ALIASES = {'python_version': 'python', 'postgres_version': 'postgres'}
SECRET_PATH = '.nixodoo/secrets/db-password'


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError('legacy YAML requires unique string keys')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_yaml(text, *, multiple=False):
    try:
        documents = list(yaml.load_all(text, Loader=UniqueLoader))
    except yaml.YAMLError as error:
        raise ValueError('cannot parse legacy YAML') from error
    if multiple:
        return documents
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise ValueError('expected one YAML mapping')
    return documents[0]


def import_answers(answers):
    if not isinstance(answers, dict):
        raise ValueError('legacy settings must be a mapping')
    config, password = {}, None
    for key, value in answers.items():
        if key.startswith('_'):
            continue
        if key in PORTS:
            config.setdefault('ports', {})[PORTS[key]] = value
            continue
        name = ALIASES.get(key, re.sub(r'_([a-z])', lambda match: match[1].upper(), key))
        if name in COMPUTED:
            continue
        if name == 'dbPassword':
            if not isinstance(value, str):
                raise ValueError('legacy database password must be a string')
            password = value
        elif name not in FIELDS:
            raise ValueError(f'unrecognized legacy setting: {key}')
        elif name in config:
            raise ValueError(f'duplicate legacy setting: {key}')
        else:
            config[name] = value
    if 'postgres' in config and isinstance(config['postgres'], str) and config['postgres'].isdigit():
        config['postgres'] = int(config['postgres'])
    secret = None
    if password not in (None, '', 'odoo') and not config.get('dbPasswordFile'):
        config['dbPasswordFile'] = SECRET_PATH
        secret = (password + '\n').encode()
    return config, secret


def import_customizations(project, settings):
    config = deepcopy(settings)
    imported = {}

    def document(path, parse):
        state = read_state(project, path)
        if state is None:
            return None
        imported[path] = state
        try:
            return parse((project / path).read_text())
        except (json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f'cannot parse customization: {path}') from error

    repos = document('repos.yaml', parse_yaml)
    if repos is not None:
        base = []
        for path, declaration in repos.items():
            if not isinstance(declaration, dict) or set(declaration) - {'remotes', 'target', 'revision'}:
                raise ValueError(f'unsupported repository instructions: {path}')
            remotes = declaration.get('remotes', {})
            target = declaration.get('target', '')
            if not isinstance(remotes, dict) or not isinstance(target, str):
                raise ValueError(f'invalid repository remote or target: {path}')
            target = target.split()
            if len(remotes) != 1 or len(target) != 2 or target[0] not in remotes:
                raise ValueError(f'repository requires one remote and an explicit branch: {path}')
            entry = {'path': path.removeprefix('./'), 'url': remotes[target[0]], 'branch': target[1]}
            if 'revision' in declaration:
                entry['revision'] = declaration['revision']
            base.append(entry)
        config.setdefault('repositories', {})['base'] = base
    documents = document('addons.yaml', lambda text: parse_yaml(text, multiple=True))
    if documents is not None:
        addons, seen = [], set()
        for data in documents:
            if not isinstance(data, dict):
                raise ValueError('addon documents must be mappings')
            environment = data.get('ENV', {})
            if not isinstance(environment, dict) or set(environment) - {'DEFAULT_REPO_PATTERN', 'ODOO_VERSION'}:
                raise ValueError('unsupported addon environment values')
            pattern = environment.get('DEFAULT_REPO_PATTERN', config.get('defaultRepoPattern', 'https://github.com/OCA/{}.git'))
            if not isinstance(pattern, str):
                raise ValueError('addon URL patterns must be strings')
            branch = str(environment.get('ODOO_VERSION', config.get('odooVersion', '19.0')))
            for name, value in data.items():
                if name == 'ENV':
                    continue
                if name in seen:
                    raise ValueError(f'duplicate addon repository: {name}')
                seen.add(name)
                entry = {'name': name, 'url': pattern.replace('{}', name), 'branch': branch}
                if isinstance(value, list):
                    entry['modules'] = value
                elif isinstance(value, dict) and not set(value) - {'modules', 'revision'}:
                    entry.update(value)
                    entry.setdefault('modules', ['*'])
                else:
                    raise ValueError(f'unsupported addon declaration: {name}')
                addons.append(entry)
        config.setdefault('repositories', {})['addons'] = addons
    for path, key, parse in (('.vscode/settings.json', 'vscode', json.loads),
                             ('.zed/settings.json', 'zed', json.loads),
                             ('odools.toml', 'odools', tomllib.loads)):
        value = document(path, parse)
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError(f'editor settings must be a mapping: {path}')
            config.setdefault('editorSettings', {})[key] = value
    return config, imported


def validate_preserve(path):
    validate_path(path)
    if path in ('nix', 'flake.nix', 'flake.lock') or path.startswith('nix/'):
        raise ValueError(f'framework code requires review and cannot be preserved: {path}')
    return path
