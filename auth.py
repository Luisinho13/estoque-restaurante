"""
auth.py
Autenticação e controle de acesso do sistema.

Regras:
- A senha nunca é gravada em texto puro. Cada usuário tem um salt aleatório
  e o que fica no banco é o PBKDF2-SHA256 da senha com esse salt.
- Quem se cadastra entra como 'pendente' e não consegue usar o sistema até
  um admin aprovar. Isso é de propósito: o cadastro é aberto, a entrada não.
- Cada usuário aprovado enxerga só as áreas liberadas para ele. O admin
  enxerga tudo, sem depender da tabela de permissões.
"""

import datetime
import hashlib
import hmac
import os

from database import get_connection

ITERACOES = 200_000

# Áreas do app que podem ser liberadas por usuário. A chave é o que fica
# gravado na tabela permissoes; o valor é o que aparece na tela do admin.
AREAS = {
    "dashboard": "Dashboard",
    "painel": "Painel de Estoque",
    "insumos": "Insumos",
    "pratos": "Pratos",
    "ficha": "Ficha Técnica",
    "compra": "Lançar Compra",
    "nfe": "Importar Nota Fiscal",
    "zig": "Importar Vendas (PDV)",
    "venda": "Lançar Venda do Dia",
    "contagem": "Contagem Física",
}

# Sugestão de acesso para quem é aprovado sem nenhuma escolha explícita:
# só consulta, nada que altere o estoque.
AREAS_PADRAO = ["dashboard", "painel"]


# ---------- Senha ----------

def _hash_senha(senha: str, salt: bytes) -> str:
    """Devolve o hash PBKDF2-SHA256 da senha, em hexadecimal."""
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, ITERACOES).hex()


def alterar_senha(usuario: str, nova_senha: str) -> bool:
    """Troca a senha de um usuário. Retorna False se ele não existir."""
    salt = os.urandom(16)
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE usuarios SET senha_hash = ?, salt = ? WHERE usuario = ?",
        (_hash_senha(nova_senha, salt), salt.hex(), usuario),
    )
    conn.commit()
    alterou = cursor.rowcount > 0
    conn.close()
    return alterou


def autenticar(usuario: str, senha: str):
    """Confere usuário e senha.

    Retorna os dados do usuário (inclusive papel e status) quando a senha
    bate, ou None. Quem chama é que decide o que fazer com um 'pendente' —
    aqui só se responde se a senha está certa.
    """
    conn = get_connection()
    dado = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    conn.close()
    if not dado:
        return None
    calculado = _hash_senha(senha, bytes.fromhex(dado["salt"]))
    # compare_digest evita que o tempo de resposta entregue quanto do hash bateu
    if not hmac.compare_digest(calculado, dado["senha_hash"]):
        return None
    return dict(dado)


# ---------- Cadastro ----------

def cadastrar_usuario(usuario: str, senha: str, nome: str = None,
                      papel: str = "usuario", status: str = "pendente",
                      areas=None):
    """Cadastra um usuário. Erra se o nome de usuário já existir."""
    salt = os.urandom(16)
    conn = get_connection()
    # RETURNING no lugar de lastrowid, e ON CONFLICT no lugar de
    # INSERT OR IGNORE: os dois funcionam tanto no SQLite quanto no
    # Postgres, então a mesma consulta serve para local e nuvem.
    linha = conn.execute(
        """INSERT INTO usuarios (usuario, senha_hash, salt, criado_em, nome, papel, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           RETURNING id""",
        (
            usuario,
            _hash_senha(senha, salt),
            salt.hex(),
            datetime.date.today().isoformat(),
            nome,
            papel,
            status,
        ),
    ).fetchone()
    usuario_id = linha["id"]
    for area in areas or []:
        conn.execute(
            """INSERT INTO permissoes (usuario_id, area) VALUES (?, ?)
               ON CONFLICT (usuario_id, area) DO NOTHING""",
            (usuario_id, area),
        )
    conn.commit()
    conn.close()


def existe_usuario(usuario: str) -> bool:
    conn = get_connection()
    dado = conn.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    conn.close()
    return dado is not None


def buscar_usuario(usuario: str):
    conn = get_connection()
    dado = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    conn.close()
    return dict(dado) if dado else None


def listar_usuarios(status: str = None):
    """Lista usuários, opcionalmente filtrando por status, com suas áreas."""
    conn = get_connection()
    if status:
        linhas = conn.execute(
            "SELECT * FROM usuarios WHERE status = ? ORDER BY criado_em, usuario", (status,)
        ).fetchall()
    else:
        linhas = conn.execute(
            "SELECT * FROM usuarios ORDER BY papel DESC, usuario"
        ).fetchall()

    resultado = []
    for linha in linhas:
        dado = dict(linha)
        areas = conn.execute(
            "SELECT area FROM permissoes WHERE usuario_id = ?", (dado["id"],)
        ).fetchall()
        dado["areas"] = [a["area"] for a in areas]
        resultado.append(dado)
    conn.close()
    return resultado


def total_de_usuarios() -> int:
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"]
    conn.close()
    return total


def total_pendentes() -> int:
    conn = get_connection()
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM usuarios WHERE status = 'pendente'"
    ).fetchone()["n"]
    conn.close()
    return total


# ---------- Aprovação e acessos ----------

def aprovar_usuario(usuario: str, decidido_por: str, areas=None):
    """Libera o acesso de um usuário e define as áreas que ele vai enxergar."""
    conn = get_connection()
    conn.execute(
        """UPDATE usuarios
           SET status = 'aprovado', decidido_em = ?, decidido_por = ?
           WHERE usuario = ?""",
        (datetime.date.today().isoformat(), decidido_por, usuario),
    )
    conn.commit()
    conn.close()
    definir_permissoes(usuario, areas if areas is not None else AREAS_PADRAO)


def recusar_usuario(usuario: str, decidido_por: str):
    """Recusa um cadastro. O usuário continua no banco, mas sem entrar."""
    conn = get_connection()
    conn.execute(
        """UPDATE usuarios
           SET status = 'recusado', decidido_em = ?, decidido_por = ?
           WHERE usuario = ?""",
        (datetime.date.today().isoformat(), decidido_por, usuario),
    )
    conn.commit()
    conn.close()


def definir_papel(usuario: str, papel: str):
    """Promove a admin ou rebaixa para usuário comum."""
    conn = get_connection()
    conn.execute("UPDATE usuarios SET papel = ? WHERE usuario = ?", (papel, usuario))
    conn.commit()
    conn.close()


def definir_permissoes(usuario: str, areas):
    """Substitui as áreas liberadas de um usuário pela lista informada."""
    conn = get_connection()
    dado = conn.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    if not dado:
        conn.close()
        raise ValueError(f"Usuário '{usuario}' não encontrado.")

    conn.execute("DELETE FROM permissoes WHERE usuario_id = ?", (dado["id"],))
    for area in areas:
        if area not in AREAS:
            continue
        conn.execute(
            "INSERT INTO permissoes (usuario_id, area) VALUES (?, ?)", (dado["id"], area)
        )
    conn.commit()
    conn.close()


def permissoes_de(usuario: str) -> set:
    """Áreas que o usuário enxerga. Admin aprovado enxerga todas."""
    dado = buscar_usuario(usuario)
    if not dado or dado["status"] != "aprovado":
        return set()
    if dado["papel"] == "admin":
        return set(AREAS)

    conn = get_connection()
    areas = conn.execute(
        "SELECT area FROM permissoes WHERE usuario_id = ?", (dado["id"],)
    ).fetchall()
    conn.close()
    return {a["area"] for a in areas}


def pode_acessar(usuario: str, area: str) -> bool:
    return area in permissoes_de(usuario)


def excluir_usuario(usuario: str) -> bool:
    """Apaga o usuário e as permissões dele. É definitivo."""
    conn = get_connection()
    dado = conn.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    if not dado:
        conn.close()
        return False
    conn.execute("DELETE FROM permissoes WHERE usuario_id = ?", (dado["id"],))
    conn.execute("DELETE FROM usuarios WHERE id = ?", (dado["id"],))
    conn.commit()
    conn.close()
    return True


def total_de_admins_aprovados() -> int:
    """Usado para impedir que o sistema fique sem nenhum admin."""
    conn = get_connection()
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM usuarios WHERE papel = 'admin' AND status = 'aprovado'"
    ).fetchone()["n"]
    conn.close()
    return total
