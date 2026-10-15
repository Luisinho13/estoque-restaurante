"""
bot_compras.py
Calcula a previsão de demanda e a sugestão de compra da semana e manda
para o WhatsApp pelo CallMeBot.

Roda sozinho toda segunda às 13h pelo GitHub Actions
(.github/workflows/sugestao-compra.yml), mas também à mão:

    python bot_compras.py            # calcula e manda
    python bot_compras.py --previa   # só mostra a mensagem, não manda
    python bot_compras.py --dias 4   # compra para 4 dias em vez de 7

Variáveis de ambiente:

    DATABASE_URL        o Postgres do restaurante (no Actions, um secret)
    CALLMEBOT_TELEFONE  o número que recebe, com DDI: +5511999998888
    CALLMEBOT_CHAVE     a apikey que o bot do CallMeBot devolveu

Recusa mandar a partir de um SQLite: sem DATABASE_URL, o `database.py`
cai no arquivo local, e o restaurante receberia uma lista calculada sobre
um banco vazio, sem nenhum erro. Mesma regra do app: fallback calado, não.
"""

import argparse
import os
import sys

import database
import sugestao_compra


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--previa", action="store_true", help="só mostra, não manda")
    parser.add_argument("--dias", type=int, default=sugestao_compra.DIAS_A_COBRIR,
                        help="quantos dias a compra cobre (padrão 7)")
    parser.add_argument("--semanas", type=int, default=sugestao_compra.SEMANAS_DE_HISTORICO,
                        help="quantas semanas de venda a previsão olha (padrão 4)")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"Banco: {database.descricao_do_backend()}")
    if not args.previa and database.backend() != "postgres":
        sys.exit("Sem DATABASE_URL: a sugestão sairia de um banco local. Nada foi enviado.")

    sugestao = sugestao_compra.calcular(args.dias, args.semanas)
    texto = sugestao_compra.mensagem(sugestao)
    print(texto)
    print(f"\n{len(sugestao['itens'])} item(ns) para comprar.")

    if args.previa:
        return
    telefone = os.environ.get("CALLMEBOT_TELEFONE", "").strip()
    chave = os.environ.get("CALLMEBOT_CHAVE", "").strip()
    if not telefone or not chave:
        sys.exit("Faltam CALLMEBOT_TELEFONE e CALLMEBOT_CHAVE. Nada foi enviado.")
    enviadas = sugestao_compra.enviar_whatsapp(texto, telefone, chave)
    print(f"Enviado para o WhatsApp em {enviadas} mensagem(ns).")


if __name__ == "__main__":
    main()
