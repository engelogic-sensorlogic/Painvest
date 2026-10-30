"""Acesso ao banco SQLite local (pasta data/ ao lado do executável)."""
import json
import os
import sqlite3
import sys


def app_dir():
    """Pasta do aplicativo: ao lado do .exe quando empacotado, ou do código-fonte."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(rel):
    """Caminho de recursos empacotados (templates/static)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


DATA_DIR = os.path.join(app_dir(), "data")
DB_PATH = os.path.join(DATA_DIR, "painvest.db")
SCHEMA_VERSION = 1

# Campos e tipos (fonte única para formulário, backup e banco)
CAMPOS_AUTO = {
    "nome": "TEXT", "preco": "REAL", "market_cap": "REAL", "vol_medio_usd": "REAL",
    "dy_bruto": "REAL", "frequencia": "TEXT", "pagamentos_12m": "INTEGER",
    "meses_pagamento": "TEXT", "cagr_div_5a": "REAL", "anos_sem_corte": "INTEGER",
    "anos_listada": "REAL", "atualizado_em": "TEXT", "erro_coleta": "TEXT",
    # Calculados a partir da SEC (EDGAR XBRL)
    "payout_calc": "REAL", "div_ebitda_calc": "REAL", "ffo_positivo_calc": "INTEGER",
    "ffo_anos_cresc_calc": "INTEGER", "ffo_ano_ref": "INTEGER", "sec_detalhe": "TEXT",
    "sec_atualizado_em": "TEXT", "sec_erro": "TEXT",
}
CAMPOS_MANUAIS = {
    "setor": "TEXT", "affo_positivo_5a": "INTEGER", "affo_anos_crescimento": "INTEGER",
    "payout_affo": "REAL", "div_liq_ebitda": "REAL", "rating": "TEXT",
    "maior_inquilino_pct": "REAL", "p_affo_atual": "REAL", "p_affo_media5a": "REAL",
    "frequencia_manual": "TEXT", "anos_sem_corte_manual": "INTEGER", "notas": "TEXT",
}
TODOS_CAMPOS = {**CAMPOS_AUTO, **CAMPOS_MANUAIS}


def _colunas_sql():
    return ",\n  ".join(f"{k} {v}" for k, v in TODOS_CAMPOS.items())


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS reits (
  ticker TEXT PRIMARY KEY,
  {_colunas_sql()}
);
CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
"""


def conectar(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def inicializar(path=None):
    with conectar(path) as con:
        con.executescript(SCHEMA)
        # Migração simples: acrescenta colunas que faltarem
        existentes = {r["name"] for r in con.execute("PRAGMA table_info(reits)")}
        for campo, tipo in TODOS_CAMPOS.items():
            if campo not in existentes:
                con.execute(f"ALTER TABLE reits ADD COLUMN {campo} {tipo}")
        con.execute("INSERT OR IGNORE INTO config VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))


# ---------- REITs ----------
def listar(path=None):
    with conectar(path) as con:
        return [dict(r) for r in con.execute("SELECT * FROM reits ORDER BY ticker")]


def obter(ticker, path=None):
    with conectar(path) as con:
        r = con.execute("SELECT * FROM reits WHERE ticker=?", (ticker.upper(),)).fetchone()
        return dict(r) if r else None


def salvar(ticker, dados, path=None):
    """Insere ou atualiza apenas os campos informados."""
    ticker = ticker.upper().strip()
    dados = {k: v for k, v in dados.items() if k in TODOS_CAMPOS}
    with conectar(path) as con:
        con.execute("INSERT OR IGNORE INTO reits (ticker) VALUES (?)", (ticker,))
        if dados:
            sets = ", ".join(f"{k}=?" for k in dados)
            con.execute(f"UPDATE reits SET {sets} WHERE ticker=?", (*dados.values(), ticker))


def excluir(ticker, path=None):
    with conectar(path) as con:
        con.execute("DELETE FROM reits WHERE ticker=?", (ticker.upper(),))


# ---------- Configuração ----------
def ler_config(padrao, path=None):
    with conectar(path) as con:
        r = con.execute("SELECT valor FROM config WHERE chave='metodologia'").fetchone()
    cfg = json.loads(json.dumps(padrao))  # cópia profunda
    if r:
        salvo = json.loads(r["valor"])
        for k, v in salvo.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def gravar_config(cfg, path=None):
    with conectar(path) as con:
        con.execute("INSERT OR REPLACE INTO config VALUES ('metodologia', ?)",
                    (json.dumps(cfg, ensure_ascii=False),))


# ---------- Backup ----------
def exportar_json(path=None):
    with conectar(path) as con:
        cfg = con.execute("SELECT chave, valor FROM config").fetchall()
    return {
        "app": "Painvest",
        "schema_version": SCHEMA_VERSION,
        "reits": listar(path),
        "config": {r["chave"]: r["valor"] for r in cfg},
    }


def importar_json(pacote, path=None):
    """Restaura um backup (substitui todos os dados atuais)."""
    if pacote.get("app") != "Painvest" or "reits" not in pacote:
        raise ValueError("Arquivo não é um backup válido do Painvest.")
    inicializar(path)
    with conectar(path) as con:
        con.execute("DELETE FROM reits")
        con.execute("DELETE FROM config")
        for chave, valor in pacote.get("config", {}).items():
            con.execute("INSERT OR REPLACE INTO config VALUES (?, ?)", (chave, valor))
    for r in pacote["reits"]:
        salvar(r["ticker"], {k: v for k, v in r.items() if k != "ticker"}, path)
    return len(pacote["reits"])
