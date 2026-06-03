import os
import json
import time
import uuid
import threading
import secrets
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
from compiler import process_and_build

app = FastAPI()

os.makedirs('downloads', exist_ok=True)
app.mount("/download", StaticFiles(directory="downloads"), name="download")

db_lock = threading.Lock()
compiler_lock = threading.Lock()

app.state.token = None
app.state.expiry = 0

class LoginReq(BaseModel):
    password: str

class DeleteReq(BaseModel):
    key: str = None
    value: str = None

class AdminTestReq(BaseModel):
    password: str
    code_data: dict

def get_password():
    if not os.path.exists('ajim.txt'):
        return ""
    with open('ajim.txt', 'r', encoding='utf-8') as f:
        return f.read().strip()

def generate_new_token():
    new_token = str(uuid.uuid4())
    app.state.token = new_token
    app.state.expiry = time.time() + 120
    return new_token

def validate_and_roll_token(authorization: str):
    if not authorization or not app.state.token:
        app.state.token = None
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if not secrets.compare_digest(authorization, app.state.token):
        app.state.token = None
        raise HTTPException(status_code=401, detail="Invalid Token")
    
    if time.time() > app.state.expiry:
        app.state.token = None
        raise HTTPException(status_code=401, detail="Token Expired")
    
    return generate_new_token()

def read_db(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return {}

def write_db(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

@app.get("/user/read")
def user_read():
    with db_lock:
        return read_db('update_db.json')

@app.post("/user/post")
async def user_post(request: Request):
    data = await request.json()
    return {"status": "success", "received": data}

@app.post("/user/compile")
async def user_compile(request: Request):
    data = await request.json()
    with db_lock:
        u_db = read_db('update_db.json')
    
    with compiler_lock:
        apk_filename = process_and_build(data, u_db)
        
    base_url = str(request.base_url).rstrip('/')
    apk_url = f"{base_url}/download/{apk_filename}"
    return {"status": "compiled", "apk_url": apk_url}

@app.post("/user/test-code")
async def user_test_code(request: Request):
    data = await request.json()
    with db_lock:
        u_db = read_db('update_db.json')
        
    with compiler_lock:
        result = process_and_build(data, u_db, test_mode=True)
        
    return {"status": "tested", "result": result}

@app.post("/admin/login")
def admin_login(req: LoginReq):
    pwd = get_password()
    if not pwd or not secrets.compare_digest(req.password, pwd):
        raise HTTPException(status_code=401, detail="Invalid Password")
    token = generate_new_token()
    return {"token": token}

@app.post("/admin/save")
async def admin_save(request: Request, authorization: str = Header(None)):
    new_token = validate_and_roll_token(authorization)
    data = await request.json()
    
    with db_lock:
        db = read_db('save_db.json')
        for k, v in data.items():
            if k not in db:
                db[k] = []
            if isinstance(v, list):
                db[k].extend(v)
            else:
                db[k].append(v)
        write_db('save_db.json', db)
    
    return {"status": "saved", "token": new_token}

@app.post("/admin/update")
def admin_update(authorization: str = Header(None)):
    new_token = validate_and_roll_token(authorization)
    
    with db_lock:
        s_db = read_db('save_db.json')
        if s_db:
            u_db = read_db('update_db.json')
            for k, v in s_db.items():
                if k not in u_db:
                    u_db[k] = []
                u_db[k].extend(v)
            write_db('update_db.json', u_db)
            write_db('save_db.json', {})
        
    return {"status": "updated", "token": new_token}

@app.post("/admin/delete")
def admin_delete(req: DeleteReq, authorization: str = Header(None)):
    new_token = validate_and_roll_token(authorization)
    
    with db_lock:
        if not req.key:
            write_db('update_db.json', {})
        else:
            u_db = read_db('update_db.json')
            if req.key in u_db:
                if req.value and req.value in u_db[req.key]:
                    u_db[req.key].remove(req.value)
                elif not req.value:
                    del u_db[req.key]
                write_db('update_db.json', u_db)
        
    return {"status": "deleted", "token": new_token}

@app.post("/admin/compile")
async def admin_compile(request: Request, authorization: str = Header(None)):
    new_token = validate_and_roll_token(authorization)
    data = await request.json()
    
    with db_lock:
        u_db = read_db('update_db.json')
        
    with compiler_lock:
        apk_filename = process_and_build(data, u_db)
    
    base_url = str(request.base_url).rstrip('/')
    apk_url = f"{base_url}/download/{apk_filename}"
    return {"status": "compiled", "apk_url": apk_url, "token": new_token}

@app.post("/admin/test-code")
def admin_test_code(req: AdminTestReq):
    pwd = get_password()
    if not pwd or not secrets.compare_digest(req.password, pwd):
        raise HTTPException(status_code=401, detail="Invalid Password")
    
    with db_lock:
        u_db = read_db('update_db.json')
        
    with compiler_lock:
        result = process_and_build(req.code_data, u_db, test_mode=True)
        
    return {"status": "tested", "result": result}

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)