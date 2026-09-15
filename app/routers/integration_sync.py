"""Queue controls and scoped review/freshness information."""
import json
import time
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from ..database import db_dependency
from ..integration_sync import discover,enabled
from .extras import set_setting

router=APIRouter(prefix='/api/integration-sync',tags=['Integration sync'])

def admin(c):
    if 'admin' not in c.user['roles']:raise HTTPException(403,'Only administrators can manage integration synchronization')

def rows(c,cid=None):
    query='SELECT j.*,c.name AS clinic_name FROM integration_jobs j JOIN clinics c ON c.id=j.clinic_id'
    result=[]
    for r in c.execute(query+(' WHERE j.clinic_id=?' if cid else '')+' ORDER BY j.provider,j.next_at', (cid,) if cid else ()):
        d=dict(r);d.pop('lease');cfg=json.loads(d.pop('config'))
        d['site_name']=cfg.get('name') or 'Main Site'
        d['running']=r['lease_until']>time.time()
        d['pending']=c.execute("SELECT COUNT(*) FROM integration_changes WHERE job_id=? AND status='pending'",(r['id'],)).fetchone()[0]
        d['overrides']=c.execute('SELECT COUNT(*) FROM integration_fields WHERE job_id=? AND overridden=1',(r['id'],)).fetchone()[0]
        d['warnings']=json.loads(d['warnings']);result.append(d)
    return result

@router.get('/settings')
def settings(c=Depends(db_dependency)):
    admin(c)
    return {'enabled':enabled(c),'jobs':rows(c)}

class Settings(BaseModel): enabled:bool

@router.put('/settings')
def configure(p:Settings,c=Depends(db_dependency)):
    admin(c);previous=enabled(c);discover(c)
    set_setting(c,'integration_sync_enabled','1' if p.enabled else '0')
    if p.enabled and not previous:
        jobs=list(c.execute('SELECT id,interval_minutes FROM integration_jobs WHERE enabled=1 ORDER BY provider,id'))
        for index,r in enumerate(jobs):c.execute('UPDATE integration_jobs SET next_at=? WHERE id=?',(time.time()+index*r['interval_minutes']*60/max(1,len(jobs)),r['id']))
    return settings(c)

@router.post('/discover')
def discover_jobs(c=Depends(db_dependency)):
    admin(c);discover(c);return settings(c)

class JobSettings(BaseModel):
    enabled:bool
    interval_minutes:int=Field(default=30,ge=15,le=1440)

@router.put('/jobs/{jid}')
def job_settings(jid:int,p:JobSettings,c=Depends(db_dependency)):
    admin(c)
    if not c.execute('SELECT id FROM integration_jobs WHERE id=?',(jid,)).fetchone():raise HTTPException(404,'Sync job not found')
    c.execute('UPDATE integration_jobs SET enabled=?,interval_minutes=? WHERE id=?',(p.enabled,p.interval_minutes,jid))
    return {'saved':True}

@router.post('/jobs/{jid}/now')
def now(jid:int,c=Depends(db_dependency)):
    admin(c)
    if not enabled(c):raise HTTPException(409,'Enable background synchronization first; Sync now uses the shared queue')
    job=c.execute('SELECT * FROM integration_jobs WHERE id=?',(jid,)).fetchone()
    if not job:raise HTTPException(404,'Sync job not found')
    if not job['enabled']:raise HTTPException(409,'Resume this site first')
    if not job['lease_until']>time.time():c.execute('UPDATE integration_jobs SET next_at=? WHERE id=?',(time.time(),jid))
    return {'queued':True}

@router.get('/clinics/{cid}')
def clinic(cid:int,c=Depends(db_dependency)):
    if not c.execute('SELECT id FROM clinics WHERE id=?',(cid,)).fetchone():raise HTTPException(404,'Clinic not found')
    return {'enabled':enabled(c),'jobs':rows(c,cid),'changes':[dict(r)|{'detail':json.loads(r['detail'])} for r in c.execute("SELECT * FROM integration_changes WHERE clinic_id=? AND status='pending' ORDER BY updated_at DESC LIMIT 200",(cid,))]}

@router.post('/changes/{change_id}/acknowledge')
def acknowledge(change_id:int,c=Depends(db_dependency)):
    admin(c)
    if not c.execute('SELECT id FROM integration_changes WHERE id=?',(change_id,)).fetchone():raise HTTPException(404,'Change not found')
    c.execute("UPDATE integration_changes SET status='reviewed' WHERE id=?",(change_id,))
    return {'reviewed':True}
