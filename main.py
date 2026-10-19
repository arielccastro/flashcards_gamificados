from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import datetime

app = FastAPI(title="App Concurseiro - Flashcards")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "flashcards.db"

class RespostaReview(BaseModel):
    usuario_id: int
    ficha_id: int
    resposta: str

class NovaFicha(BaseModel):
    frente: str
    verso: str
    baralho_id: int
    usuario_id: int = 1

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, xp_total INTEGER DEFAULT 0, ofensiva_atual INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS baralhos (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER, nome TEXT);
    CREATE TABLE IF NOT EXISTS fichas (id INTEGER PRIMARY KEY AUTOINCREMENT, baralho_id INTEGER, frente TEXT, verso TEXT);
    CREATE TABLE IF NOT EXISTS progresso_fichas (id INTEGER PRIMARY KEY AUTOINCREMENT, ficha_id INTEGER, usuario_id INTEGER, proxima_revisao DATE, intervalo_dias INTEGER DEFAULT 0, fator_facilidade REAL DEFAULT 2.5, acertos_consecutivos INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_revisao ON progresso_fichas (usuario_id, proxima_revisao, intervalo_dias);
    """)
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (nome) VALUES ('Concurseiro Alfa')")
        # Criando duas matérias de exemplo
        cursor.execute("INSERT INTO baralhos (usuario_id, nome) VALUES (1, 'Direito Constitucional')")
        cursor.execute("INSERT INTO baralhos (usuario_id, nome) VALUES (1, 'Direito Administrativo')")
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/baralhos/{usuario_id}")
def get_baralhos(usuario_id: int):
    """Retorna as matérias criadas pelo usuário."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome FROM baralhos WHERE usuario_id = ?", (usuario_id,))
    baralhos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return baralhos

@app.get("/api/revisao/{usuario_id}/{baralho_id}")
def get_fila_revisao(usuario_id: int, baralho_id: int):
    """Busca as cartas apenas da matéria escolhida."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    hoje = datetime.date.today().isoformat()
    cursor.execute("""
        SELECT f.id AS ficha_id, f.frente, f.verso, pf.intervalo_dias
        FROM fichas f
        INNER JOIN progresso_fichas pf ON f.id = pf.ficha_id
        WHERE pf.usuario_id = ? AND f.baralho_id = ? AND pf.proxima_revisao <= ?
        ORDER BY pf.proxima_revisao ASC, pf.intervalo_dias ASC
        LIMIT 20
    """, (usuario_id, baralho_id, hoje))
    cartas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"quantidade": len(cartas), "cartas": cartas}

@app.post("/api/responder")
def registrar_resposta(req: RespostaReview):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM progresso_fichas WHERE ficha_id = ? AND usuario_id = ?", (req.ficha_id, req.usuario_id))
    progresso = cursor.fetchone()
    
    intervalo_atual, fator_atual, acertos = progresso['intervalo_dias'], float(progresso['fator_facilidade']), progresso['acertos_consecutivos']
    
    if req.resposta == "errei":
        novo_acertos, novo_intervalo, novo_fator, xp_ganho = 0, 1, max(1.3, fator_atual - 0.2), 0
    else:
        novo_acertos, novo_fator = acertos + 1, fator_atual
        novo_intervalo = 1 if novo_acertos == 1 else (6 if novo_acertos == 2 else round(intervalo_atual * novo_fator))
        xp_ganho = 10 

    proxima_data = (datetime.date.today() + datetime.timedelta(days=novo_intervalo)).isoformat()
    cursor.execute("UPDATE progresso_fichas SET acertos_consecutivos = ?, intervalo_dias = ?, fator_facilidade = ?, proxima_revisao = ? WHERE ficha_id = ? AND usuario_id = ?", (novo_acertos, novo_intervalo, novo_fator, proxima_data, req.ficha_id, req.usuario_id))
    if xp_ganho > 0: cursor.execute("UPDATE usuarios SET xp_total = xp_total + ? WHERE id = ?", (xp_ganho, req.usuario_id))
    conn.commit()
    conn.close()
    return {"status": "sucesso"}

@app.post("/api/fichas")
def criar_ficha(req: NovaFicha):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO fichas (baralho_id, frente, verso) VALUES (?, ?, ?)", (req.baralho_id, req.frente, req.verso))
    ficha_id = cursor.lastrowid
    hoje = datetime.date.today().isoformat()
    cursor.execute("INSERT INTO progresso_fichas (ficha_id, usuario_id, proxima_revisao) VALUES (?, ?, ?)", (ficha_id, req.usuario_id, hoje))
    conn.commit()
    conn.close()
    return {"status": "sucesso"}
