import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
import unicodedata
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import load_workbook
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
from .database import connection, DB
from .excel import parse_excel
import psycopg
SECURE = os.getenv('COOKIE_SECURE', 'true').lower() == 'true'
app = FastAPI(title='Assiduité · OFPPT', docs_url=None, redoc_url=None, openapi_url=None)

def password_digest(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

def set_admin(username, password):
    if not username.strip() or len(password) < 12:
        raise ValueError('Identifiant requis ; mot de passe : au moins 12 caractères.')
    salt = secrets.token_hex(16)
    digest = password_digest(password, salt)
    with connection() as c:
        c.execute('DELETE FROM admin')
        c.execute('INSERT INTO admin VALUES (?,?,?)', (username.strip(), salt, digest))
        c.execute('DELETE FROM sessions')

@app.middleware('http')
async def harden(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-app-request') != '1':
        return Response('Requête refusée', status_code=403)
    try:
        response = await call_next(request)
    except (RuntimeError, psycopg.OperationalError):
        return Response('Service indisponible : vérifier DATABASE_URL et la configuration du serveur.', status_code=503)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response

def authenticated(request: Request):
    token = request.cookies.get('session', '')
    hashed = hashlib.sha256(token.encode()).hexdigest()
    with connection() as c:
        row = c.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?', (hashed, int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401, 'Veuillez vous connecter.')
    return hashed

class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)

@app.post('/api/login')
def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else 'local'
    now = int(time.time())
    with connection() as c:
        # Serialize login attempts so concurrent requests cannot bypass the counter.
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM attempts WHERE since<?', (now-900,))
        attempt = c.execute('SELECT * FROM attempts WHERE ip=?', (ip,)).fetchone()
        if attempt and attempt['count'] >= 8:
            raise HTTPException(429, 'Trop de tentatives. Réessayez dans 15 minutes.')
        c.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(ip) DO UPDATE SET count=attempts.count+1', (ip, now))
        admin = c.execute('SELECT * FROM admin LIMIT 1').fetchone()
    if not admin:
        raise HTTPException(503, 'Compte administrateur à configurer sur le serveur.')
    actual = password_digest(body.password, admin['salt'])
    if not (hmac.compare_digest(actual, admin['digest']) and hmac.compare_digest(body.username.encode(), admin['username'].encode())):
        raise HTTPException(401, 'Identifiant ou mot de passe incorrect.')
    token = secrets.token_urlsafe(32)
    with connection() as c:
        c.execute('DELETE FROM attempts WHERE ip=?', (ip,))
        c.execute('DELETE FROM sessions WHERE expires<?', (now,))
        c.execute('INSERT INTO sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(), now+28800))
    response.set_cookie('session', token, httponly=True, secure=SECURE, samesite='strict', max_age=28800, path='/')
    return {'ok': True}

@app.post('/api/logout')
def logout(response: Response, token=Depends(authenticated)):
    with connection() as c:
        c.execute('DELETE FROM sessions WHERE token=?', (token,))
    response.delete_cookie('session', path='/', secure=SECURE, httponly=True, samesite='strict')
    return {'ok': True}

@app.get('/api/data')
def data(_=Depends(authenticated)):
    with connection() as c:
        return {'students': [dict(r) for r in c.execute('SELECT * FROM students ORDER BY nom,prenom')], 'abs': [dict(r) for r in c.execute('SELECT * FROM absences ORDER BY week DESC')]}

class Student(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    nom: str = Field(min_length=1, max_length=100)
    prenom: str = Field(min_length=1, max_length=100)
    groupe: str = Field(default='', max_length=100)
    site: str = Field(default='', max_length=150)

def clean_student(body):
    d = {k: v.strip() for k,v in body.model_dump().items()}
    if not all(d[k] for k in ('id','nom','prenom')):
        raise HTTPException(422, 'Matricule, nom et prénom sont obligatoires.')
    d['id'] = d['id'].upper()
    return d

@app.post('/api/students')
def add_student(body: Student, _=Depends(authenticated)):
    d = clean_student(body)
    try:
        with connection() as c:
            c.execute('INSERT INTO students (id,nom,prenom,groupe,site) VALUES (:id,:nom,:prenom,:groupe,:site)', d)
    except (sqlite3.IntegrityError, psycopg.IntegrityError):
        raise HTTPException(409, 'Ce matricule existe déjà.')
    return d

@app.put('/api/students/{sid:path}')
def update_student(sid: str, body: Student, _=Depends(authenticated)):
    d = clean_student(body)
    if d['id'] != sid:
        raise HTTPException(422, 'Le matricule ne peut pas être modifié.')
    with connection() as c:
        if not c.execute('UPDATE students SET nom=:nom,prenom=:prenom,groupe=:groupe,site=:site WHERE id=:id', d).rowcount:
            raise HTTPException(404, 'Élève introuvable.')
    return d

@app.delete('/api/students/{sid:path}')
def delete_student(sid: str, _=Depends(authenticated)):
    with connection() as c:
        if not c.execute('DELETE FROM students WHERE id=?', (sid,)).rowcount:
            raise HTTPException(404, 'Élève introuvable.')
    return {'ok': True}

class Absence(BaseModel):
    sid: str = Field(min_length=1, max_length=50)
    week: str
    status: str
    quantity: int = Field(default=1, ge=1, le=1000, strict=True)
    note: str = Field(default='', max_length=500)

def validate_abs(body):
    try:
        if not re.fullmatch(r'\d{4}-W\d{2}', body.week):
            raise ValueError()
        y, w = body.week.split('-W')
        date.fromisocalendar(int(y), int(w), 1)
    except ValueError:
        raise HTTPException(422, 'Semaine ISO invalide.')
    if body.status not in ('yes','no'):
        raise HTTPException(422, 'Statut invalide.')
    return body.model_dump()

@app.post('/api/absences')
def add_abs(body: Absence, _=Depends(authenticated)):
    d = validate_abs(body)
    d['id'] = secrets.token_hex(16)
    try:
        with connection() as c:
            c.execute('INSERT INTO absences (id,sid,week,status,note,quantity) VALUES (:id,:sid,:week,:status,:note,:quantity)', d)
    except (sqlite3.IntegrityError, psycopg.IntegrityError):
        raise HTTPException(422, 'Élève introuvable.')
    return d

@app.put('/api/absences/{aid}')
def update_abs(aid: str, body: Absence, _=Depends(authenticated)):
    d = validate_abs(body)
    d['id'] = aid
    try:
        with connection() as c:
            if not c.execute('UPDATE absences SET sid=:sid,week=:week,status=:status,note=:note,quantity=:quantity WHERE id=:id', d).rowcount:
                raise HTTPException(404, 'Absence introuvable.')
    except (sqlite3.IntegrityError, psycopg.IntegrityError):
        raise HTTPException(422, 'Élève introuvable.')
    return d

@app.delete('/api/absences/{aid}')
def delete_abs(aid: str, _=Depends(authenticated)):
    with connection() as c:
        if not c.execute('DELETE FROM absences WHERE id=?', (aid,)).rowcount:
            raise HTTPException(404, 'Absence introuvable.')
    return {'ok': True}

@app.post('/api/import/preview')
async def preview(file: UploadFile, _=Depends(authenticated)):
    raw = await file.read(4*1024*1024+1)
    if len(raw) > 4*1024*1024:
        raise HTTPException(413, 'Fichier limité à 4 Mo.')
    if not (file.filename or '').lower().endswith(('.xlsx','.xls')):
        raise HTTPException(422, 'Utilisez un .xlsx ou un export XML Excel .xls.')
    try:
        return parse_excel(raw, file.filename)
    except Exception as e:
        raise HTTPException(422, 'Excel invalide. Les .xls binaires doivent être réenregistrés en .xlsx ; les exports XML .xls sont acceptés.') from e

class ImportRequest(BaseModel):
    students: list[Student] = Field(min_length=1, max_length=10000)

@app.post('/api/import/commit')
def commit_import(body: ImportRequest, _=Depends(authenticated)):
    students = [clean_student(s) for s in body.students]
    ids = [s['id'] for s in students]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, 'Matricules en double dans le fichier : corrigez-les avant l’import.')
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        existing = {r['id'] for r in c.execute('SELECT id FROM students')}
        added = [s for s in students if s['id'] not in existing]
        c.executemany('INSERT INTO students (id,nom,prenom,groupe,site) VALUES (:id,:nom,:prenom,:groupe,:site)', added)
    return {'added': len(added), 'skipped': len(students)-len(added)}

app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')
@app.get('/')
def index():
    return FileResponse(ROOT/'static'/'index.html', headers={'Cache-Control':'no-cache'})
