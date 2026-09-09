"""Read-only IT overview, using the same scoped connection as technical records."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from ..database import db_dependency, rows_to_list

router = APIRouter(prefix='/api/it', tags=['IT dashboard'])


def appointment_day(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().date()
    except (ValueError, TypeError, AttributeError):
        return None


@router.get('/dashboard')
def dashboard(include_prospects: bool = False, conn=Depends(db_dependency)):
    today = date.today()
    end = today + timedelta(days=7)
    clinics = rows_to_list(conn.execute('''SELECT c.id,c.name,c.shorthand,c.relationship,
        (SELECT COUNT(*) FROM clinic_locations l WHERE l.clinic_id=c.id)+1 AS site_count,
        (SELECT COUNT(*) FROM devices d WHERE d.clinic_id=c.id) AS device_count,
        (SELECT COUNT(*) FROM devices d WHERE d.clinic_id=c.id AND d.device_type IN ('server','vm')) AS server_count,
        (SELECT COUNT(*) FROM device_services s JOIN devices d ON d.id=s.device_id WHERE d.clinic_id=c.id) AS service_count
        FROM clinics c WHERE (? OR c.relationship='current_client') ORDER BY c.name COLLATE NOCASE''', (include_prospects,)))
    selected = {c['id']: c for c in clinics}
    tasks = rows_to_list(conn.execute('''SELECT t.id,t.title,t.due_date,t.priority,t.clinic_id,c.name AS clinic_name
        FROM tasks t LEFT JOIN clinics c ON c.id=t.clinic_id WHERE t.done=0
        ORDER BY t.due_date IS NULL,t.due_date,CASE t.priority WHEN 'high' THEN 0 ELSE 1 END,t.id'''))
    tasks = [t for t in tasks if t['clinic_id'] is None or t['clinic_id'] in selected]
    overdue = [t for t in tasks if t['due_date'] and t['due_date'] < today.isoformat()]
    attention = [dict(kind='task', title=t['title'], clinic_id=t['clinic_id'], clinic_name=t['clinic_name'],
                      detail='Task overdue · ' + t['due_date'], task_id=t['id']) for t in overdue]
    vpns = rows_to_list(conn.execute("SELECT id,name,a_clinic_id,b_clinic_id FROM vpn_links WHERE status='down' ORDER BY id"))
    for v in vpns:
        cid = next((cid for cid in (v['a_clinic_id'],v['b_clinic_id']) if cid in selected), None)
        if cid is not None:
            attention.append(dict(kind='vpn',title=v['name'] or 'VPN link',clinic_id=cid,clinic_name=selected[cid]['name'],
                                  detail='Manually marked down · verify with monitoring',vpn_id=v['id']))
    for c in clinics:
        if c['relationship']=='current_client' and not c['device_count']:
            attention.append(dict(kind='documentation',title='No equipment recorded',clinic_id=c['id'],clinic_name=c['name'],
                                  detail='Documentation gap · add this clinic’s equipment'))
    from .devices import topology
    for c in clinics:
        if not c['device_count']:continue
        topo=topology(c['id'],'all',conn)
        names={n['id']:n['name'] for n in topo['nodes']+topo['offsite']}
        grouped={}
        for issue in topo['documentation']:
            ids=[issue['id']] if issue['kind']=='device' else [issue['parent'],issue['child']] if issue['kind']=='connection' else []
            for did in ids:
                if did in names:grouped.setdefault(did,[]).append(issue['message'])
        for did,messages in grouped.items():
            messages=list(dict.fromkeys(messages))
            attention.append(dict(kind='documentation',topology=True,title=names[did],clinic_id=c['id'],device_id=did,
                                  clinic_name=c['name'],detail=f"{len(messages)} documentation items · "+'; '.join(messages)))
    services = rows_to_list(conn.execute('''SELECT s.id,s.name,d.clinic_id FROM device_services s
        JOIN devices d ON d.id=s.device_id WHERE TRIM(COALESCE(s.support_email,''))=''
        AND TRIM(COALESCE(s.support_url,''))='' ORDER BY s.name COLLATE NOCASE,s.id'''))
    for s in services:
        if s['clinic_id'] in selected:
            attention.append(dict(kind='service',title=s['name'],clinic_id=s['clinic_id'],clinic_name=selected[s['clinic_id']]['name'],
                                  detail='Documentation gap · add a support link or email',service_id=s['id']))
    upcoming = [dict(kind='task',id=t['id'],title=t['title'],date=t['due_date'],clinic_id=t['clinic_id'],clinic_name=t['clinic_name'])
                for t in tasks if t['due_date'] and today.isoformat() <= t['due_date'] <= end.isoformat()]
    appointments = rows_to_list(conn.execute("SELECT id,title,start_time,clinic_id,appt_type FROM appointments WHERE status='scheduled' ORDER BY start_time"))
    for a in appointments:
        day = appointment_day(a['start_time'])
        if a['clinic_id'] in selected and day and today <= day <= end:
            upcoming.append(dict(kind='appointment',id=a['id'],title=a['title'],date=day.isoformat(),start_time=a['start_time'],
                                 clinic_id=a['clinic_id'],clinic_name=selected[a['clinic_id']]['name']))
    upcoming.sort(key=lambda row:(row['date'],row.get('start_time',''),row['id']))
    return dict(today=today.isoformat(),through=end.isoformat(),include_prospects=include_prospects,
                summary=dict(current_clients=sum(c['relationship']=='current_client' for c in clinics),
                             devices=sum(c['device_count'] for c in clinics),servers=sum(c['server_count'] for c in clinics),
                             overdue_tasks=len(overdue),open_tasks=len(tasks),services=sum(c['service_count'] for c in clinics)),
                clinics=clinics,attention=attention,upcoming=upcoming)
