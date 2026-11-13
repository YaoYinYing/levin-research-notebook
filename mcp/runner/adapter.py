"""Thin Levin adapter; filesystem implementation also runs without MCP."""
from __future__ import annotations
import importlib.metadata
from levin_plugin_sdk import PluginError


def preflight(context, arguments):
    checks=[]
    for package in ('jsonschema','filelock','reportlab','matplotlib'):
        try: checks.append({'name':package,'ready':True,'version':importlib.metadata.version(package)})
        except importlib.metadata.PackageNotFoundError: checks.append({'name':package,'ready':False})
    ready=all(c['ready'] for c in checks)
    # Font availability has to be visible before a report is rendered: a host with no
    # CJK face produces [U+XXXX] boxes, and that is not something to discover from the PDF.
    fonts=None
    try:
        from reporting import font_report
        fonts=font_report('scientific-cjk')
    except Exception as error:
        fonts={'error':str(error)}
    return {'ready':ready,'runtime_ready':ready,'model_ready':True,'source_ready':True,'checks':checks,'execution_location':context.execution_location,'integration':'skill checkpoints; no automatic lifecycle hook','renderer':'reportlab','fonts':fonts,'remote_policy':'references only; notebook writes use selected filesystem'}


def invoke(operation, arguments):
    a=dict(arguments)
    preview=a.pop('preview',False)
    workspace=a.pop('workspace_dir')
    if preview:
        return {'ok':True,'preview':True,'operation':operation,'note':'Schema-valid plan only; no record read, created or finalized. Domain execution is separately tested.'}
    try:
        from notebook import Notebook, NotebookError
        n=Notebook(workspace)
        if operation=='init': return n.init(**a)
        if operation=='checkpoint':
            a['eid']=a.pop('experiment_id'); a['body']=a.pop('text')
            return n.checkpoint(**a)
        if operation=='register_artifact':
            return n.register_artifact(a['experiment_id'],a['artifact'],a.get('request_id'))
        if operation=='register_run': return n.register_run(a['experiment_id'],a['run'],a.get('request_id'))
        if operation=='validate': return n.validate(a['experiment_id'])
        if operation=='finalize':
            a['eid']=a.pop('experiment_id'); return n.finalize(**a)
        if operation=='prune_reports':
            return n.prune_reports(a['experiment_id'], a.get('keep','last-success'), a.get('dry_run',False))
        if operation=='prune_revisions':
            return n.prune_revisions(a['experiment_id'], a.get('keep',20), a.get('dry_run',False))
        if operation=='index':
            rows,errors=n.index(**a); return {'ok':True,'experiments':rows,'errors':errors,'count':len(rows)}
        raise NotebookError('Unknown operation')
    except PluginError:
        raise
    except Exception as e:
        raise PluginError(str(e),code='notebook_validation_error',stage=operation) from e


def research_record_init(context,arguments): return invoke('init',arguments)
def research_record_checkpoint(context,arguments): return invoke('checkpoint',arguments)
def research_record_register_artifact(context,arguments): return invoke('register_artifact',arguments)
def research_record_register_run(context,arguments): return invoke('register_run',arguments)
def research_record_validate(context,arguments): return invoke('validate',arguments)
def research_record_finalize(context,arguments): return invoke('finalize',arguments)
def research_record_index(context,arguments): return invoke('index',arguments)
def research_record_prune_reports(context,arguments): return invoke('prune_reports',arguments)
def research_record_prune_revisions(context,arguments): return invoke('prune_revisions',arguments)
