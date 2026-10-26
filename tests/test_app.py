import importlib
import io
import os
import uuid
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

@pytest.fixture(params=["sqlite"] + (["postgres"] if os.getenv("TEST_DATABASE_URL") else []))
def system(tmp_path, monkeypatch, request):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('VERCEL', raising=False)
    schema = None
    if request.param == 'postgres':
        schema = 'test_' + uuid.uuid4().hex
        with psycopg.connect(os.environ['TEST_DATABASE_URL']) as con:
            con.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        monkeypatch.setenv('DATABASE_URL', make_conninfo(os.environ['TEST_DATABASE_URL'], options='-csearch_path='+schema))
    from app import database
    importlib.reload(database)
    from app import main
    importlib.reload(main)
    main.set_admin('test-admin', 'Strong-test-only-1234')
    try:
        with TestClient(main.app) as client:
            client.headers['X-App-Request']='1'
            yield client,main
    finally:
        if schema:
            with psycopg.connect(os.environ['TEST_DATABASE_URL']) as con:
                con.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

def login(c):
    return c.post('/api/login', json={'username':'test-admin','password':'Strong-test-only-1234'})

def test_auth_and_logout(system):
    c,m=system
    assert c.get('/api/data').status_code==401
    assert c.post('/api/login',json={'username':'test-admin','password':'wrong'}).status_code==401
    assert login(c).status_code==200
    assert 'HttpOnly' in login(c).headers['set-cookie']
    assert c.get('/api/data').status_code==200
    c.post('/api/logout')
    assert c.get('/api/data').status_code==401

def test_csrf_and_throttling(system):
    c,m=system
    c.headers.pop('X-App-Request')
    assert login(c).status_code==403
    c.headers['X-App-Request']='1'
    for attempt in range(1,9):
        assert c.post('/api/login',json={'username':'x','password':'wrong'}).status_code==401
        with m.connection() as db:
            assert db.execute('SELECT count FROM attempts').fetchone()['count']==attempt
    assert login(c).status_code==429

def test_students_absences_persistence(system):
    c,m=system
    login(c)
    s={'id':' 001a ','nom':'Exemple','prenom':'Test','groupe':'DEV101'}
    assert c.post('/api/students',json=s).status_code==200
    assert c.post('/api/students',json=s).status_code==409
    a={'sid':'001A','week':'2026-W43','status':'no','note':'Test'}
    assert c.post('/api/absences',json={**a,'week':'2026-W99'}).status_code==422
    assert c.post('/api/absences',json={**a,'sid':'missing'}).status_code==422
    result=c.post('/api/absences',json=a)
    assert result.status_code==200
    aid=result.json()['id']
    assert c.put('/api/absences/'+aid,json={**a,'status':'yes'}).status_code==200
    # Persisted record through an independent connection, on either backend.
    with m.connection() as db:
        assert db.execute('SELECT status FROM absences').fetchone()['status']=='yes'
    assert c.get('/api/data').json()['abs'][0]['status']=='yes'
    assert c.delete('/api/students/001A').status_code==200
    assert c.get('/api/data').json()=={'students':[],'abs':[]}

def test_excel_preview_and_import_atomicity(system):
    c,m=system
    login(c)
    wb=Workbook();ws=wb.active
    ws.append(['Matricule','Nom','Prénom','Groupe'])
    ws.append(['0001','Exemple','Lina','DEV101'])
    data=io.BytesIO();wb.save(data)
    r=c.post('/api/import/preview',files={'file':('test.xlsx',data.getvalue())})
    assert r.status_code==200
    assert r.json()['sheets'][0]['rows'][0][0]=='0001'
    s={'id':'0001','nom':'Exemple','prenom':'Lina'}
    assert c.post('/api/import/commit',json={'students':[s,s]}).status_code==422
    assert c.get('/api/data').json()['students']==[]
    assert c.post('/api/import/commit',json={'students':[s]}).json()=={'added':1,'skipped':0}
    assert c.post('/api/import/commit',json={'students':[s]}).json()=={'added':0,'skipped':1}
    assert c.post('/api/import/preview',files={'file':('bad.xlsx',b'bad')}).status_code==422

def test_expiry_reset_and_private_routes(system):
    c,m=system
    login(c)
    with m.connection() as db:
        db.execute('UPDATE sessions SET expires=0')
    assert c.get('/api/data').status_code==401
    login(c)
    m.set_admin('new-admin','New-password-12345')
    assert c.get('/api/data').status_code==401
    assert c.get('/data/absence.sqlite3').status_code==404
    assert c.get('/').status_code==200


def test_xml_export_and_site(system):
    c,m=system
    login(c)
    xml=b'''<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Export"><Table><Row><Cell><Data>MatriculeEtudiant</Data></Cell><Cell><Data>Nom</Data></Cell><Cell><Data>Prenom</Data></Cell><Cell><Data>groupe</Data></Cell><Cell><Data>Site</Data></Cell></Row><Row><Cell><Data>000001</Data></Cell><Cell><Data>Exemple</Data></Cell><Cell><Data>Test</Data></Cell><Cell><Data>G1</Data></Cell><Cell><Data>Centre exemple</Data></Cell></Row></Table></Worksheet></Workbook>'''
    result=c.post('/api/import/preview', files={'file':('export.xls',xml)})
    assert result.status_code==200
    assert result.json()['sheets'][0]['rows'][0][0]=='000001'
    s={'id':'000001','nom':'Exemple','prenom':'Test','groupe':'G1','site':'Centre exemple'}
    assert c.post('/api/import/commit',json={'students':[s]}).status_code==200
    assert c.get('/api/data').json()['students'][0]['site']=='Centre exemple'
    assert c.post('/api/import/preview',files={'file':('evil.xls',b'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><x>&xxe;</x>')}).status_code==422


def test_postgres_query_adapter():
    from app.database import Postgres
    assert Postgres.sql('SELECT * FROM students WHERE id=?')=='SELECT * FROM students WHERE id=%s'
    assert Postgres.sql('UPDATE students SET nom=:nom WHERE id=:id')=='UPDATE students SET nom=%(nom)s WHERE id=%(id)s'
    assert 'pg_advisory_xact_lock' in Postgres.sql('BEGIN IMMEDIATE')
