"""
demo.py
Ponto de entrada da versão de demonstração do sistema.

Roda o mesmo `app.py`, só que com o modo demonstração já ligado: dados
fictícios, sem login e com a faixa de aviso no topo.

Existe para que publicar a vitrine não dependa de configurar nada no
painel do Streamlit Community Cloud. Lá, o app de demonstração aponta
para este arquivo em "Main file path" e os Secrets ficam vazios — sem
variável para esquecer, sem credencial para colar errado. O caminho para
os dados do restaurante simplesmente não existe neste processo.

Rodar localmente:

    streamlit run demo.py
"""

import os
import runpy
from pathlib import Path

# Precisa vir antes de qualquer import de database: é na importação dele
# que o caminho do banco é decidido.
os.environ["MODO_DEMO"] = "1"

APP = Path(__file__).parent / "app.py"

runpy.run_path(str(APP), run_name="__main__")
