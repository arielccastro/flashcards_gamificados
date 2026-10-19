from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import sqlite3
import datetime

app = FastAPI(title="App Concurseiro - Flashcards")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

DB_FILE = "flashcards.db"

# --- MODELOS DE DADOS ---
class RespostaReview(BaseModel):
    usuario_id: int
    ficha_id: int
    resposta: str

class NovaFicha(BaseModel):
    frente: str
    verso: str
    topico_id: int
    usuario_id: int = 1

class LoteFichas(BaseModel):
    topico_id: int
    usuario_id: int = 1
    fichas: List[dict]

class NovoBaralho(BaseModel):
    nome: str
    usuario_id: int = 1

class NovoTopico(BaseModel):
    nome: str
    baralho_id: int

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, xp_total INTEGER DEFAULT 0, ofensiva_atual INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS baralhos (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER, nome TEXT);
    CREATE TABLE IF NOT EXISTS topicos (id INTEGER PRIMARY KEY AUTOINCREMENT, baralho_id INTEGER, nome TEXT);
    CREATE TABLE IF NOT EXISTS fichas (id INTEGER PRIMARY KEY AUTOINCREMENT, topico_id INTEGER, frente TEXT, verso TEXT);
    CREATE TABLE IF NOT EXISTS progresso_fichas (id INTEGER PRIMARY KEY AUTOINCREMENT, ficha_id INTEGER, usuario_id INTEGER, proxima_revisao DATE, intervalo_dias INTEGER DEFAULT 0, fator_facilidade REAL DEFAULT 2.5, acertos_consecutivos INTEGER DEFAULT 0, total_erros INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_revisao ON progresso_fichas (usuario_id, proxima_revisao, intervalo_dias);
    """)
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (nome) VALUES ('Concurseiro Alfa')")
        cursor.execute("INSERT INTO baralhos (usuario_id, nome) VALUES (1, 'Direito Constitucional')")
        cursor.execute("INSERT INTO topicos (baralho_id, nome) VALUES (1, 'Direitos Fundamentais')")
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

# --- ROTAS DE LEITURA (GET) ---
@app.get("/api/baralhos/{usuario_id}")
def get_baralhos(usuario_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome FROM baralhos WHERE usuario_id = ?", (usuario_id,))
    baralhos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return baralhos

@app.get("/api/topicos/{baralho_id}")
def get_topicos(baralho_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome FROM topicos WHERE baralho_id = ?", (baralho_id,))
    topicos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return topicos

@app.get("/api/revisao/{usuario_id}/{topico_id}")
def get_fila_revisao(usuario_id: int, topico_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    hoje = datetime.date.today().isoformat()
    cursor.execute("""
        SELECT f.id AS ficha_id, f.frente, f.verso, pf.intervalo_dias
        FROM fichas f
        INNER JOIN progresso_fichas pf ON f.id = pf.ficha_id
        WHERE pf.usuario_id = ? AND f.topico_id = ? AND pf.proxima_revisao <= ?
        ORDER BY pf.proxima_revisao ASC, pf.intervalo_dias ASC LIMIT 20
    """, (usuario_id, topico_id, hoje))
    cartas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"quantidade": len(cartas), "cartas": cartas}

@app.get("/api/estatisticas/{usuario_id}")
def get_estatisticas(usuario_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.frente, pf.total_erros, t.nome as topico, b.nome as baralho
        FROM fichas f
        INNER JOIN progresso_fichas pf ON f.id = pf.ficha_id
        INNER JOIN topicos t ON f.topico_id = t.id
        INNER JOIN baralhos b ON t.baralho_id = b.id
        WHERE pf.usuario_id = ? AND pf.total_erros > 0
        ORDER BY pf.total_erros DESC LIMIT 10
    """, (usuario_id,))
    ranking = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return ranking

# --- ROTAS DE ESCRITA (POST) ---
@app.post("/api/baralhos")
def criar_baralho(req: NovoBaralho):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO baralhos (usuario_id, nome) VALUES (?, ?)", (req.usuario_id, req.nome))
    baralho_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"status": "sucesso", "id": baralho_id, "nome": req.nome}

@app.post("/api/topicos")
def criar_topico(req: NovoTopico):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO topicos (baralho_id, nome) VALUES (?, ?)", (req.baralho_id, req.nome))
    topico_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"status": "sucesso", "id": topico_id, "nome": req.nome}

@app.post("/api/responder")
def registrar_resposta(req: RespostaReview):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM progresso_fichas WHERE ficha_id = ? AND usuario_id = ?", (req.ficha_id, req.usuario_id))
    progresso = cursor.fetchone()
    
    intervalo_atual, fator_atual, acertos, total_erros = progresso['intervalo_dias'], float(progresso['fator_facilidade']), progresso['acertos_consecutivos'], progresso['total_erros']
    
    if req.resposta == "errei":
        novo_acertos, novo_intervalo, novo_fator, xp_ganho, novo_total_erros = 0, 1, max(1.3, fator_atual - 0.2), 0, total_erros + 1
    else:
        novo_acertos, novo_fator, novo_total_erros = acertos + 1, fator_atual, total_erros
        novo_intervalo = 1 if novo_acertos == 1 else (6 if novo_acertos == 2 else round(intervalo_atual * novo_fator))
        xp_ganho = 10 

    proxima_data = (datetime.date.today() + datetime.timedelta(days=novo_intervalo)).isoformat()
    cursor.execute("UPDATE progresso_fichas SET acertos_consecutivos = ?, intervalo_dias = ?, fator_facilidade = ?, proxima_revisao = ?, total_erros = ? WHERE ficha_id = ? AND usuario_id = ?", (novo_acertos, novo_intervalo, novo_fator, proxima_data, novo_total_erros, req.ficha_id, req.usuario_id))
    if xp_ganho > 0: cursor.execute("UPDATE usuarios SET xp_total = xp_total + ? WHERE id = ?", (xp_ganho, req.usuario_id))
    conn.commit()
    conn.close()
    return {"status": "sucesso"}

@app.post("/api/fichas")
def criar_ficha(req: NovaFicha):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO fichas (topico_id, frente, verso) VALUES (?, ?, ?)", (req.topico_id, req.frente, req.verso))
    ficha_id = cursor.lastrowid
    cursor.execute("INSERT INTO progresso_fichas (ficha_id, usuario_id, proxima_revisao) VALUES (?, ?, ?)", (ficha_id, req.usuario_id, datetime.date.today().isoformat()))
    conn.commit()
    conn.close()
    return {"status": "sucesso"}

@app.post("/api/fichas/lote")
def criar_fichas_lote(req: LoteFichas):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    hoje = datetime.date.today().isoformat()
    for f in req.fichas:
        cursor.execute("INSERT INTO fichas (topico_id, frente, verso) VALUES (?, ?, ?)", (req.topico_id, f['frente'], f['verso']))
        ficha_id = cursor.lastrowid
        cursor.execute("INSERT INTO progresso_fichas (ficha_id, usuario_id, proxima_revisao) VALUES (?, ?, ?)", (ficha_id, req.usuario_id, hoje))
    conn.commit()
    conn.close()
    return {"status": "sucesso", "quantidade": len(req.fichas)}
