from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import datetime
import os

app = FastAPI(title="App Concurseiro - Flashcards")

# Configuração para permitir o frontend acessar a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "flashcards.db"

# --- MODELOS DE DADOS (Pydantic) ---
class RespostaReview(BaseModel):
    usuario_id: int
    ficha_id: int
    resposta: str # 'acertei' ou 'errei'

# --- CONFIGURAÇÃO DO BANCO DE DADOS (SQLite) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT, xp_total INTEGER DEFAULT 0, ofensiva_atual INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS baralhos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER, nome TEXT
    );
    CREATE TABLE IF NOT EXISTS fichas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        baralho_id INTEGER, frente TEXT, verso TEXT
    );
    CREATE TABLE IF NOT EXISTS progresso_fichas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ficha_id INTEGER, usuario_id INTEGER,
        proxima_revisao DATE, intervalo_dias INTEGER DEFAULT 0,
        fator_facilidade REAL DEFAULT 2.5, acertos_consecutivos INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_revisao ON progresso_fichas (usuario_id, proxima_revisao, intervalo_dias);
    """)
    conn.commit()
    
    # Inserir dados de teste se o banco estiver vazio
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (nome) VALUES ('Concurseiro Alfa')")
        cursor.execute("INSERT INTO baralhos (usuario_id, nome) VALUES (1, 'Direito Constitucional')")
        fichas = [
            (1, "Qual o prazo decadencial para anular atos favoráveis?", "5 anos, salvo comprovada má-fé."),
            (1, "Quais são os fundamentos da República (Art. 1º)?", "SO-CI-DI-VA-PLU (Soberania, Cidadania, Dignidade, Valores sociais, Pluralismo)."),
            (1, "O que é Habeas Corpus?", "Remédio constitucional para proteger a liberdade de locomoção.")
        ]
        cursor.executemany("INSERT INTO fichas (baralho_id, frente, verso) VALUES (?, ?, ?)", fichas)
        
        # Cria o progresso zerado agendado para HOJE para as 3 cartas
        hoje = datetime.date.today().isoformat()
        cursor.executemany(
            "INSERT INTO progresso_fichas (ficha_id, usuario_id, proxima_revisao) VALUES (?, ?, ?)",
            [(1, 1, hoje), (2, 1, hoje), (3, 1, hoje)]
        )
    
    conn.commit()
    conn.close()

# --- ROTAS DA API ---

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/", response_class=HTMLResponse)
def read_root():
    # Serve o arquivo HTML diretamente
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/revisao/{usuario_id}")
def get_fila_revisao(usuario_id: int):
    """Busca as cartas agendadas para hoje ou atrasadas."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    hoje = datetime.date.today().isoformat()
    
    query = """
        SELECT f.id AS ficha_id, f.frente, f.verso, pf.intervalo_dias
        FROM fichas f
        INNER JOIN progresso_fichas pf ON f.id = pf.ficha_id
        WHERE pf.usuario_id = ? AND pf.proxima_revisao <= ?
        ORDER BY pf.proxima_revisao ASC, pf.intervalo_dias ASC
        LIMIT 20
    """
    cursor.execute(query, (usuario_id, hoje))
    cartas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"quantidade": len(cartas), "cartas": cartas}

@app.post("/api/responder")
def registrar_resposta(req: RespostaReview):
    """Aplica o Algoritmo SM-2 modificado e atualiza a carta."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM progresso_fichas WHERE ficha_id = ? AND usuario_id = ?", (req.ficha_id, req.usuario_id))
    progresso = cursor.fetchone()
    
    if not progresso:
        conn.close()
        raise HTTPException(status_code=404, detail="Progresso não encontrado")

    intervalo_atual = progresso['intervalo_dias']
    fator_atual = float(progresso['fator_facilidade'])
    acertos = progresso['acertos_consecutivos']
    
    # Lógica SM-2
    if req.resposta == "errei":
        novo_acertos = 0
        novo_intervalo = 1
        novo_fator = max(1.3, fator_atual - 0.2)
        xp_ganho = 0
    else: # acertei
        novo_acertos = acertos + 1
        novo_fator = fator_atual
        if novo_acertos == 1:
            novo_intervalo = 1
        elif novo_acertos == 2:
            novo_intervalo = 6
        else:
            novo_intervalo = round(intervalo_atual * novo_fator)
        xp_ganho = 10 # Gamificação: Ganha 10 XP por acerto

    hoje = datetime.date.today()
    proxima_data = (hoje + datetime.timedelta(days=novo_intervalo)).isoformat()

    # Atualiza Progresso da Ficha
    cursor.execute("""
        UPDATE progresso_fichas 
        SET acertos_consecutivos = ?, intervalo_dias = ?, fator_facilidade = ?, proxima_revisao = ?
        WHERE ficha_id = ? AND usuario_id = ?
    """, (novo_acertos, novo_intervalo, novo_fator, proxima_data, req.ficha_id, req.usuario_id))
    
    # Atualiza XP do Usuário (Gamificação)
    if xp_ganho > 0:
        cursor.execute("UPDATE usuarios SET xp_total = xp_total + ? WHERE id = ?", (xp_ganho, req.usuario_id))
        
    conn.commit()
    conn.close()
    
    return {"status": "sucesso", "proxima_revisao": proxima_data, "xp_ganho": xp_ganho}