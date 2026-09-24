"""
backup_nuvem.py
Copia todas as tabelas do banco configurado para um arquivo JSON local.

Serve para guardar o estado do banco real antes de uma mudança grande
(reimportar a ficha técnica, zerar dados). Só lê: não altera nada no banco.

    python backup_nuvem.py

Gera `backup-nuvem-AAAAMMDD-HHMMSS.json` na pasta do projeto, que o
.gitignore mantém fora do git. É o mesmo formato dos backups anteriores:
um dicionário {tabela: [linhas]}.
"""

import datetime
import json
import re
from pathlib import Path

import database

# As tabelas saem do próprio esquema, para que uma tabela nova entre no
# backup sem ninguém lembrar de acrescentá-la aqui.
TABELAS = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", database.ESQUEMA)


def main():
    print(f"Banco: {database.descricao_do_backend()}")
    conn = database.get_connection()
    dados = {}
    for tabela in TABELAS:
        # O esquema do código pode estar à frente do banco: uma tabela nova
        # só é criada quando o app novo abre pela primeira vez. Ela ainda
        # não tem dado nenhum, então fica de fora do backup em vez de
        # derrubá-lo. O rollback limpa a transação que o Postgres abortou.
        try:
            linhas = conn.execute(f"SELECT * FROM {tabela}").fetchall()
        except Exception:
            conn.rollback()
            print(f"  {tabela}: ainda não existe neste banco (pulada)")
            continue
        dados[tabela] = [dict(linha) for linha in linhas]
        print(f"  {tabela}: {len(linhas)}")
    conn.close()

    carimbo = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = Path(__file__).parent / f"backup-nuvem-{carimbo}.json"
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
    print(f"Backup gravado em {destino}")


if __name__ == "__main__":
    main()
