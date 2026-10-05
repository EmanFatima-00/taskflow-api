"""
TaskFlow - REST API + React frontend in ONE file.

Run:
    pip install fastapi uvicorn
    uvicorn main:app --reload
Open:
    App      -> http://localhost:8000
    API docs -> http://localhost:8000/docs
"""
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

DB_FILE = "tasks.db"
STATUSES = ("todo", "in_progress", "done")
PRIORITIES = ("low", "medium", "high")
SORTS = {
    "newest": "id DESC",
    "oldest": "id ASC",
    "due": "due_date IS NULL, due_date ASC",
    "priority": "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id DESC",
    "title": "title COLLATE NOCASE ASC",
}


# ----------------------------------------------------------------- database
@contextmanager
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'todo',
                priority TEXT DEFAULT 'medium',
                due_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)"""
        )
        if c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
            now = datetime.now().isoformat(timespec="seconds")
            seed = [
                ("Design the API routes", "List every endpoint and its status codes.", "done", "high", None),
                ("Build the dashboard UI", "Cards, filters, and a task form.", "in_progress", "high", None),
                ("Write the README", "Setup steps and an endpoint table.", "todo", "medium", None),
                ("Test with Postman", "Cover success and error cases.", "todo", "low", None),
            ]
            c.executemany(
                "INSERT INTO tasks (title,description,status,priority,due_date,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                [(*s, now, now) for s in seed],
            )
            # ------------------------------------------------------------------- schemas
def _check_date(v):
    if v in (None, ""):
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError("must be a valid date in YYYY-MM-DD format")
    return v


class TaskCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(..., min_length=3, max_length=100)
    description: str = Field("", max_length=500)
    status: Literal["todo", "in_progress", "done"] = "todo"
    priority: Literal["low", "medium", "high"] = "medium"
    due_date: Optional[str] = None

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, v):
        return _check_date(v)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    status: Optional[Literal["todo", "in_progress", "done"]] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    due_date: Optional[str] = None

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, v):
        return _check_date(v)


# ----------------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="TaskFlow API", version="1.0.0", lifespan=lifespan,
              description="A task manager REST API with a React frontend.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def ok(data=None, message="Success", code=200, **extra):
    return JSONResponse({"success": True, "message": message, "data": data, **extra}, status_code=code)


@app.exception_handler(StarletteHTTPException)
async def http_error(_, e):
    return JSONResponse({"success": False, "message": str(e.detail), "data": None}, status_code=e.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_, e):
    msg = "; ".join(
        f"{'.'.join(str(p) for p in x['loc'][1:]) or 'request'}: {x['msg'].replace('Value error, ', '')}"
        for x in e.errors()
    )
    return JSONResponse({"success": False, "message": msg, "data": None}, status_code=422)


@app.exception_handler(Exception)
async def server_error(_, e):
    return JSONResponse({"success": False, "message": "Internal server error", "data": None}, status_code=500)


def get_or_404(c, task_id: int):
    row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Task {task_id} not found")
    return row


def apply_update(task_id: int, fields: dict):
    with db() as c:
        get_or_404(c, task_id)
        if fields:
            fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*fields.values(), task_id))
        return dict(get_or_404(c, task_id))
    # -------------------------------------------------------------------- routes
@app.get("/api/tasks", tags=["Tasks"])
def list_tasks(q: str = "", status: str = "", priority: str = "", sort: str = "newest",
               page: int = 1, limit: int = 6):
    if status and status not in STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
    if priority and priority not in PRIORITIES:
        raise HTTPException(400, f"priority must be one of {', '.join(PRIORITIES)}")
    if sort not in SORTS:
        raise HTTPException(400, f"sort must be one of {', '.join(SORTS)}")
    page, limit = max(page, 1), min(max(limit, 1), 50)
    where, params = [], []
    if q.strip():
        where.append("(title LIKE ? OR description LIKE ?)")
        params += [f"%{q.strip()}%"] * 2
    if status:
        where.append("status=?"); params.append(status)
    if priority:
        where.append("priority=?"); params.append(priority)
    clause = "WHERE " + " AND ".join(where) if where else ""
    with db() as c:
        total = c.execute(f"SELECT COUNT(*) FROM tasks {clause}", params).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM tasks {clause} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
            (*params, limit, (page - 1) * limit),
        ).fetchall()
    pages = max(1, -(-total // limit))
    return ok([dict(r) for r in rows], "Tasks retrieved", meta={"total": total, "page": page, "pages": pages})


@app.get("/api/stats", tags=["Tasks"])
def stats():
    with db() as c:
        rows = c.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status").fetchall()
        overdue = c.execute(
            "SELECT COUNT(*) FROM tasks WHERE due_date < ? AND status != 'done'", (date.today().isoformat(),)
        ).fetchone()[0]
    s = {r["status"]: r["n"] for r in rows}
    data = {k: s.get(k, 0) for k in STATUSES}
    data.update(total=sum(data.values()), overdue=overdue)
    return ok(data, "Stats retrieved")


@app.get("/api/tasks/{task_id}", tags=["Tasks"])
def get_task(task_id: int):
    with db() as c:
        return ok(dict(get_or_404(c, task_id)), "Task retrieved")


@app.post("/api/tasks", status_code=201, tags=["Tasks"])
def create_task(task: TaskCreate):
    now = datetime.now().isoformat(timespec="seconds")
    with db() as c:
        cur = c.execute(
            "INSERT INTO tasks (title,description,status,priority,due_date,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (task.title, task.description, task.status, task.priority, task.due_date, now, now),
        )
        row = dict(get_or_404(c, cur.lastrowid))
    return ok(row, "Task created", 201)


@app.put("/api/tasks/{task_id}", tags=["Tasks"])
def replace_task(task_id: int, task: TaskCreate):
    return ok(apply_update(task_id, task.model_dump()), "Task updated")


@app.patch("/api/tasks/{task_id}", tags=["Tasks"])
def patch_task(task_id: int, task: TaskUpdate):
    fields = task.model_dump(exclude_unset=True)
    if "title" in fields and fields["title"] is None:
        raise HTTPException(400, "title cannot be null")
    return ok(apply_update(task_id, fields), "Task updated")


@app.delete("/api/tasks/{task_id}", status_code=204, tags=["Tasks"])
def delete_task(task_id: int):
    with db() as c:
        get_or_404(c, task_id)
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return PAGE
# ------------------------------------------------------------------ frontend
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TaskFlow</title>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={darkMode:'class',theme:{extend:{fontFamily:{sans:['Manrope','system-ui','sans-serif']}}}}</script>
<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>@keyframes pop{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:none}}.pop{animation:pop .15s ease-out}</style>
</head>
<body class="bg-stone-100 dark:bg-slate-950 text-slate-800 dark:text-slate-100 font-sans antialiased">
<div id="root"></div>
<script type="text/babel">
const {useState,useEffect,useCallback}=React;
const PRI={high:'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300',medium:'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',low:'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'};
const STA={todo:'To do',in_progress:'In progress',done:'Done'};
const card='bg-white dark:bg-slate-900 border border-stone-200 dark:border-slate-800 rounded-2xl';
const inp='w-full rounded-xl border border-stone-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-teal-600';
const btn='rounded-xl px-4 py-2.5 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-teal-600';
const today=()=>new Date().toLocaleDateString('en-CA');

async function api(path,opts={}){
  const r=await fetch('/api'+path,{headers:{'Content-Type':'application/json'},...opts});
  if(r.status===204)return {success:true};
  const j=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(j.message||'Request failed ('+r.status+')');
  return j;
}
function useDebounce(v,ms){const[x,setX]=useState(v);useEffect(()=>{const t=setTimeout(()=>setX(v),ms);return()=>clearTimeout(t)},[v]);return x}

function Field({label,error,children}){return <label className="block"><span className="mb-1 block text-sm font-semibold">{label}</span>{children}{error&&<span className="mt-1 block text-xs text-rose-600">{error}</span>}</label>}

function TaskModal({task,onClose,onSave}){
  const[f,setF]=useState(task?{...task,due_date:task.due_date||''}:{title:'',description:'',status:'todo',priority:'medium',due_date:''});
  const[err,setErr]=useState({});const[busy,setBusy]=useState(false);
  const set=(k,v)=>setF(p=>({...p,[k]:v}));
  const submit=async e=>{e.preventDefault();
    const er={};const t=f.title.trim();
    if(t.length<3)er.title='Title needs at least 3 characters.';
    if(t.length>100)er.title='Title can be 100 characters at most.';
    if(f.description.length>500)er.description='Description can be 500 characters at most.';
    setErr(er);if(Object.keys(er).length)return;
    setBusy(true);await onSave({title:t,description:f.description,status:f.status,priority:f.priority,due_date:f.due_date||null});setBusy(false)};
  return <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4" onMouseDown={e=>e.target===e.currentTarget&&onClose()}>
    <form onSubmit={submit} className={card+' pop w-full max-w-lg p-6 space-y-4 max-h-[92vh] overflow-y-auto'}>
      <h2 className="text-xl font-extrabold">{task?'Edit task':'New task'}</h2>
      <Field label="Title" error={err.title}><input autoFocus className={inp} value={f.title} onChange={e=>set('title',e.target.value)} placeholder="What needs to be done?"/></Field>
      <Field label="Description" error={err.description}><textarea rows="3" className={inp} value={f.description} onChange={e=>set('description',e.target.value)} placeholder="Add details (optional)"/></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Status"><select className={inp} value={f.status} onChange={e=>set('status',e.target.value)}>{Object.entries(STA).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Priority"><select className={inp} value={f.priority} onChange={e=>set('priority',e.target.value)}>{['low','medium','high'].map(p=><option key={p} value={p}>{p[0].toUpperCase()+p.slice(1)}</option>)}</select></Field>
      </div>
      <Field label="Due date"><input type="date" className={inp} value={f.due_date} onChange={e=>set('due_date',e.target.value)}/></Field>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={onClose} className={btn+' hover:bg-stone-100 dark:hover:bg-slate-800'}>Cancel</button>
        <button disabled={busy} className={btn+' bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-60'}>{busy?'Saving...':task?'Save changes':'Create task'}</button>
      </div>
    </form></div>;
}

function Confirm({task,onCancel,onConfirm}){
  return <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4">
    <div className={card+' pop w-full max-w-sm p-6'}>
      <h3 className="text-lg font-extrabold">Delete this task?</h3>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">"{task.title}" will be removed permanently.</p>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onCancel} className={btn+' hover:bg-stone-100 dark:hover:bg-slate-800'}>Keep task</button>
        <button onClick={onConfirm} className={btn+' bg-rose-600 text-white hover:bg-rose-700'}>Delete task</button>
      </div></div></div>;
}

function Stat({label,value,tone}){return <div className={card+' p-4'}><div className={'text-3xl font-extrabold '+tone}>{value}</div><div className="text-sm text-slate-500 dark:text-slate-400">{label}</div></div>}

function TaskRow({t,onEdit,onDelete,onStatus}){
  const overdue=t.due_date&&t.due_date<today()&&t.status!=='done';const done=t.status==='done';
  return <div className={card+' p-4 flex gap-3 items-start'}>
    <button title={done?'Mark as to do':'Mark as done'} onClick={()=>onStatus(t,done?'todo':'done')}
      className={'mt-0.5 h-6 w-6 shrink-0 rounded-full border-2 flex items-center justify-center text-xs '+(done?'bg-teal-700 border-teal-700 text-white':'border-stone-300 dark:border-slate-600 hover:border-teal-600')}>{done&&'✓'}</button>
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className={'font-bold break-words '+(done?'line-through text-slate-400':'')}>{t.title}</h3>
        <span className={'rounded-full px-2 py-0.5 text-xs font-semibold '+PRI[t.priority]}>{t.priority}</span>
      </div>
      {t.description&&<p className="mt-1 text-sm text-slate-500 dark:text-slate-400 break-words">{t.description}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
        <select value={t.status} onChange={e=>onStatus(t,e.target.value)} className="rounded-lg border border-stone-300 dark:border-slate-700 bg-transparent px-2 py-1 font-semibold">{Object.entries(STA).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select>
        {t.due_date&&<span className={overdue?'font-bold text-rose-600':'text-slate-500 dark:text-slate-400'}>{overdue?'Overdue: ':'Due '}{t.due_date}</span>}
      </div>
    </div>
    <div className="flex gap-1 shrink-0">
      <button onClick={()=>onEdit(t)} className="rounded-lg px-2.5 py-1.5 text-sm font-semibold hover:bg-stone-100 dark:hover:bg-slate-800">Edit</button>
      <button onClick={()=>onDelete(t)} className="rounded-lg px-2.5 py-1.5 text-sm font-semibold text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10">Delete</button>
    </div></div>;
}
function App(){
  const[tasks,setTasks]=useState([]);const[meta,setMeta]=useState({total:0,pages:1});
  const[stats,setStats]=useState({total:0,todo:0,in_progress:0,done:0,overdue:0});
  const[loading,setLoading]=useState(true);const[error,setError]=useState('');
  const[q,setQ]=useState('');const[status,setStatus]=useState('');const[priority,setPriority]=useState('');const[sort,setSort]=useState('newest');const[page,setPage]=useState(1);
  const[modal,setModal]=useState(null);const[del,setDel]=useState(null);const[toasts,setToasts]=useState([]);
  const[dark,setDark]=useState(localStorage.getItem('dark')==='1');
  const dq=useDebounce(q,300);
  useEffect(()=>{document.documentElement.classList.toggle('dark',dark);localStorage.setItem('dark',dark?'1':'0')},[dark]);
  const toast=(m,t='ok')=>{const id=Math.random();setToasts(a=>[...a,{id,m,t}]);setTimeout(()=>setToasts(a=>a.filter(x=>x.id!==id)),3500)};
  const load=useCallback(async()=>{
    setLoading(true);setError('');
    try{
      const p=new URLSearchParams({q:dq,status,priority,sort,page,limit:6});
      const[l,s]=await Promise.all([api('/tasks?'+p),api('/stats')]);
      setTasks(l.data);setMeta(l.meta);setStats(s.data);
      if(l.meta.page>l.meta.pages)setPage(l.meta.pages);
    }catch(e){setError(e.message==='Failed to fetch'?'Cannot reach the server. Check that it is running.':e.message)}
    setLoading(false);
  },[dq,status,priority,sort,page]);
  useEffect(()=>{load()},[load]);
  useEffect(()=>{setPage(1)},[dq,status,priority,sort]);

  const save=async f=>{try{
    if(modal.id){await api('/tasks/'+modal.id,{method:'PUT',body:JSON.stringify(f)});toast('Task updated')}
    else{await api('/tasks',{method:'POST',body:JSON.stringify(f)});toast('Task created')}
    setModal(null);load();
  }catch(e){toast(e.message,'err')}};
  const changeStatus=async(t,s)=>{try{await api('/tasks/'+t.id,{method:'PATCH',body:JSON.stringify({status:s})});toast('Moved to '+STA[s].toLowerCase());load()}catch(e){toast(e.message,'err')}};
  const remove=async()=>{try{await api('/tasks/'+del.id,{method:'DELETE'});toast('Task deleted');setDel(null);load()}catch(e){toast(e.message,'err');setDel(null)}};
  const pct=stats.total?Math.round(stats.done/stats.total*100):0;
  const filtered=q||status||priority;

  return <div className="mx-auto max-w-4xl px-4 py-6 sm:py-10">
    <header className="flex items-center justify-between gap-3">
      <div><h1 className="text-3xl font-extrabold tracking-tight">TaskFlow</h1><p className="text-sm text-slate-500 dark:text-slate-400">Plan it, track it, finish it.</p></div>
      <div className="flex gap-2">
        <button onClick={()=>setDark(!dark)} className={btn+' border border-stone-300 dark:border-slate-700'}>{dark?'Light':'Dark'}</button>
        <button onClick={()=>setModal({})} className={btn+' bg-teal-700 text-white hover:bg-teal-800'}>New task</button>
      </div>
    </header>

    <section className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label="Total tasks" value={stats.total} tone=""/>
      <Stat label="To do" value={stats.todo} tone="text-slate-500"/>
      <Stat label="In progress" value={stats.in_progress} tone="text-amber-600"/>
      <Stat label="Done" value={stats.done} tone="text-teal-700 dark:text-teal-400"/>
    </section>
    <div className={card+' mt-3 p-4'}>
      <div className="mb-2 flex justify-between text-sm font-semibold"><span>{pct}% complete</span>{stats.overdue>0&&<span className="text-rose-600">{stats.overdue} overdue</span>}</div>
      <div className="h-2.5 overflow-hidden rounded-full bg-stone-200 dark:bg-slate-800"><div className="h-full rounded-full bg-teal-600 transition-all duration-500" style={{width:pct+'%'}}/></div>
    </div>

    <section className="mt-6 grid gap-2 sm:grid-cols-4">
      <input className={inp+' sm:col-span-2'} placeholder="Search tasks" value={q} onChange={e=>setQ(e.target.value)}/>
      <select className={inp} value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option>{Object.entries(STA).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select>
      <select className={inp} value={priority} onChange={e=>setPriority(e.target.value)}><option value="">All priorities</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
      <select className={inp+' sm:col-span-4'} value={sort} onChange={e=>setSort(e.target.value)}>
        <option value="newest">Sort: Newest first</option><option value="oldest">Sort: Oldest first</option><option value="due">Sort: Due date</option><option value="priority">Sort: Priority</option><option value="title">Sort: Title (A-Z)</option></select>
    </section>

    <section className="mt-4 space-y-3">
      {loading&&!tasks.length&&[1,2,3].map(i=><div key={i} className={card+' h-24 animate-pulse'}/>)}
      {error&&<div className={card+' p-6 text-center'}><p className="font-bold text-rose-600">Something went wrong</p><p className="mt-1 text-sm text-slate-500">{error}</p><button onClick={load} className={btn+' mt-4 bg-teal-700 text-white'}>Try again</button></div>}
      {!error&&!loading&&!tasks.length&&<div className={card+' p-10 text-center'}>
        <p className="text-lg font-extrabold">{filtered?'No tasks match your filters':'No tasks yet'}</p>
        <p className="mt-1 text-sm text-slate-500">{filtered?'Clear the search or filters to see everything.':'Create your first task to get started.'}</p>
        {!filtered&&<button onClick={()=>setModal({})} className={btn+' mt-4 bg-teal-700 text-white'}>Create a task</button>}</div>}
      {!error&&tasks.map(t=><TaskRow key={t.id} t={t} onEdit={setModal} onDelete={setDel} onStatus={changeStatus}/>)}
    </section>

    {!error&&meta.pages>1&&<div className="mt-5 flex items-center justify-center gap-3 text-sm">
      <button disabled={page<=1} onClick={()=>setPage(page-1)} className={btn+' border border-stone-300 dark:border-slate-700 disabled:opacity-40'}>Previous</button>
      <span className="font-semibold">Page {page} of {meta.pages}</span>
      <button disabled={page>=meta.pages} onClick={()=>setPage(page+1)} className={btn+' border border-stone-300 dark:border-slate-700 disabled:opacity-40'}>Next</button></div>}

    {modal&&<TaskModal task={modal.id?modal:null} onClose={()=>setModal(null)} onSave={save}/>}
    {del&&<Confirm task={del} onCancel={()=>setDel(null)} onConfirm={remove}/>}
    <div className="fixed bottom-4 right-4 z-50 space-y-2">{toasts.map(t=><div key={t.id} className={'pop rounded-xl px-4 py-3 text-sm font-semibold text-white shadow-lg '+(t.t==='err'?'bg-rose-600':'bg-slate-800')}>{t.m}</div>)}</div>
  </div>;
}
ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
</script>
</body>
</html>
"""