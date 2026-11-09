"""Portable filesystem notebook. No Levin imports, network, scheduler or data deletion."""
from __future__ import annotations
import copy, hashlib, json, os, re, shutil, socket, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from filelock import FileLock
from jsonschema import Draft202012Validator

MAX_RECORD = 2_000_000

# Unit problems that make a recorded number uninterpretable rather than merely
# unconventional; these are surfaced before the conclusion, not buried in a table.
BLOCKING_UNIT_CODES = ('dimension_mismatch','unparsable_unit','missing_unit',
                       'non_numeric','non_finite','negative_uncertainty',
                       'uncertainty_unit_mismatch','inconsistent_unit',
                       # A wrong-but-legal unit rescales the number silently: 2.26 nm
                       # reads as 22.6 Å. Opt out per quantity with unit_acknowledged.
                       'unit_scale','unknown_quantity','unparsable_dimension')
HASH_BUDGET = 64 * 1024 * 1024
LARGE_COPY_BYTES = 64 * 1024 * 1024
LIGHT_OUTPUT_BYTES = 64 * 1024 * 1024
USAGE_CAP = 200000
SLUG = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$')
EXP = re.compile(r'^exp-[0-9a-f]{32}$')

def now(): return datetime.now(timezone.utc).isoformat()
def uid(prefix): return prefix + '-' + uuid.uuid4().hex
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def human_bytes(value):
    """Human-readable size: B, KB, MB, GB, TB with one decimal for scaled units."""
    try: value = float(value)
    except (TypeError, ValueError): return 'unknown'
    sign = '-' if value < 0 else ''
    size = abs(value)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f"{sign}{size:.0f} B" if unit == 'B' else f"{sign}{size:.1f} {unit}"
        size /= 1024.0
    return f"{sign}{size:.1f} TB"


def usage(root, cap=USAGE_CAP):
    """Bounded recursive byte usage. Symlinks are never followed, so external data is not counted twice."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink(): return {'bytes': 0, 'files': 0, 'truncated': False}
    total = files = visited = 0; truncated = False; stack = [root]
    while stack:
        visited += 1
        if visited > cap: truncated = True; break
        item = stack.pop()
        if item.is_symlink(): continue
        if item.is_dir():
            try: stack.extend(item.iterdir())
            except OSError: pass
        elif item.is_file():
            try: total += item.stat().st_size; files += 1
            except OSError: pass
    return {'bytes': total, 'files': files, 'truncated': truncated}


def usage_delta(baseline, current):
    if not baseline or not current: return None
    keys = [k for k in current if k in baseline]
    return {k: {'bytes': current[k]['bytes'] - baseline[k]['bytes'], 'files': current[k]['files'] - baseline[k]['files']} for k in keys}


VAGUE_FAILURES = {'无结果', 'no result', 'failed', 'fail', 'error', 'n/a', 'na', 'none', '失败', '没结果', '见日志', 'see log'}


def _specific(value, what):
    """Reject the shorthand the lab-record standard explicitly forbids."""
    text_value = (value or '').strip()
    if text_value.casefold() in VAGUE_FAILURES or len(text_value) < 15:
        raise NotebookError(what + ' must state what went wrong concretely (at least 15 characters); '
                            '"无结果"/"failed"/"error" style shorthand is not accepted')


class NotebookError(ValueError): pass


# A caller may identify an artifact or run either by the server id it was given or by
# the reference_id it registered itself. Both used to look "unknown" in every *other*
# field, which cost a real user five failed calls, so resolution happens in one place.
def _known_artifacts(m):
    return {a['id']: a for a in m['artifacts']}


def _resolve_artifact(ref, known):
    if not isinstance(ref, str):
        return None
    if ref in known:
        return known[ref]
    for artifact in known.values():
        if artifact.get('reference_id') == ref:
            return artifact
    return None


def _resolve_run(ref, runs):
    if not isinstance(ref, str):
        return None
    for run in runs:
        if run['id'] == ref:
            return run
    for run in runs:
        if run.get('reference_id') == ref:
            return run
    return None


def _sample_ids(table, limit=4):
    """A short, honest hint: what the caller could have passed instead."""
    names = []
    for key, value in table.items():
        alias = value.get('reference_id') if isinstance(value, dict) else None
        names.append(f'{key}' + (f' (alias {alias})' if alias else ''))
        if len(names) >= limit:
            break
    return ', '.join(names) if names else 'none registered yet'


def text(value, name, required=True, limit=20000):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise NotebookError(f'{name} must be a nonempty string of at most {limit} characters')
    return value

def safe_name(value, name):
    if not isinstance(value, str) or not SLUG.fullmatch(value) or value in ('.','..'):
        raise NotebookError(f'Invalid {name}')
    return value

SCHEMA = {
 '$schema':'https://json-schema.org/draft/2020-12/schema', 'type':'object', 'additionalProperties':False,
 'required':['schema_version','experiment_id','task_id','created_at','updated_at','revision','title','objective','hypothesis','execution_status','interpretation','limitations','agents','checkpoints','artifacts','runs','visualization','reports','requests','retention'],
 'properties':{
 'schema_version':{'const':1}, 'experiment_id':{'type':'string','pattern':EXP.pattern},
 'task_id':{'type':'string','minLength':1},'created_at':{'type':'string'},'updated_at':{'type':'string'},
 'revision':{'type':'integer','minimum':1},'title':{'type':'string','minLength':1},'objective':{'type':'string','minLength':1},
 'hypothesis':{'type':'string'},'expected_result':{'type':'string'},'lessons':{'type':'array','items':{'type':'string'},'maxItems':100},'plans':{'type':'array','items':{'type':'string'},'maxItems':100},'execution_status':{'enum':['wip','success','failed']},
 'interpretation':{'type':'string'},'limitations':{'type':'string'},'retention':{'type':'string'},
 'agents':{'type':'array','items':{'type':'string'},'uniqueItems':True},
 'checkpoints':{'type':'array','maxItems':500,'items':{'type':'object','additionalProperties':False,'required':['id','created_at','agent_id','kind','text','evidence_ids'], 'properties':{'id':{'type':'string'},'created_at':{'type':'string'},'agent_id':{'type':'string'},'kind':{'enum':['method','observation','failure','conclusion','resume','note']},'text':{'type':'string','minLength':1},'evidence_ids':{'type':'array','items':{'type':'string'}},'title':{'type':'string'},'replica':{'type':['integer','null']},'retry':{'type':['integer','null']},'when_note':{'type':'string'},'refers_to':{'type':['string','null']},'supersedes':{'type':['string','null']}}}},
 'artifacts':{'type':'array','maxItems':500,'items':{'type':'object','additionalProperties':False,'required':['id','created_at','role','location','external','description','input_ids','script_id','run_id','sha256','checksum_origin','size_bytes','availability','conditions'], 'properties':{'id':{'type':'string'},'created_at':{'type':'string'},'role':{'enum':['raw','derived','script','figure','log','input','table','deliverable']},'location':{'type':'string','minLength':1},'external':{'type':'boolean'},'description':{'type':'string'},'input_ids':{'type':'array','items':{'type':'string'}},'script_id':{'type':['string','null']},'run_id':{'type':['string','null']},'sha256':{'type':['string','null'],'pattern':'^[a-f0-9]{64}$'},'source_origin':{'enum':['local_original','remote_copy','unspecified']},'remote_host':{'type':['string','null']},'remote_path':{'type':['string','null']},'remote_copy_permission':{'type':['string','null']},'reference_id':{'type':['string','null']},'checksum_origin':{'enum':['computed','supplied_unverified','not_computed']},'size_bytes':{'type':['integer','null'],'minimum':0},'availability':{'enum':['local','missing','external_unverified']},'conditions':{'type':'object'}}}},
 'runs':{'type':'array','maxItems':500,'items':{'type':'object','additionalProperties':False,'required':['id','created_at','backend','external_id','execution_status','command','parameters','environment','input_ids','output_ids','failure'], 'properties':{'id':{'type':'string'},'created_at':{'type':'string'},'backend':{'enum':['local','levin','slurm','external']},'host':{'type':'string','minLength':1},'external_id':{'type':'string'},'reference_id':{'type':['string','null']},'execution_status':{'enum':['wip','success','failed']},'command':{'type':'string'},'parameters':{'type':'object'},'environment':{'type':'object'},'input_ids':{'type':'array','items':{'type':'string'}},'output_ids':{'type':'array','items':{'type':'string'}},'failure':{'type':'string'}}}},
 'visualization':{'type':['object','null'],'additionalProperties':False,'required':['beneficial','reason','figure_ids','reviewed_by'], 'properties':{'beneficial':{'type':'boolean'},'reason':{'type':'string','minLength':1},'figure_ids':{'type':'array','items':{'type':'string'}},'reviewed_by':{'type':'string','minLength':1}}},
 'reports':{'type':'array','items':{'type':'object'}},'requests':{'type':'object'},
 'usage_at_init':{'type':'object'},'usage_at_finalize':{'type':'object'},'workspace_dir':{'type':'string'},
 'purpose':{'type':'string'},'environment_location':{'type':'string'},
 'record_type':{'enum':['experiment','analysis','literature_review']},
 'bibtex_source':{'type':['string','null']},'bibtex_path':{'type':['string','null']},'bibtex_warnings':{'type':'array','items':{'type':'string'}},
 'search_strategy':{'type':['object','null'],'additionalProperties':False,'properties':{'databases':{'type':'string'},'query':{'type':'string'},'window':{'type':'string'},'languages':{'type':'string'},'screening':{'type':'string'}}},
 'references':{'type':'array','maxItems':500,'items':{'type':'object','additionalProperties':False,'required':['id','citation'],'properties':{'id':{'type':'string','minLength':1,'maxLength':60},'citation':{'type':'string','minLength':1},'year':{'type':['integer','null']},'venue':{'type':'string'},'design':{'type':'string'},'sample':{'type':'string'},'key_findings':{'type':'string'},'evidence_level':{'type':'string'},'relevance':{'type':'string'},'read_full_text':{'type':['boolean','null']},'doi':{'type':'string'},'authors':{'type':'array','items':{'type':'string'}},'title':{'type':'string'},'entry_type':{'type':'string'},'section':{'type':'string'},'metadata_issues':{'type':'array','items':{'type':'string'}},'source':{'type':'string'}}}},
 'synthesis':{'type':'string'},
 'font_profile':{'type':'string','maxLength':60},
 'derived_from':{'type':'array','maxItems':50,'items':{'type':'string','pattern':'^exp-[0-9a-f]{32}$'}},

 'citations':{'type':'array','maxItems':2000,'items':{'type':'object','additionalProperties':False,'required':['from','to'],'properties':{'from':{'type':'string'},'to':{'type':'string'},'relation':{'type':'string'}}}},
 'reference_sections':{'type':'array','maxItems':50,'items':{'type':'object','additionalProperties':False,'required':['title'],'properties':{'title':{'type':'string','minLength':1,'maxLength':200},'text':{'type':'string','maxLength':20000}}}},
 'quantities':{'type':'array','maxItems':500,'items':{'type':'object','additionalProperties':False,'required':['name','value'],'properties':{'name':{'type':'string','minLength':1,'maxLength':120},'value':{'type':'number'},'unit':{'type':'string','maxLength':60},'dimension':{'type':'string','maxLength':60},'unit_acknowledged':{'type':'boolean'},'uncertainty':{'type':['number','null']},'uncertainty_unit':{'type':'string','maxLength':60},'note':{'type':'string','maxLength':1000},'artifact_id':{'type':'string','maxLength':120},'replica':{'type':['integer','null'],'minimum':1}}}},

 'extra_sections':{'type':'array','maxItems':30,'items':{'type':'object','additionalProperties':False,'required':['title','text'],'properties':{'title':{'type':'string','minLength':1,'maxLength':200},'text':{'type':'string','minLength':1}}}},
 'implementer':{'type':['object','null'],'additionalProperties':False,'properties':{'kind':{'enum':['user','agent']},'name':{'type':'string'},'model':{'type':'string'}}},
 'strategy':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['title','text'],'properties':{'title':{'type':'string','minLength':1},'text':{'type':'string','minLength':1}}},'maxItems':50},
 'method_plan':{'type':'array','items':{'type':'string'},'maxItems':100},
 'materials':{'type':['object','null'],'additionalProperties':False,'properties':{'datasets':{'type':'array','items':{'type':'string'}},'software':{'type':'array','items':{'type':'string'}},'notes':{'type':'string'}}},
 'results':{'type':['object','null'],'additionalProperties':False,'properties':{'expected_seen':{'type':'array','items':{'type':'string'}},'unexpected_seen':{'type':'array','items':{'type':'string'}},'expected_not_seen':{'type':'array','items':{'type':'string'}},'incidents':{'type':'array','items':{'type':'string'}}}},
 'footnotes':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['label','text'],'properties':{'label':{'type':'string'},'text':{'type':'string'}}},'maxItems':200},
 'remote_space':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['host','path','bytes'],'properties':{'host':{'type':'string'},'path':{'type':'string'},'bytes':{'type':'integer','minimum':0},'files':{'type':['integer','null']},'measured_at':{'type':'string'},'note':{'type':'string'}}},'maxItems':50}
 }}
VALIDATOR = Draft202012Validator(SCHEMA)

class Notebook:
    def __init__(self, workspace_dir):
        self.workspace = Path(workspace_dir).expanduser().resolve()
        if not self.workspace.is_dir(): raise NotebookError('workspace_dir must exist')
        self.root = self.workspace / 'levin_notebook'
        self.scratch = self.workspace / 'levin_scratch'
        for p in (self.root, self.scratch):
            if p.is_symlink(): raise NotebookError(f'Symlink managed root rejected: {p}')
        self.tmp = self.scratch / 'notebook-system' / 'writer'

    def _guard(self, path):
        path = Path(path)
        if not path.is_relative_to(self.workspace): raise NotebookError('Managed path escapes workspace')
        for p in [path, *path.parents]:
            if p == self.workspace: break
            if p.is_symlink(): raise NotebookError(f'Symlink managed path rejected: {p}')
        return path

    def _lock(self):
        self._guard(self.root).mkdir(parents=True, exist_ok=True)
        return FileLock(str(self._guard(self.root / '.notebook.lock')), timeout=10)

    def _atomic(self, path, content):
        path = self._guard(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._guard(self.tmp).mkdir(parents=True, exist_ok=True)
        tmp = self.tmp / (uuid.uuid4().hex + '.pending')
        with open(tmp, 'x', encoding='utf-8') as f:
            f.write(content); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)

    def _dir(self, eid):
        if not isinstance(eid,str) or not EXP.fullmatch(eid): raise NotebookError('Invalid experiment_id')
        return self._guard(self.root / 'experiments' / eid)

    def _load(self, eid):
        path = self._dir(eid) / 'manifest.json'
        self._guard(path)
        if not path.is_file(): raise NotebookError(f'No experiment record exists for {eid}')
        if path.stat().st_size > MAX_RECORD: raise NotebookError('Manifest exceeds the 2 MB limit; split into linked experiments')
        m = json.loads(path.read_text())
        VALIDATOR.validate(m)
        if m['experiment_id'] != eid: raise NotebookError('Manifest identity mismatch')
        return m

    def _save(self, m):
        VALIDATOR.validate(m)
        s = canonical(m)
        if len(s.encode()) > MAX_RECORD: raise NotebookError('Manifest limit exceeded; split into linked experiments')
        d = self._dir(m['experiment_id'])
        snapshot = d / 'revisions' / f"{m['revision']:06d}-{uuid.uuid4().hex}.json"
        if (d / 'record.md').is_file() and (d / 'manifest.json').is_file():
            previous = json.loads((d / 'manifest.json').read_text())
            current_text = (d / 'record.md').read_text()
            if current_text != self.markdown(previous):
                self._atomic(d / 'revisions' / ('human-record-' + uuid.uuid4().hex + '.md'), current_text)
        self._atomic(snapshot, s)
        self._atomic(d / 'manifest.json', s)
        self._atomic(d / 'record.md', self.markdown(m))
        self._write_index()

    def _write_index(self):
        rows, errors = self.index(limit=10000)
        out = '# Research notebook\n\nGenerated index; experiment manifests are authoritative.\n\n'
        for r in rows:
            out += f"- [{r['experiment_id']}](experiments/{r['experiment_id']}/record.md) — {r['title'].replace(chr(10),' ')} — {r['execution_status']} — {r['created_at']}\n"
        for e in errors: out += f"- INVALID: {e['experiment_id']} — {e['error']}\n"
        self._atomic(self.root / 'index.md', out)

    def summary(self,m):
        d = self._dir(m['experiment_id'])
        return {'ok':True,'experiment_id':m['experiment_id'],'revision':m['revision'],'execution_status':m['execution_status'],'manifest_path':str(d/'manifest.json'),'record_path':str(d/'record.md')}

    def init(self, task_id, agent_id, title, objective, hypothesis='', experiment_id=None, retention='retain until explicit user-approved policy', expected_result='', purpose='', implementer=None, environment_location='', record_type='experiment', derived_from=()):
        safe_name(task_id,'task_id'); safe_name(agent_id,'agent_id'); text(title,'title',limit=300); text(objective,'objective'); text(hypothesis,'hypothesis',False); text(expected_result,'expected_result',False); text(purpose,'purpose',False); text(environment_location,'environment_location',False,limit=4096)
        if record_type not in ('experiment','analysis','literature_review'): raise NotebookError('record_type must be experiment, analysis or literature_review')
        parents=[]
        for parent in derived_from or ():
            if not isinstance(parent,str) or not re.fullmatch(r'exp-[0-9a-f]{32}',parent):
                raise NotebookError(f'derived_from accepts experiment ids (exp-<32 hex>), got {parent!r}')
            if parent not in parents: parents.append(parent)
        if implementer is not None:
            if not isinstance(implementer,dict) or set(implementer)-{'kind','name','model'}:
                raise NotebookError(f'implementer must be an object with kind/name/model, got {type(implementer).__name__}; '
                                    'pass {"kind": "agent", "name": ...} rather than a JSON string')
            if implementer.get('kind') not in ('user','agent'): raise NotebookError('implementer.kind must be user or agent')
            for key in ('name','model'):
                if key in implementer: text(implementer[key],'implementer.'+key,limit=200)
        with self._lock():
            baseline={'captured_at':now(),'notebook':usage(self.root),'scratch':usage(self.scratch)}
            matches = []
            for p in (self.root/'experiments').glob('exp-*/manifest.json'):
                try:
                    candidate = self._load(p.parent.name)
                except Exception:
                    continue  # index/validate expose corrupt records; never rewrite them
                if candidate['task_id'] == task_id: matches.append(p.parent.name)
            if len(matches)>1: raise NotebookError('Duplicate task identity; explicit repair required')
            if experiment_id and matches and experiment_id != matches[0]: raise NotebookError('task_id and experiment_id conflict')
            eid = experiment_id or (matches[0] if matches else None)
            if eid:
                m=self._load(eid)
                if m['task_id'] != task_id or m['objective'] != objective or m['title'] != title: raise NotebookError('Resume identity conflicts with recorded task; use a new task_id')
                patched = False
                if expected_result and not m.get('expected_result'):
                    m['expected_result']=expected_result; patched=True
                # Backfill only when nothing was recorded: the point is to repair a
                # missing attribute, never to rewrite who did the work.
                if implementer and not m.get('implementer'):
                    m['implementer']=dict(implementer); patched=True
                if environment_location and not m.get('environment_location'):
                    m['environment_location']=environment_location; patched=True
                if parents and not m.get('derived_from'):
                    m['derived_from']=list(parents); patched=True
                if patched:
                    m['revision']+=1; m['updated_at']=now(); self._save(m)
                changed=agent_id not in m['agents']
                if changed:
                    m['agents'].append(agent_id); m['revision']+=1; m['updated_at']=now(); self._save(m)
                resumed=True
            else:
                eid=uid('exp'); t=now()
                m=dict(schema_version=1,experiment_id=eid,task_id=task_id,created_at=t,updated_at=t,revision=1,title=title,objective=objective,hypothesis=hypothesis,execution_status='wip',interpretation='',limitations='',agents=[agent_id],checkpoints=[],artifacts=[],runs=[],visualization=None,reports=[],requests={},retention=retention,usage_at_init=baseline,expected_result=expected_result,lessons=[],plans=[],workspace_dir=str(self.workspace),purpose=purpose,implementer=implementer,environment_location=environment_location,strategy=[],method_plan=[],materials={},results={},footnotes=[],remote_space=[],record_type=record_type,search_strategy=None,references=[],synthesis='',citations=[],extra_sections=[],reference_sections=[],quantities=[],derived_from=list(parents))
                self._dir(eid).mkdir(parents=True,exist_ok=False)
                for n in ('scripts','figures','data','reports','revisions'): (self._dir(eid)/n).mkdir()
                self._atomic(self._dir(eid)/'notes.md','# Human notes\n\nEditable notes; record.md is a generated view. Capture scientific claims with checkpoint evidence IDs.\n')
                self._save(m); resumed=False
            scratch=self._guard(self.scratch/task_id/agent_id); scratch.mkdir(parents=True,exist_ok=True)
            gitignore=self.root/'.gitignore'
            if not gitignore.exists(): self._atomic(gitignore,'# Data are references by default; explicitly select any small files to version.\n**/data/\n**/*.xtc\n**/*.trr\n**/*.dcd\n**/*.h5\n**/*.hdf5\n**/*.npy\n**/*.npz\n**/*.fastq*\n**/*.bam\n.notebook.lock\n')
            self._atomic(self.root/'manifest.schema.json',canonical(SCHEMA))
            return {**self.summary(m),'resumed':resumed,'scratch_dir':str(scratch)}

    def mutate(self,eid,request_id,payload,fn,memoize=None):
        with self._lock():
            m=self._load(eid)
            fingerprint=hashlib.sha256(canonical(payload).encode()).hexdigest()
            if request_id:
                safe_name(request_id,'request_id')
                if request_id in m['requests']:
                    receipt=m['requests'][request_id]
                    if receipt['fingerprint']!=fingerprint: raise NotebookError('request_id reused with different content')
                    return {**self.summary(m),**receipt['result'],'idempotent':True}
            result=fn(m) or {}
            m['revision']+=1; m['updated_at']=now()
            if request_id and (memoize is None or memoize(result)): m['requests'][request_id]={'fingerprint':fingerprint,'result':result}
            self._save(m)
            return {**self.summary(m),**result}

    def checkpoint(self,eid,agent_id,kind,body,evidence_ids=(),request_id=None,execution_status=None,title='',replica=None,retry=None,when_note='',refers_to=None,supersedes=None):
        safe_name(agent_id,'agent_id'); text(body,'text'); text(title,'title',False,limit=200); text(when_note,'when_note',False,limit=200)
        for value,name in ((replica,'replica'),(retry,'retry')):
            if value is not None and (not isinstance(value,int) or isinstance(value,bool) or value<1): raise NotebookError(name+' must be a positive integer when given')
        if refers_to is not None: text(refers_to,'refers_to',limit=200)
        if supersedes is not None: text(supersedes,'supersedes',limit=200)
        if kind=='failure': _specific(body,'failure checkpoint')
        p=dict(op='checkpoint',agent_id=agent_id,kind=kind,body=body,evidence_ids=list(evidence_ids),execution_status=execution_status,title=title,replica=replica,retry=retry,when_note=when_note,refers_to=refers_to,supersedes=supersedes)
        def change(m):
            arts=_known_artifacts(m)
            resolved=[]
            for ref in evidence_ids:
                target=_resolve_artifact(ref,arts)
                if target is None:
                    target=_resolve_run(ref,m['runs'])
                if target is None:
                    raise NotebookError(f'Unknown checkpoint evidence reference {ref!r}; evidence_ids takes artifact or run '
                                        f'ids only, not checkpoint ids. Known: {_sample_ids(arts)}')
                resolved.append(target['id'])
            if kind=='conclusion' and not resolved: raise NotebookError('Conclusions require evidence references')
            if supersedes:
                earlier=[c for c in m['checkpoints'] if c['id']==supersedes]
                if not earlier:
                    raise NotebookError(f'supersedes must name an earlier checkpoint id (checkpoint-…); got {supersedes!r}. '
                                        'Checkpoints are not artifacts or runs, and they have no alias.')
                if earlier[0]['kind'] not in ('conclusion','observation','method'):
                    raise NotebookError(f'cannot supersede a {earlier[0]["kind"]} checkpoint; only an earlier conclusion, '
                                        'observation or method is correctable (a failure stays as it happened)')
            if execution_status: m['execution_status']=execution_status
            c=dict(id=uid('checkpoint'),created_at=now(),agent_id=agent_id,kind=kind,text=body,evidence_ids=resolved,title=title,replica=replica,retry=retry,when_note=when_note,refers_to=refers_to,supersedes=supersedes)
            m['checkpoints'].append(c)
            if agent_id not in m['agents']: m['agents'].append(agent_id)
            return {'checkpoint_id':c['id']}
        return self.mutate(eid,request_id,p,change)

    def location(self,value):
        text(value,'location',limit=4096)
        parsed=urlsplit(value)
        if parsed.scheme and parsed.scheme!='file':
            if parsed.scheme not in ('ssh','s3','https','http','slurm','dvc','datalad','levin-remote'): raise NotebookError('Unsupported reference scheme')
            if parsed.username or parsed.password or parsed.query or parsed.fragment: raise NotebookError('Credential/userinfo/query-bearing references are forbidden')
            return value,True,None
        if parsed.scheme=='file': raise NotebookError('Use a filesystem path instead of file://')
        path=Path(value).expanduser()
        if not path.is_absolute(): path=self.workspace/path
        path=path.absolute()
        if path.is_symlink(): raise NotebookError('Artifact symlink rejected; register the resolved original explicitly')
        resolved=path.resolve()
        return (str(resolved.relative_to(self.workspace)) if resolved.is_relative_to(self.workspace) else str(resolved)),not resolved.is_relative_to(self.workspace),resolved

    def register_artifact(self,eid,artifact,request_id=None):
        allowed={'role','location','description','input_ids','script_id','run_id','sha256','conditions','source_origin','remote_host','remote_path','remote_copy_permission','reference_id'}
        if set(artifact)-allowed: raise NotebookError('Unknown artifact metadata fields')
        artifact=dict(artifact)   # never mutate the caller's object; a replay must fingerprint identically
        reference_id=artifact.get('reference_id')
        if reference_id is not None: text(reference_id,'reference_id',limit=60)
        source_origin=artifact.get('source_origin','unspecified')
        if source_origin not in ('local_original','remote_copy','unspecified'): raise NotebookError('source_origin must be local_original, remote_copy or unspecified')
        permission=artifact.get('remote_copy_permission')
        if permission is not None: text(permission,'remote_copy_permission',limit=2000)
        remote_host=artifact.get('remote_host'); remote_path=artifact.get('remote_path')
        for value,name in ((remote_host,'remote_host'),(remote_path,'remote_path')):
            if value is not None: text(value,name,limit=512)
        location,external,path=self.location(artifact['location'])
        supplied=artifact.get('sha256')
        sha=None; size=None; origin='not_computed'; availability='external_unverified'
        if path is not None:
            if path.exists() and not path.is_file(): raise NotebookError('Register individual regular files, not directories')
            if path.exists():
                size=path.stat().st_size; availability='local'
                if size <= HASH_BUDGET:
                    before=path.stat(); sha=digest(path); after=path.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise NotebookError('Artifact changed while hashing')
                    origin='computed'
                    if supplied and supplied!=sha: raise NotebookError('Supplied checksum does not match file')
            else: availability='missing'
        if sha is None and supplied: sha=supplied; origin='supplied_unverified'
        if path and path.is_relative_to(self.scratch) and artifact['role'] in ('raw','input'):
            raise NotebookError('Raw/input evidence cannot be registered as scratch; preserve original outside levin_scratch')
        # Policy: remote raw data stays remote. Anything sourced from a remote host must name the host
        # and its original path; landing a remote ORIGINAL additionally needs explicit permission.
        if source_origin=='remote_copy':
            if not remote_host: raise NotebookError('source_origin=remote_copy requires remote_host naming the machine the data came from')
            if not remote_path: raise NotebookError('source_origin=remote_copy requires remote_path giving the original location on that host')
            if artifact['role'] in ('raw','input') and not permission:
                raise NotebookError('Remote raw/input evidence should stay on '+remote_host+' and be registered as an external reference; landing a copy requires remote_copy_permission naming who authorized it')
            if artifact['role'] in ('raw','input') and size and size>LARGE_COPY_BYTES:
                raise NotebookError('A '+format(size)+'-byte remote original must stay on '+remote_host+' and be referenced; permission covers small working copies only')
        def change(m):
            known=_known_artifacts(m)
            for ref in artifact.get('input_ids',[]):
                if _resolve_artifact(ref,known) is None:
                    raise NotebookError(f'Unknown artifact input reference {ref!r}; pass an artifact_id (artifact-…) '
                                        f'or the reference_id you registered it with. Known: {_sample_ids(known)}')
            if artifact.get('script_id'):
                target=_resolve_artifact(artifact['script_id'],known)
                if target is None or target['role']!='script':
                    scripts={k:v for k,v in known.items() if v['role']=='script'}
                    raise NotebookError(f'Unknown plotting/analysis script {artifact["script_id"]!r}; it must name a '
                                        f'registered artifact with role=script. Known scripts: {_sample_ids(scripts)}')
            if artifact.get('run_id') and _resolve_run(artifact['run_id'],m['runs']) is None:
                raise NotebookError(f'Unknown run reference {artifact["run_id"]!r}; use the run_id returned by '
                                    f'register_run or the reference_id it was registered with. '
                                    f'Known: {_sample_ids({r["id"]:r for r in m["runs"]})}')
            if artifact['role']=='figure':
                run=_resolve_run(artifact.get('run_id') or '', m['runs']) if artifact.get('run_id') else None
                if run is None:
                    raise NotebookError('Figures require the run that produced them: pass run_id (or its reference_id) '
                                        'and input_ids plus script_id, or just run_id when that run already declares '
                                        'them. Register the run first.')
                # Inherit what the run already declares instead of demanding it twice.
                missing_inputs=not artifact.get('input_ids')
                missing_script=not artifact.get('script_id')
                if missing_inputs and run.get('input_ids'):
                    artifact['input_ids']=list(run['input_ids'])
                if missing_script:
                    script=_resolve_artifact(str(artifact.get('script_id') or ''),known)
                    if script is None:
                        script=next((known[r] for r in run.get('input_ids',[]) if r in known and known[r]['role']=='script'),None)
                    if script is not None: artifact['script_id']=script['id']
                if not artifact.get('input_ids') or not artifact.get('script_id'):
                    raise NotebookError('Figures require input_ids and script_id (or a run that declares them): '
                                        f'run {run["id"]} declares {len(run.get("input_ids",[]))} input(s). '
                                        'Register the script artifact, then register or update the run with its inputs.')
            # Store canonical ids, never the alias the caller happened to pass: accepting an
            # alias at registration but persisting it verbatim produced records that were
            # valid on write and invalid at validate.
            artifact['input_ids']=[_resolve_artifact(ref,known)['id'] if _resolve_artifact(ref,known) else ref
                                   for ref in artifact.get('input_ids',[])]
            if artifact.get('script_id'):
                script=_resolve_artifact(str(artifact['script_id']),known)
                if script is not None: artifact['script_id']=script['id']
            if artifact.get('run_id'):
                run=_resolve_run(str(artifact['run_id']),m['runs'])
                if run is not None: artifact['run_id']=run['id']
            existing=None
            for old in m['artifacts']:
                if old['location']==location and old['role']==artifact['role']:
                    if old['role']=='raw' and old['sha256'] and sha and sha!=old['sha256']: raise NotebookError('Raw evidence changed; original record retained')
                    existing=old
            if existing is not None and (existing['role'] != 'raw' or not existing['sha256'] or existing['sha256'] == sha):
                existing.update(sha256=sha,checksum_origin=origin,size_bytes=size,availability=availability,
                                source_origin=source_origin,remote_host=remote_host,remote_path=remote_path,remote_copy_permission=permission,
                                # omit means keep: a refresh must not silently erase the alias
                                reference_id=reference_id if reference_id is not None else existing.get('reference_id'),
                                description=artifact.get('description',existing['description']),
                                input_ids=artifact.get('input_ids',existing['input_ids']),
                                script_id=artifact.get('script_id',existing['script_id']),
                                run_id=artifact.get('run_id',existing['run_id']),
                                conditions=artifact.get('conditions',existing['conditions']))
                return {'artifact_id':existing['id'],'sha256':sha,'checksum_origin':origin,'availability':availability,'refreshed':True,
                        'source_origin':source_origin,'remote_host':remote_host,'remote_path':remote_path,'remote_copy_permission':permission,
                        'warnings':([] if sha else ['Still no checksum: the file is absent or exceeds the 64 MiB per-operation hash budget'])}
            a=dict(id=uid('artifact'),created_at=now(),role=artifact['role'],source_origin=source_origin,remote_host=remote_host,remote_path=remote_path,remote_copy_permission=permission,reference_id=reference_id,location=location,external=external,description=artifact.get('description',''),input_ids=artifact.get('input_ids',[]),script_id=artifact.get('script_id'),run_id=artifact.get('run_id'),sha256=sha,checksum_origin=origin,size_bytes=size,availability=availability,conditions=artifact.get('conditions',{}))
            m['artifacts'].append(a)
            warnings=[]
            if availability=='missing': warnings.append('Registered file is absent; validate reports it as missing until it exists')
            elif availability=='external_unverified': warnings.append('External reference was not contacted; no checksum and no availability proof')
            elif sha is None: warnings.append('File is larger than the 64 MiB per-operation hash budget; no checksum recorded')
            elif origin=='supplied_unverified': warnings.append('Checksum recorded as supplied and not yet verified')
            if artifact['role'] in ('raw','input') and source_origin=='unspecified' and size and size>LARGE_COPY_BYTES:
                warnings.append('Large raw evidence declared with no source_origin; set remote_copy plus remote_host and remote_path if it exists on another machine')
            if source_origin=='remote_copy' and artifact['role'] not in ('raw','input') and size and size>LIGHT_OUTPUT_BYTES:
                warnings.append('Pulled-back result is '+format(size)+' bytes; keep large derived data on '+str(remote_host)+' and register an external reference instead')
            return {'artifact_id':a['id'],'sha256':sha,'checksum_origin':origin,'availability':availability,'warnings':warnings}
        return self.mutate(eid,request_id,dict(op='artifact',artifact=artifact),change)

    def register_run(self,eid,run,request_id=None):
        allowed={'id','backend','host','external_id','execution_status','command','parameters','environment','input_ids','output_ids','failure','reference_id'}
        if set(run)-allowed: raise NotebookError('Unknown run metadata fields')
        def change(m):
            known=_known_artifacts(m)
            resolved_io={}
            for field in ('input_ids','output_ids'):
                resolved_io[field]=[]
                for ref in run.get(field,[]):
                    target=_resolve_artifact(ref,known)
                    if target is None:
                        raise NotebookError(f'Unknown {field} reference {ref!r}; pass an artifact_id or the reference_id '
                                            f'you registered it with. Known: {_sample_ids(known)}')
                    resolved_io[field].append(target['id'])
            text(run.get('command',''),'command')
            host=run.get('host') or (socket.gethostname() if run['backend'] in ('local','levin') else None)
            if not host: raise NotebookError('backend='+run['backend']+' runs must record host, the machine the computation actually ran on (e.g. hpc-node7)')
            text(host,'host',limit=200)
            if not run.get('environment'): raise NotebookError('Software environment must be recorded')
            if run['execution_status']=='failed':
                if not run.get('failure'): raise NotebookError('Failed runs require failure information')
                _specific(run['failure'],'failure text')
            existing=_resolve_run(run['id'],m['runs']) if run.get('id') else None
            if run.get('id') and existing is None:
                raise NotebookError(f'Unknown run id for update: {run["id"]!r}. To create a run, omit run.id entirely; '
                                    f'to update one, pass the run_id you were given or its reference_id. '
                                    f'Known runs: {_sample_ids({r["id"]:r for r in m["runs"]})}')
            ref_id=run.get('reference_id')
            if ref_id is not None: text(ref_id,'reference_id',limit=60)
            # omit means keep, exactly as for artifacts
            ref_id=ref_id if ref_id is not None else (existing.get('reference_id') if existing else None)
            r=dict(id=existing['id'] if existing else uid('run'),created_at=existing['created_at'] if existing else now(),backend=run['backend'],host=host,reference_id=ref_id,external_id=run.get('external_id',''),execution_status=run['execution_status'],command=run['command'],parameters=run.get('parameters',{}),environment=run['environment'],input_ids=resolved_io['input_ids'],output_ids=resolved_io['output_ids'],failure=run.get('failure',''))
            if existing: m['runs'][m['runs'].index(existing)]=r
            else: m['runs'].append(r)
            return {'run_id':r['id']}
        return self.mutate(eid,request_id,dict(op='run',run=run),change)

    def validate_manifest(self,m,final=False):
        errors=[]; warnings=[]; budget=HASH_BUDGET
        for e in VALIDATOR.iter_errors(m): errors.append(f'{list(e.path)}: {e.message}')
        if errors: return {'valid':False,'errors':errors,'warnings':warnings}
        arts={a['id']:a for a in m['artifacts']}; runs={r['id']:r for r in m['runs']}
        if len(arts)!=len(m['artifacts']) or len(runs)!=len(m['runs']): errors.append('Duplicate evidence identifiers')
        for a in m['artifacts']:
            aid=a['id']
            try: _,_,path=self.location(a['location'])
            except Exception as e: errors.append(f'{aid}: {e}'); continue
            if path is None: warnings.append(f'{aid}: external reference not contacted or verified')
            elif not path.is_file(): errors.append(f'{aid}: missing local file {a["location"]}')
            elif a['sha256']:
                size=path.stat().st_size
                if size<=budget:
                    budget-=size
                    if digest(path)!=a['sha256']: errors.append(f'{aid}: checksum mismatch')
                else: warnings.append(f'{aid}: checksum not reverified (64 MiB total budget)')
            else: warnings.append(f'{aid}: no checksum recorded')
            if path and a['role'] in ('raw','input') and path.is_relative_to(self.scratch): errors.append(f'{aid}: raw/input evidence in scratch')
            if set(a['input_ids'])-arts.keys(): errors.append(f'{aid}: unknown input reference')
            if a['script_id'] and (a['script_id'] not in arts or arts[a['script_id']]['role']!='script'): errors.append(f'{aid}: invalid script reference')
            if a['run_id'] and a['run_id'] not in runs: errors.append(f'{aid}: missing run')
            if a['role']=='figure':
                if not a['input_ids'] or not a['script_id'] or not a['run_id']: errors.append(f'{aid}: incomplete figure provenance')
                if a['run_id'] in runs and runs[a['run_id']]['execution_status']!='success': errors.append(f'{aid}: figure generation run not successful')
        for r in m['runs']:
            if (set(r['input_ids'])|set(r['output_ids']))-arts.keys(): errors.append(f'{r["id"]}: missing run artifact')
            if r['execution_status']=='failed' and not r['failure']: errors.append(f'{r["id"]}: missing failure details')
            if not r['environment'] or not r['command']: errors.append(f'{r["id"]}: incomplete execution provenance')
            if not r.get('host'): warnings.append(f'{r["id"]}: no executing host recorded (register the run again to add it)')
        for c in m['checkpoints']:
            if set(c['evidence_ids'])-(arts.keys()|runs.keys()): errors.append(f'{c["id"]}: dangling evidence')
            if c['kind']=='conclusion' and not c['evidence_ids']: errors.append(f'{c["id"]}: unsupported conclusion')
        if final:
            if m['execution_status']=='wip': errors.append('Stored execution_status is wip; final_readiness evaluates the saved manifest, so this line clears when finalize is called with success or failed')
            if any(r['execution_status']=='wip' for r in m['runs']): errors.append('Unfinished run remains')
            try:
                import units as _units
                for issue in _units.check_all(m.get('quantities') or []):
                    line=f"quantity {issue.get('index','')}: {issue['text']}".replace('quantity :','quantity')
                    (errors if issue['code'] in BLOCKING_UNIT_CODES else warnings).append(line)
            except Exception as error:  # pragma: no cover - defensive
                warnings.append(f'unit check unavailable: {error}')
            if not m['limitations'].strip(): errors.append('Explicit limitations required')
            if not m['interpretation'].strip(): errors.append('Explicit interpretation required (may be inconclusive)')
            if not m['checkpoints']: errors.append('At least one methods, observations or failure checkpoint required')
            if m['execution_status']=='failed' and not any(c['kind']=='failure' for c in m['checkpoints']) and not any(r['failure'] for r in m['runs']): errors.append('Failed experiment requires failure details')
            v=m['visualization']
            if v is None: errors.append('Visualization assessment required')
            else:
                if v['beneficial'] and not v['figure_ids']: errors.append('Visualization justified but no accepted figure registered')
                for a in v['figure_ids']:
                    if a not in arts or arts[a]['role']!='figure': errors.append('Visualization references invalid figure')
        return {'valid':not errors,'errors':errors,'warnings':warnings}

    def validate(self,eid):
        try:
            m=self._load(eid); result=self.validate_manifest(m)
            d=self._dir(eid)
            if not (d/'record.md').is_file(): result['errors'].append('record.md missing')
            elif (d/'record.md').read_text()!=self.markdown(m): result['warnings'].append('record.md differs from generated manifest view; preserve edits in notes.md')
            for report in m['reports']:
                for key in ('source_path','pdf_path'):
                    if report.get(key):
                        p=self.workspace/report[key]
                        if not p.is_file(): result['errors'].append(f'Missing report {key}')
                        elif report.get(key+'_sha256') and digest(p)!=report[key+'_sha256']: result['errors'].append(f'Changed report {key}')
            # Which report is "the" report was previously only answerable by filtering
            # manifest.reports by hand, and blocked attempts (source folder, no PDF) look
            # like results in a directory listing.
            delivered=[r for r in m['reports'] if r.get('render_state')=='success']
            result['reports']={
                'total':len(m['reports']),
                'success':len(delivered),
                'blocked':sum(1 for r in m['reports'] if r.get('render_state')=='blocked'),
                'failed':sum(1 for r in m['reports'] if r.get('render_state')=='failed'),
                'latest_success':max(delivered,key=lambda r:r.get('source_revision',0))['id'] if delivered else None,
                'pending_snapshots':len(m['reports'])-len(delivered),
            }
            if delivered and m['revision']>max(r.get('source_revision',0) for r in delivered):
                result['warnings'].append(f'Delivered report is stale: it snapshots revision {max(r.get("source_revision",0) for r in delivered)} but the manifest is at revision {m["revision"]}; re-finalize with a new request_id')
            # A cross-record artifact reference is allowed, but the hierarchy has to be
            # declared or a reader cannot tell whose data this is.
            declared=set(m.get('derived_from') or [])
            foreign=set()
            for a in m['artifacts']:
                location=str(a.get('location') or '')
                match=re.search(r'levin_notebook/experiments/(exp-[0-9a-f]{32})/', location)
                if match and match.group(1)!=m['experiment_id']:
                    foreign.add(match.group(1))
            for other in sorted(foreign-declared):
                result['warnings'].append(f'references artifacts of {other} without listing it in derived_from')
            for parent in sorted(declared):
                if not (self.root/'experiments'/parent/'manifest.json').is_file():
                    result['warnings'].append(f'derived_from names {parent} but no such record exists in this workspace')
            for a in m['artifacts']:
                if a['external'] and '://' not in a['location']:
                    result['warnings'].append(f'{a["id"]}: path {a["location"]} is outside workspace_dir; this record is not portable to another machine')
            # Glyph coverage belongs in validate: the author can still reword an
            # observation here, whereas after finalize the PDF already has tofu in it.
            try:
                from reporting import check_glyphs
                profile=m.get('font_profile') or 'scientific-cjk'
                body='\n'.join([self.markdown(m)] + [c['text'] for c in m['checkpoints']])
                for finding in check_glyphs(body, profile)[:20]:
                    result['warnings'].append(
                        f"报告字体画不出 {finding['character']} ({finding['codepoint']}, "
                        f"{finding['count']} 处)：…{finding['context']}…；改用 ASCII 等价符号（如 => 或 ->）")
            except Exception:
                pass  # a font probe must never make validation fail
            result['valid']=not result['errors']
            final=self.validate_manifest(copy.deepcopy(m),final=True)
            result['final_readiness']={'valid':final['valid'],'errors':final['errors']}
            return {'ok':True,'experiment_id':eid,**result}
        except Exception as e: return {'ok':True,'experiment_id':eid,'valid':False,'errors':[str(e)],'warnings':[]}

    def finalize(self,eid,execution_status,interpretation,limitations,visualization,request_id=None,lessons=None,plans=None,strategy=None,method_plan=None,materials=None,results=None,footnotes=None,remote_space=None,purpose='',environment_location='',search_strategy=None,references=None,synthesis='',citations=None,extra_sections=None,record_type=None,bibtex=None,bibtex_path=None,reference_sections=None,quantities=None,font_profile=None):
        # None means the caller omitted the field (keep what is stored); an explicit empty
        # list is a real request to clear it. Without this distinction a finalize that only
        # adds artifacts silently wiped lessons/plans/results in a real campaign.
        provided={name:(value is not None) for name,value in
                  (('lessons',lessons),('plans',plans),('strategy',strategy),('method_plan',method_plan),
                   ('materials',materials),('results',results),('footnotes',footnotes),
                   ('remote_space',remote_space),('references',references),('citations',citations),
                   ('extra_sections',extra_sections),('reference_sections',reference_sections),
                   ('quantities',quantities))}
        lessons=() if lessons is None else lessons
        plans=() if plans is None else plans
        strategy=() if strategy is None else strategy
        method_plan=() if method_plan is None else method_plan
        footnotes=() if footnotes is None else footnotes
        remote_space=() if remote_space is None else remote_space
        references=() if references is None else references
        citations=() if citations is None else citations
        extra_sections=() if extra_sections is None else extra_sections
        reference_sections=() if reference_sections is None else reference_sections
        quantities=() if quantities is None else quantities
        text(interpretation,'interpretation'); text(limitations,'limitations')
        for item in list(lessons)+list(plans): text(item,'lessons/plans entry')
        for entry in strategy:
            if not isinstance(entry,dict) or set(entry)-{'title','text'}: raise NotebookError('strategy entries accept only title and text')
            text(entry.get('title',''),'strategy.title',limit=200); text(entry.get('text',''),'strategy.text')
        for item in method_plan: text(item,'method_plan entry')
        notes=[]
        for entry in footnotes:
            if not isinstance(entry,dict) or set(entry)-{'label','text'}: raise NotebookError('footnotes accept only label and text')
            label=text(entry.get('label',''),'footnote.label',limit=40); body=text(entry.get('text',''),'footnote.text')
            notes.append({'label':label,'text':body})
        remote=[]
        for entry in remote_space:
            if not isinstance(entry,dict) or set(entry)-{'host','path','bytes','files','measured_at','note'}: raise NotebookError('remote_space accepts host, path, bytes, files, measured_at, note')
            text(entry.get('host',''),'remote_space.host',limit=200); text(entry.get('path',''),'remote_space.path',limit=4096)
            if not isinstance(entry.get('bytes'),int) or isinstance(entry.get('bytes'),bool) or entry['bytes']<0: raise NotebookError('remote_space.bytes must be a non-negative integer')
            remote.append({k:entry.get(k) for k in ('host','path','bytes','files','measured_at','note') if k in entry})
        for entry in references:
            if not isinstance(entry,dict) or not entry.get('id'):
                raise NotebookError('each reference override needs an id matching a BibTeX citekey')
        for entry in citations:
            if not isinstance(entry,dict) or not entry.get('from') or not entry.get('to'):
                raise NotebookError('each citation edge needs from and to')
        ref_sections=[]
        for entry in reference_sections:
            if not isinstance(entry,dict) or set(entry)-{'title','text'}:
                raise NotebookError('reference_sections accept only title and text')
            title=text(entry.get('title',''),'reference_sections.title',limit=200)
            body=text(entry.get('text',''),'reference_sections.text') if entry.get('text') else ''
            ref_sections.append({'title':title,'text':body})
        for entry in extra_sections:
            if not isinstance(entry,dict) or not entry.get('title') or not entry.get('text'):
                raise NotebookError('each extra section needs title and text')
        parsed_refs, bib_warnings = [], []
        bib_source = bibtex_path or bibtex
        if bib_source:
            from bibtex_index import read_bibtex, merge as merge_refs
            parsed_refs, bib_warnings, resolved = read_bibtex(str(bib_source), self.workspace)
            if bib_warnings: pass
            references = merge_refs(list(references), parsed_refs)
        else:
            resolved = None
        for entry in references:
            if not (entry.get('citation') or entry.get('title')):
                raise NotebookError(f"reference {entry.get('id')!r} has neither citation nor title")
        qty=[]
        for entry in quantities:
            if not isinstance(entry,dict):
                raise NotebookError('each quantity must be an object with name and value')
            allowed={'name','value','unit','dimension','unit_acknowledged','uncertainty',
                     'uncertainty_unit','note','artifact_id','replica'}
            unknown=set(entry)-allowed
            if unknown: raise NotebookError(f"quantity accepts {', '.join(sorted(allowed))}; got {sorted(unknown)}")
            qty.append({k:entry[k] for k in ('name','value','unit','dimension','unit_acknowledged',
                                             'uncertainty','uncertainty_unit','note','artifact_id','replica')
                        if k in entry})
        note_text=str(synthesis) if synthesis else ''
        if note_text: text(note_text,'synthesis')
        if search_strategy is not None and not isinstance(search_strategy,dict): raise NotebookError('search_strategy must be an object')
        payload=dict(op='finalize',execution_status=execution_status,interpretation=interpretation,limitations=limitations,visualization=visualization,lessons=list(lessons),plans=list(plans),strategy=list(strategy),method_plan=list(method_plan),materials=materials or {},results=results or {},footnotes=notes,remote_space=remote,purpose=purpose,environment_location=environment_location,
                     search_strategy=search_strategy or {},references=list(references),synthesis=note_text,
                     bibtex_source=bib_source, bibtex_warnings=bib_warnings,
                     citations=list(citations),extra_sections=list(extra_sections),record_type=record_type,
                     reference_sections=ref_sections,quantities=qty,font_profile=font_profile)
        def change(m):
            # Scalar fields are always replaced (they are required or additive); list- and
            # dict-valued fields only when the caller actually passed them.
            m.update(interpretation=interpretation,limitations=limitations,visualization=visualization)
            if provided['lessons']: m['lessons']=list(lessons)
            if provided['plans']: m['plans']=list(plans)
            if provided['strategy']: m['strategy']=list(strategy)
            if provided['method_plan']: m['method_plan']=list(method_plan)
            if provided['materials']: m['materials']=dict(materials or {})
            if provided['results']: m['results']=dict(results or {})
            if provided['footnotes']: m['footnotes']=notes
            if provided['remote_space']: m['remote_space']=remote
            if purpose: m['purpose']=purpose
            if environment_location: m['environment_location']=environment_location
            if record_type:
                if record_type not in ('experiment','analysis','literature_review'): raise NotebookError('invalid record_type')
                m['record_type']=record_type
            m['search_strategy']=dict(search_strategy or {}) if search_strategy is not None else m.get('search_strategy')
            m['bibtex_source']=bib_source if bib_source else m.get('bibtex_source')
            m['bibtex_warnings']=bib_warnings if bib_warnings else m.get('bibtex_warnings',[])
            if provided['references']: m['references']=list(references)
            if provided['citations']: m['citations']=list(citations)
            if provided['reference_sections']: m['reference_sections']=ref_sections
            if provided['quantities']: m['quantities']=qty
            if font_profile: m['font_profile']=font_profile
            if provided['extra_sections']: m['extra_sections']=list(extra_sections)
            if note_text: m['synthesis']=note_text
            current={'notebook':usage(self.root),'scratch':usage(self.scratch)}
            m['usage_at_finalize']={'captured_at':now(),'notebook':current['notebook'],'scratch':current['scratch'],
                                    'experiment':usage(self._dir(eid)),
                                    'delta_since_init':usage_delta(m.get('usage_at_init'),current) if m.get('usage_at_init') else None}
            candidate=copy.deepcopy(m); candidate['execution_status']=execution_status
            validation=self.validate_manifest(candidate,final=True)
            if validation['valid']: m['execution_status']=execution_status
            report_id=uid('report'); d=self._guard(self._dir(eid)/'reports'/report_id)
            d.mkdir(parents=True,exist_ok=False)
            snapshot_manifest=copy.deepcopy(m)
            snapshot_manifest['revision']+=1
            snapshot_manifest['updated_at']=now()
            verdict = 'valid' if validation['valid'] else 'INVALID'
            snapshot_manifest['execution_status']=m['execution_status']
            source=self.markdown(snapshot_manifest)+'\n## 快照校验\n\n'+f"Schema and provenance validation: {verdict}.\n\n"+"\n".join('- ERROR: '+e for e in validation['errors'])+('\n' if validation['errors'] else '')+"\n".join('- Warning: '+w for w in validation['warnings'])+'\n'
            source_path=d/'report.md'; self._atomic(source_path,source)
            self._atomic(d/'report.qmd','---\nformat:\n  typst:\n    papersize: a4\n    margin: 22mm\nexecute:\n  enabled: false\n---\n\n'+source)
            # A TeX source next to the Markdown: same content, ready for xelatex on a
            # machine that has one. The plugin's own PDF never depends on this file.
            try:
                from latex_export import to_latex
                self._atomic(d/'report.tex', to_latex(source, snapshot_manifest['title']))
            except Exception as error:
                self._atomic(d/'report.tex', f'% LaTeX export failed: {error}\n')
            record={'id':report_id,'created_at':now(),'source_revision':m['revision']+1,'source_path':str(source_path.relative_to(self.workspace)),'source_path_sha256':digest(source_path),'pdf_path':None,'render_state':'blocked','validation':validation,'requested_execution_status':execution_status}
            if validation['valid']:
                try:
                    from reporting import render_report
                    figures=[]
                    for aid in visualization['figure_ids']:
                        a=next(a for a in m['artifacts'] if a['id']==aid)
                        _,_,p=self.location(a['location'])
                        if p and p.suffix.lower() in ('.png','.jpg','.jpeg') and a['sha256'] and p.stat().st_size<=HASH_BUDGET and digest(p)==a['sha256']:
                            figures.append(dict(path=str(p),caption=a['description'],artifact_id=aid))
                    pdf=d/'report.pdf'
                    info=render_report(source,pdf,title=m['title'],figures=figures,
                                       font_profile=font_profile or m.get('font_profile'))
                    record.update(pdf_path=str(pdf.relative_to(self.workspace)),pdf_path_sha256=digest(pdf),render_state='success',renderer=info)
                    # Which faces a report actually used belongs in the record: a
                    # silent fallback is otherwise invisible after the fact.
                    record['fonts']=info.get('fonts')
                except Exception as e: record.update(render_state='failed',error=str(e))
            m['reports'].append(record)
            usage_result=dict(m['usage_at_finalize'])
            usage_result['display']={
                'notebook':human_bytes(usage_result['notebook']['bytes']),
                'scratch':human_bytes(usage_result['scratch']['bytes']),
                'experiment':human_bytes(usage_result['experiment']['bytes']),
                'delta_notebook':human_bytes((usage_result.get('delta_since_init') or {}).get('notebook',{}).get('bytes',0)) if usage_result.get('delta_since_init') else None,
                'delta_scratch':human_bytes((usage_result.get('delta_since_init') or {}).get('scratch',{}).get('bytes',0)) if usage_result.get('delta_since_init') else None,
            }
            return {'finalized':record['render_state']=='success','validation':validation,'report':record,'space_usage':usage_result}
        return self.mutate(eid,request_id,payload,change,memoize=lambda result: bool(result.get('finalized')))

    def prune_reports(self, eid, keep='last-success', dry_run=False):
        """Delete old PDF snapshot folders; never touches revisions or artifacts.

        Guards: the newest successful report is always kept, a folder is removed only
        when the manifest records it, and `dry_run` reports what would go.
        """
        if keep not in ('last-success', 'all-success'):
            raise NotebookError("keep must be 'last-success' or 'all-success'")
        m=self._load(eid)
        reports=list(m.get('reports') or [])
        success=[r for r in reports if r.get('render_state')=='success']
        # Always keep at least one snapshot. Without this guard a record whose every
        # finalize was blocked would be emptied and then fail validation for missing
        # reports — deleting the evidence that the attempts happened.
        if keep=='last-success':
            keep_ids={ (success[-1] if success else (reports[-1] if reports else None))['id'] } if reports else set()
        else:
            keep_ids={r['id'] for r in (success or reports[-1:])}
        removable=[]
        for record in reports:
            name=str(record.get('source_path') or record.get('pdf_path') or '')
            match=re.search(r'reports/(report-[0-9a-f]{32})/', name)
            if not match: continue
            folder=match.group(1)
            if record['id'] in keep_ids: continue
            target=self._dir(eid)/'reports'/folder
            if not target.is_dir(): continue
            removable.append((record['id'], folder, usage(target)['bytes']))
        total=sum(bytes_ for _,_,bytes_ in removable)
        if not dry_run:
            for report_id, folder, _bytes in removable:
                shutil.rmtree(self._dir(eid)/'reports'/folder)
                m['reports']=[r for r in m['reports'] if r['id']!=report_id]
            if removable:
                m['revision']+=1; m['updated_at']=now()
                self._save(m)
        return {'ok':True,'experiment_id':eid,'removed':[f for _,f,_ in removable],
                'removed_count':len(removable),'reclaimable_bytes':total,
                'reclaimable':human_bytes(total),'kept':sorted(keep_ids),'dry_run':dry_run}

    def index(self,query='',limit=100,offset=0,include_summary=False):
        rows=[]; errors=[]
        paths=sorted((self.root/'experiments').glob('exp-*/manifest.json'))
        if len(paths)>10000: raise NotebookError('Index exceeds 10000 experiments; split workspace')
        for p in paths:
            try:
                m=self._load(p.parent.name)
                parts=[m['title'],m['objective'],m['hypothesis'],m['interpretation'],m['limitations'],m['experiment_id'],m['task_id']]
                parts+= [c['text'] for c in m['checkpoints']]
                for a in m['artifacts']: parts+=[a['location'],a['description'],a['id']]
                for r in m['runs']: parts+=[r['command'],r['failure'],r['external_id'],r['id'],json.dumps(r['parameters'],ensure_ascii=False),json.dumps(r['environment'],ensure_ascii=False)]
                haystack=' '.join(parts).lower()[:200000]
                if all(term in haystack for term in query.lower().split()[:8]):
                    row={k:m[k] for k in ('experiment_id','task_id','title','objective','created_at','updated_at','execution_status','revision')}
                    if include_summary:
                        by_role={}
                        for a in m['artifacts']: by_role[a['role']]=by_role.get(a['role'],0)+1
                        row['summary']={
                            'artifacts':len(m['artifacts']),'artifact_roles':by_role,
                            'runs':len(m['runs']),
                            'run_status':{s:sum(1 for r in m['runs'] if r['execution_status']==s)
                                          for s in ('wip','success','failed') if any(r['execution_status']==s for r in m['runs'])},
                            'checkpoints':{k:sum(1 for c in m['checkpoints'] if c['kind']==k)
                                           for k in ('method','observation','failure','conclusion')},
                            'conclusions':sum(1 for c in m['checkpoints'] if c['kind']=='conclusion'),
                            'quantities':len(m.get('quantities') or []),
                            'references':len(m.get('references') or []),
                            'reports':len(m['reports']),
                            'derived_from':list(m.get('derived_from') or []),
                        }
                    rows.append(row)
            except Exception as e: errors.append({'experiment_id':p.parent.name,'error':str(e)[:500]})
        return rows[offset:offset+limit],errors

    @staticmethod
    def _stamp(value):
        """YYYY-MM-DD HH:MM:SS in UTC; None-safe."""
        if not value: return 'not recorded'
        try: return datetime.fromisoformat(value).strftime('%Y-%m-%d %H:%M:%S')
        except Exception: return str(value)[:19]

    @staticmethod
    def _cell(value):
        """Escape a Markdown table cell: pipes and newlines would break the table."""
        return str(value).replace('|','\\|').replace('\n',' ').strip() or 'not recorded'

    @staticmethod
    def _section(lines, kind, heading_title, m, numbered=True):
        items=[c for c in m['checkpoints'] if c['kind']==kind]
        if not items: return
        lines += [f'## {heading_title}','']
        for index, c in enumerate(items,1):
            label=c.get('title') or c['text'].split('.')[0][:80] or kind
            suffix=''
            if c.get('replica'): suffix+=f' replica #{c["replica"]}'
            if c.get('retry'): suffix+=f' retry #{c["retry"]}'
            if c.get('refers_to'): suffix+=f' (see {c["refers_to"]})'
            lines.append(f'### {index}. {label}{suffix}' if numbered else f'### {label}{suffix}')
            if c.get('when_note'): lines += ['', f'> {c["when_note"]}']
            lines += ['', c['text'], '']
            if c['evidence_ids']: lines.append('Evidence: '+', '.join(f'`{e}`' for e in c['evidence_ids']))
            lines.append('')

    # ---------- section builders: each returns the lines of one numbered section ----------
    @staticmethod
    def _sec_strategy(m):
        strategy=m.get('strategy') or []
        if not strategy: return ['未记录策略说明。','']
        out=[]
        for index, entry in enumerate(strategy,1):
            out += [f'### {{s}}.{index}. {entry["title"]}','',entry['text'],'']
        return out

    @staticmethod
    def _sec_methods(m):
        plan=m.get('method_plan') or []
        methods=[c for c in m['checkpoints'] if c['kind']=='method']
        out=[]
        if plan: out += [f'- {step}' for step in plan]+['']
        superseded={c.get('supersedes') for c in methods if c.get('supersedes')}
        for index, c in enumerate(methods,1):
            label=c.get('title') or '方法'
            if c['id'] in superseded:
                later=next((x for x in methods if x.get('supersedes')==c['id']), None)
                label=f"~~{label}~~（已由第 {methods.index(later)+1 if later else '?'} 条方法更正）"
            suffix=''
            if c.get('replica'): suffix+=f" replica #{c['replica']}"
            if c.get('retry'): suffix+=f" retry #{c['retry']}"
            if c.get('refers_to'): suffix+=f"（见 {c['refers_to']}）"
            out.append(f'### {{s}}.{index}. {label}{suffix}')
            if c.get('when_note'): out += ['',f'> {c["when_note"]}']
            out += ['',c['text'],'']
        if not out: out=[f'- {step}' for step in plan] or ['未记录方法。','']
        return out

    @staticmethod
    def _sec_materials(m):
        hosts, platforms = [], set()
        for r in m['runs']:
            host=r.get('host') or '未记录'
            if host not in hosts: hosts.append(host)
            platform=(r['environment'] or {}).get('platform')
            if platform: platforms.add(str(platform))
        out=['| 类别 | 内容 |','| --- | --- |']
        host_text=', '.join(h+(' / '+', '.join(sorted(platforms)) if platforms else '') for h in hosts) or '未记录'
        out.append(f"| 执行主机 / 架构 | {Notebook._cell(host_text)} |")
        datasets=[a for a in m['artifacts'] if a['role'] in ('raw','input','derived','table')]
        out.append(f"| 数据集 | {Notebook._cell(', '.join('`'+a['location']+'`（'+a['role']+'）' for a in datasets) or '未记录')} |")
        scripts=[a for a in m['artifacts'] if a['role']=='script']
        out.append(f"| 脚本 | {Notebook._cell(', '.join('`'+a['location']+'`' for a in scripts) or '未记录')} |")
        software=list((m.get('materials') or {}).get('software') or [])
        for r in m['runs']:
            for name, version in (r['environment'] or {}).items():
                if name=='platform': continue
                entry=f'{name} {version}'
                if entry not in software: software.append(entry)
        out.append(f"| 软件与版本 | {Notebook._cell(', '.join(software) or '未记录')} |")
        params=[f"`{json.dumps(r['parameters'], ensure_ascii=False)}`" for r in m['runs'] if r['parameters']]
        out.append(f"| 非默认参数 | {Notebook._cell(', '.join(params) or '未记录（默认参数未列出）')} |")
        out.append(f"| 环境位置 | {Notebook._cell('`'+m['environment_location']+'`' if m.get('environment_location') else '未记录')} |")
        extra=(m.get('materials') or {}).get('notes')
        if extra: out.append(f"| 其他 | {Notebook._cell(extra)} |")
        out.append('')
        for entry in ((m.get('materials') or {}).get('datasets') or []): out.append(f'- {entry}')
        return out

    @staticmethod
    def _units_body(m):
        """Dimensional table plus explicit issue lines; never converts or rewrites a value."""
        import units as U
        quantities = m.get('quantities') or []
        if not quantities:
            return ['未登记带单位的数值；本记录因此无法做量纲核对。', '']
        issues = U.check_all(quantities)
        blocking = [i for i in issues if i['code'] in BLOCKING_UNIT_CODES]
        rows = U.summary(quantities)
        out = ['| 量 | 数值 | 记录单位 | 规范单位 | 量纲 | 状态 |',
               '| --- | --- | --- | --- | --- | --- |']
        for row in rows:
            value = row['value']
            value_text = f'{value:g}' if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
            status = '**需修正**' if row['status'] == '需修正' else '通过'
            out.append('| ' + ' | '.join(Notebook._cell(str(v)) for v in (
                row['name'], value_text, row['unit'], row['canonical'], row['dimension'], status)) + ' |')
        out.append('')
        flagged = [(row['name'], text) for row in rows for text in row['issues']]
        out += [f'- `{name}`：{text}' for name, text in flagged] or ['- 全部量的量纲与记录惯例一致。']
        out += ['',
                '核对方式：按量名所属物理族比较量纲指数，并把换算因子与库内惯例比对；'
                '本插件只报告差异，**不做任何静默换算或改值**。', '']
        if blocking:
            out += [f"其中 {len(blocking)} 项为量纲不符或单位缺失，不能据此作定量陈述。", '']
        return out

    @staticmethod
    def _sec_results(m):
        res=m.get('results') or {}
        out=['### {s}.1. 看到了什么','']
        for item in res.get('expected_seen') or []: out.append(f'- 预期结果：{item}')
        for item in res.get('unexpected_seen') or []: out.append(f'- 意外的结果：{item}')
        observations=[c for c in m['checkpoints'] if c['kind']=='observation']
        superseded={c.get('supersedes') for c in observations if c.get('supersedes')}
        for c in observations:
            label=c.get('title') or '观测'
            if c['id'] in superseded:
                # A corrected observation stays visible, marked as replaced, so the
                # record shows what was believed before. Observation bullets are not
                # numbered, so point at the correcting entry by its own label.
                later=next((o for o in observations if o.get('supersedes')==c['id']), None)
                later_label=(later.get('title') or '').strip() if later else ''
                where=(f'「{later_label}」' if later_label and later_label!=label else '后续观测')
                out.append(f"- ~~{label}~~（已由{where}更正）：{c['text']}")
            else:
                out.append(f"- {label}：{c['text']}")
        if not (res.get('expected_seen') or res.get('unexpected_seen') or any(c['kind']=='observation' for c in m['checkpoints'])):
            out.append('- 未记录观测结果。')
        out += ['','### {s}.2. 没看到什么','']
        missing=res.get('expected_not_seen') or []
        out += [f'- 预期结果：{item}' for item in missing] or ['- 未记录缺失的预期结果。']
        out += ['','### {s}.3. 实验过程中的意外和处置','']
        failures=[f"{c.get('title') or '失败'}：{c['text']}" for c in m['checkpoints'] if c['kind']=='failure']
        incidents=list(res.get('incidents') or [])
        blob=' '.join(failures)
        incidents=[item for item in incidents if item not in blob and item[:12] not in blob]
        out += [f'- {item}' for item in incidents+failures] or ['- 无记录的意外。']
        out += ['','### {s}.4. 量纲与单位核对','']
        out += Notebook._units_body(m)
        out += ['\\figures','']
        return out

    @staticmethod
    def _sec_questions(m):
        strategy=m.get('search_strategy') or {}
        out=[m.get('purpose') or '未记录研究问题。','']
        if strategy.get('query'): out += [f"检索问题式：`{strategy['query']}`",'']
        scope=[]
        for label, key in (('数据库','databases'),('时间窗','window'),('语种','languages'),('纳排与筛选','screening')):
            if strategy.get(key): scope.append(f'- {label}：{strategy[key]}')
        if scope: out += ['**范围与筛选**','']+scope+['']
        return out

    @staticmethod
    @staticmethod
    def _ref_entry(r):
        """One bibliography line: authors, year, venue, title, DOI."""
        authors=[a for a in (r.get('authors') or []) if a]
        def surname(name):
            return name.split()[-1] if name.split() else name
        if not authors:
            who='作者未记录'
        elif len(authors)==1:
            who=authors[0]
        elif len(authors)==2:
            who=f"{authors[0]}, {authors[1]}"
        else:
            who=f"{surname(authors[0])} et al, {authors[-1]}"
        return ', '.join([
            who,
            str(r.get('year') or '年份未记录'),
            (r.get('venue') or '期刊未记录').rstrip('.'),
            (r.get('title') or r.get('citation') or '标题未记录').rstrip('.'),
            (f"doi:{r['doi']}" if r.get('doi') else 'DOI 未记录'),
        ])

    @staticmethod
    def _sec_references(m):
        refs=m.get('references') or []
        if not refs: return ['未登记文献。','']
        sections=[s for s in (m.get('reference_sections') or []) if s.get('title')]
        grouped={}
        order=[]
        for section in sections:
            order.append(section['title']); grouped[section['title']]=[]
        for r in refs:
            key=r.get('section') or ''
            if key in grouped:
                grouped[key].append(r)
            elif key and sections:
                raise NotebookError(f"reference {r.get('id')!r} names section {key!r} that reference_sections does not declare")
            else:
                grouped.setdefault('',[]).append(r)
                if '' not in order: order.append('')
        out=[]
        counter=0
        for title in order:
            members=grouped.get(title) or []
            if not members: continue
            intro=next((s.get('text') for s in sections if s.get('title')==title), '')
            if title:
                out += [f"**{title}**",'']
            if intro:
                out += [intro,'']
            for r in members:
                counter+=1
                # A blank line keeps each entry its own paragraph; consecutive lines would merge.
                out += [f"[{counter}]. {Notebook._ref_entry(r)}",'']
            out.append('')
        linked={}
        for a in m['artifacts']:
            if a.get('reference_id'): linked.setdefault(a['reference_id'],[]).append(a)
        flagged=[r for r in refs if r.get('metadata_issues')]
        if flagged:
            out += [f"需人工核对的元数据（{len(flagged)} 条）："
                    +'；'.join(f"[{next((i for i,x in enumerate(refs,1) if x['id']==r['id']),'?')}] `{r['id']}` "
                               +'、'.join(r['metadata_issues']) for r in flagged), '']
        traced=[r for r in refs if r.get('evidence_level') or r.get('relevance') or r.get('read_full_text') is not None or r['id'] in linked]
        if traced:
            out += ['| 文献 | 证据等级 | 相关性 | 已读全文 | 关联工件 |','| --- | --- | --- | --- | --- |']
            for r in traced:
                arts=', '.join(f"`{a['id']}`" for a in linked.get(r['id'],[])) or '—'
                read='是' if r.get('read_full_text') else ('否' if r.get('read_full_text') is False else '—')
                out.append('| '+' | '.join(Notebook._cell(v) for v in (
                    f"`{r['id']}`", r.get('evidence_level') or '—', r.get('relevance') or '—', read, arts))+' |')
            out.append('')
        sourced=[r for r in refs if r.get('source')]
        if sourced:
            out += [f"文献来源：`{sourced[0]['source']}`（bibtexparser 解析 {len(sourced)} 条）。",'']
        return out

    def _sec_synthesis(m):
        out=[m.get('synthesis') or '未记录证据综合。','']
        observations=[c for c in m['checkpoints'] if c['kind']=='observation']
        for index, c in enumerate(observations,1):
            out += [f'### {{s}}.{index}. {c.get("title") or "观察"}','',c['text'],'']
        return out

    @staticmethod
    def _sec_verification(m):
        runs=[r for r in m['runs'] if r.get('reference_id')] or m['runs']
        if not runs: return ['未做复算或核验。','']
        out=[]
        for r in runs:
            target=f"（对应文献 `{r['reference_id']}`）" if r.get('reference_id') else ''
            out += [f"- `{r['id']}`{target}：{r['backend']} @ `{r.get('host') or '未记录'}`，状态 {r['execution_status']}",
                    '', '```', f"command     {r['command']}",
                    f"parameters  {json.dumps(r['parameters'], ensure_ascii=False)}",
                    f"environment {json.dumps(r['environment'], ensure_ascii=False)}", '```', '']
        derived=[a for a in m['artifacts'] if a['role'] in ('derived','table','figure')]
        if derived:
            out += ['复算与核验产出：','']+[f"- `{a['id']}`（{a['role']}）：`{a['location']}`" for a in derived]+['']
        return out

    @staticmethod
    def _sec_citations(m):
        edges=m.get('citations') or []
        if not edges: return []
        out=['| 起点 | 终点 | 关系 |','| --- | --- | --- |']
        for edge in edges:
            out.append(f"| `{Notebook._cell(edge['from'])}` | `{Notebook._cell(edge['to'])}` | {Notebook._cell(edge.get('relation') or '引用')} |")
        out += ['','引用关系图（Mermaid 源码，可在支持 Mermaid 的渲染器中查看）：','','```mermaid',
                'graph LR']
        for edge in edges:
            relation=edge.get('relation') or 'cites'
            out.append(f"  {edge['from']}[\"{edge['from']}\"] -->|{relation}| {edge['to']}[\"{edge['to']}\"]")
        out += ['```','']
        return out

    @staticmethod
    def _sec_conclusions(m):
        conclusions=[c for c in m['checkpoints'] if c['kind']=='conclusion']
        superseded={c.get('supersedes') for c in conclusions if c.get('supersedes')}
        out=[]
        for index, c in enumerate(conclusions,1):
            label=c.get('title') or '结论'
            if c['id'] in superseded:
                later=next((ch for ch in conclusions if ch.get('supersedes')==c['id']),None)
                label=f"~~{label}~~（已被第 {conclusions.index(later)+1 if later else '?'} 条结论取代）"
            out += [f'### {{s}}.{index}. {label}','',c['text'],'']
            if c['evidence_ids']: out += ['','证据：'+', '.join('`'+e+'`' for e in c['evidence_ids']),'']
        if not out: out += ['未记录结论。','']
        out += ['**结论解读**：'+(m['interpretation'] or '未填写。'),'',
                '**不足**：'+(m['limitations'] or '未填写。'),'']
        return out

    @staticmethod
    def _sec_bullets(items, empty):
        out=[f'- {item}' for item in items or []] or [empty]
        out.append('')
        return out

    @staticmethod
    def _sec_space(m):
        out=['| 位置 | 占用 | 文件数 |','| --- | --- | --- |']
        u=m.get('usage_at_finalize')
        if u:
            out += [f"| `levin_notebook`（本地） | {human_bytes(u['notebook']['bytes'])} | {u['notebook']['files']} |",
                    f"| `levin_scratch`（本地） | {human_bytes(u['scratch']['bytes'])} | {u['scratch']['files']} |",
                    f"| 本记录目录 | {human_bytes(u['experiment']['bytes'])} | {u['experiment']['files']} |"]
            d=u.get('delta_since_init')
            if d: out.append(f"| 相对立项时增量 | `{human_bytes(d['notebook']['bytes'])}` / `{human_bytes(d['scratch']['bytes'])}` | — |")
            out += ['',f"统计时间：{Notebook._stamp(u['captured_at'])}。scratch 不会自动删除，见保留策略。",'']
        else:
            out += ['| 未统计 | — | — |','']
        remote=m.get('remote_space') or []
        if remote:
            out += ['**远程主机占用**（由执行代理用 `du` 实测后上报，插件本身不连接远程）','',
                    '| 主机 | 路径 | 占用 | 文件数 | 标记 |','| --- | --- | --- | --- | --- |']
            for entry in remote:
                flag='**巨额占用**' if entry['bytes']>=1024**3 else ''
                out.append(f"| `{Notebook._cell(entry['host'])}` | `{Notebook._cell(entry['path'])}` | {human_bytes(entry['bytes'])} | {entry.get('files') if entry.get('files') is not None else '—'} | {flag} |")
            out.append('')
        return out

    @staticmethod
    def _sec_notes(m):
        """Recovery and side notes. Kept out of the numbered method list on purpose:
        a resume is not a method, and a note is not a result."""
        entries=[c for c in m['checkpoints'] if c['kind'] in ('resume','note')]
        if not entries: return []
        out=['']
        for c in entries:
            label=c.get('title') or ('续做记录' if c['kind']=='resume' else '备注')
            marker='**续做**' if c['kind']=='resume' else '**备注**'
            out += [f'- {marker}｜{label}：{c["text"]}']
            if c.get('when_note'): out += [f'  > {c["when_note"]}']
            if c['evidence_ids']: out += ['  证据：'+', '.join('`'+e+'`' for e in c['evidence_ids'])]
        out.append('')
        return out

    @staticmethod
    def _sec_extra(m):
        out=[]
        for index, entry in enumerate(m.get('extra_sections') or [],1):
            out += [f'### {{s}}.{index}. {entry["title"]}','',entry['text'],'']
        return out

    @staticmethod
    def _template(m):
        """Ordered section list: (title, builder). The spine is shared; the middle depends on record_type."""
        kind=m.get('record_type') or 'experiment'
        has_refs=bool(m.get('references'))
        evidence=('文献依据', Notebook._sec_references) if has_refs else None
        citations=('引用关系', Notebook._sec_citations)
        if kind=='literature_review':
            middle=[('研究问题与范围', Notebook._sec_questions),
                    ('检索策略', lambda x: Notebook._sec_bullets(
                        [f"{label}：{(x.get('search_strategy') or {}).get(key)}"
                         for key, label in (('databases','数据库'),('query','检索式'),('window','时间窗'),
                                            ('languages','语种'),('screening','去重与筛选'))
                         if (x.get('search_strategy') or {}).get(key)], '未记录检索策略。')),
                    ('文献清单', Notebook._sec_references),
                    ('证据综合', Notebook._sec_synthesis),
                    ('复算与核验', Notebook._sec_verification),
                    citations]
        elif kind=='analysis':
            middle=[('实验目的与依据', lambda x: Notebook._sec_questions(x)),
                    ('分析策略', Notebook._sec_strategy),
                    ('方法与流程', Notebook._sec_methods),
                    ('数据与工具', Notebook._sec_materials)]
            if evidence: middle.append(evidence)
            middle += [('分析结果', Notebook._sec_results),
                       ('证据综合', Notebook._sec_synthesis)]
        else:
            middle=[('实验目的', lambda x: Notebook._sec_questions(x)),
                    ('实验策略', Notebook._sec_strategy),
                    ('实验方法和计划', Notebook._sec_methods),
                    ('实验材料', Notebook._sec_materials),
                    ('实验结果', Notebook._sec_results)]
            if evidence: middle.append(evidence)
        extra=('补充说明', Notebook._sec_extra) if (m.get('extra_sections') or []) else None
        tail=[('实验结论和不足' if kind=='experiment' else '结论与不足', Notebook._sec_conclusions),
              ('下一步计划', lambda x: Notebook._sec_bullets(x.get('plans'), '暂无后续计划。')),
              ('经验教训', lambda x: Notebook._sec_bullets(x.get('lessons'), '未记录。')),
              ('数据空间统计', Notebook._sec_space)]
        if any(c['kind'] in ('resume','note') for c in m['checkpoints']):
            tail.append(('恢复与备注', Notebook._sec_notes))
        ordered=middle+([extra] if extra else [])+tail
        return ordered

    @staticmethod
    def markdown(m):
        title=m['title'].replace('\n',' ')
        notes=m.get('footnotes') or []
        stamp=f"***{Notebook._stamp(m['created_at'])} — {Notebook._stamp(m['updated_at'])}***"
        lines=[f'# {title}','',stamp,'']
        lines += [f"**本项目在做什么**：{m['objective']}",'',
                  f"**为什么要做**：{m.get('purpose') or m['hypothesis'] or '未记录立项背景。'}",'',
                  f"**预期结果**：{m.get('expected_result') or '立项时未写明预期结果。'}",'']
        hosts, backends = [], []
        for r in m['runs']:
            host=r.get('host') or '未记录'
            if host not in hosts: hosts.append(host)
            if r['backend'] not in backends: backends.append(r['backend'])
        impl=m.get('implementer') or {}
        who={'user':'用户','agent':'Agent'}.get(impl.get('kind'),'未记录')
        detail=', '.join(x for x in (impl.get('name'), ('模型 '+impl['model']) if impl.get('model') else '') if x)
        if detail: who+=f'（{detail}）'
        outcome={'success':'成功','failed':'失败','wip':'进行中'}.get(m['execution_status'],m['execution_status'])
        kind_label={'experiment':'实验','analysis':'分析','literature_review':'文献调研'}.get(m.get('record_type') or 'experiment')
        lines += ['| 项目 | 内容 |','| --- | --- |',
                  f"| 记录类型 | {kind_label} |",
                  f"| 开始 / 结束 | {Notebook._cell(Notebook._stamp(m['created_at']))} — {Notebook._cell(Notebook._stamp(m['updated_at']))} |",
                  f"| 实施人 | {Notebook._cell(who)} |",
                  f"| 执行主机 | {Notebook._cell(', '.join(hosts))} |",
                  f"| 工作路径 | {Notebook._cell('`'+(m.get('workspace_dir') or '未记录')+'`')} |",
                  f"| 环境 / 调度框架 | {Notebook._cell(', '.join(backends) or '未记录')} |",
                  f"| 环境位置 | {Notebook._cell('`'+m['environment_location']+'`' if m.get('environment_location') else '未记录（未使用 uv/conda 或未登记）')} |",
                  f"| 最终结果 | **{Notebook._cell(outcome)}** |",'']
        number=0
        for heading, builder in Notebook._template(m):
            block=builder(m)
            if not block: continue
            number+=1
            lines.append(f'## {number}. {heading}')
            lines.append('')
            for entry in block:
                lines.append(entry.replace('{s}', str(number)) if isinstance(entry,str) else entry)
            if lines[-1] != '': lines.append('')
        if notes:
            lines += ['## 尾注','']
            for note in notes: lines.append(f"[^{note['label']}]: {note['text']}")
            lines.append('')
        # Long machine strings (paths, digests) are printed one per line rather than in
        # a grid cell: a 64-character digest inside a column becomes unreadable
        # fragments, and the value must stay copyable.
        lines += ['\\pagebreak','','## 工件与溯源','','机器可读证据。路径与摘要为精确值；外部引用从未被访问。','',
                  '| ID | 角色 | 可用性 | 来源 |','| --- | --- | --- | --- |']
        for a in m['artifacts']:
            note=a.get('source_origin','unspecified')+(' @ '+a['remote_host'] if a.get('remote_host') else '')
            if a.get('reference_id'): note+=f" / 文献 {a['reference_id']}"
            lines.append(f"| `{a['id']}` | {a['role']} | {Notebook._cell(a['availability'])} | {Notebook._cell(note)} |")
        if not m['artifacts']: lines.append('| — | — | 未登记工件 | — | — |')
        if m['artifacts']:
            lines += ['','### 位置与校验和','']
            for a in m['artifacts']:
                lines += [f"**`{a['id']}`**（{a['role']}）",'',
                          '```',f"location  {a['location']}",
                          f"sha256    {a['sha256'] or '未计算（外部引用或超出哈希预算）'}",
                          '```','']
                if a.get('remote_host'):
                    lines.append(f"- 远程来源：主机 `{a['remote_host']}`，原始路径 `{a['remote_path']}`")
                    if a.get('remote_copy_permission'): lines.append(f"- 拷贝授权：{a['remote_copy_permission']}")
                if a.get('input_ids'): lines += [f"- 输入：{', '.join('`'+i+'`' for i in a['input_ids'])}"]
                if a.get('script_id'): lines += [f"- 脚本：`{a['script_id']}`"]
                if a.get('run_id'): lines += [f"- 运行：`{a['run_id']}`"]
                if lines[-1]!='': lines.append('')
            lines.append('')
        remote_art=[a for a in m['artifacts'] if a.get('remote_host')]
        if remote_art:
            lines += ['','**远程来源**','']
            for a in remote_art:
                note=f"- `{a['id']}` — 来源 `{a.get('source_origin','unspecified')}`，主机 `{a['remote_host']}`，原始路径 `{a['remote_path']}`"
                if a.get('remote_copy_permission'): note+=f"；拷贝授权：{a['remote_copy_permission']}"
                lines.append(note)
        lines += ['','### 执行溯源','','| Run | 后端 | 主机 | 状态 | 外部 ID |','| --- | --- | --- | --- | --- |']
        for r in m['runs']:
            lines.append(f"| `{r['id']}` | {r['backend']} | `{Notebook._cell(r.get('host') or '未记录')}` | {r['execution_status']} | {Notebook._cell(r['external_id'] or '—')} |")
        if not m['runs']: lines.append('| — | — | — | 未登记运行 | — |')
        for r in m['runs']:
            lines += ['',f"**Run** `{r['id']}`",'','```']
            lines.append(f"command     {r['command']}")
            lines.append(f"parameters  {json.dumps(r['parameters'], ensure_ascii=False)}")
            lines.append(f"environment {json.dumps(r['environment'], ensure_ascii=False)}")
            if r['input_ids']: lines.append("inputs      "+', '.join(r['input_ids']))
            if r['output_ids']: lines.append("outputs     "+', '.join(r['output_ids']))
            if r['execution_status']=='failed': lines.append("failure     "+r['failure'])
            lines += ['```']
        lines += ['','## 保存与复现','',f"保留策略：{m['retention']}",'',
                  '清单与溯源通过校验不等于科学可复现。校验和仅在实测通过时证明同一性。',
                  '人工笔记：`notes.md`；历史清单：`revisions/`；报告：`reports/`。','']
        return '\n'.join(lines)
