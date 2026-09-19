"""
auth.py
Autenticação do sistema: cadastro e verificação de usuários.

A senha nunca é gravada em texto puro. Para cada usuário é sorteado um
salt e guardado o PBKDF2-SHA256 da senha com esse salt, o que torna
inútil um eventual vazamento do arquivo estoque.db.
"""

import datetime
import hashlib
import hmac
import os

from database import get_connection

ITERACOES = 200_000


def _hash_senha(senha: str, salt: bytes) -> str:
    """Devolve o hash PBKDF2-SHA256 da senha, em hexadecimal."""
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, ITERACOES).hex()


def cadastrar_usuario(usuario: str, senha: str):
    """Cadastra um novo usuário. Erra se o nome já existir."""
    salt = os.urandom(16)
    conn = get_connection()
    conn.execute(
        "INSERT INTO usuarios (usuario, senha_hash, salt, criado_em) VALUES (?, ?, ?, ?)",
        (
            usuario,
            _hash_senha(senha, salt),
            salt.hex(),
            datetime.date.today().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def alterar_senha(usuario: str, nova_senha: str) -> bool:
    """Troca a senha de um usuário existente. Retorna False se ele não existir."""
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


def verificar_login(usuario: str, senha: str) -> bool:
    """Confere usuário e senha. Retorna True só se os dois baterem."""
    conn = get_connection()
    dado = conn.execute(
        "SELECT senha_hash, salt FROM usuarios WHERE usuario = ?", (usuario,)
    ).fetchone()
    conn.close()
    if not dado:
        return False
    calculado = _hash_senha(senha, bytes.fromhex(dado["salt"]))
    # compare_digest evita que o tempo de resposta entregue quanto do hash bateu
    return hmac.compare_digest(calculado, dado["senha_hash"])


def existe_usuario(usuario: str) -> bool:
    conn = get_connection()
    dado = conn.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    conn.close()
    return dado is not None


def total_de_usuarios() -> int:
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"]
    conn.close()
    return total
