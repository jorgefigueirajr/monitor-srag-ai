import sqlite3
import logging
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

class ChartGenerator:
    """
    Responsável pela criação determinística de gráficos estáticos para o relatório.
    Gera visualizações de séries temporais (Diário e Mensal) salvando-as como imagens.
    """

    def __init__(self):
        self.db_path = settings.DB_PATH
        self.img_dir = settings.IMG_DIR
        # Configuração estética do Seaborn
        sns.set_theme(style="whitegrid")

    def _get_max_date(self, conn: sqlite3.Connection) -> str:
        """
        Recupera a data mais recente registrada no banco para usar como âncora temporal.
        Evita erros ao rodar o projeto em datas futuras onde não há dados.
        """
        try:
            query = "SELECT MAX(data_sintomas) FROM casos_srag;"
            max_date = pd.read_sql_query(query, conn).iloc[0, 0]
            if not max_date:
                raise ValueError("Banco de dados vazio ou sem datas de sintomas.")
            return max_date
        except Exception as e:
            logger.error(f"Erro ao buscar data de referência: {e}")
            raise

    def _plot_and_save(self, df: pd.DataFrame, x_col: str, y_col: str, title: str, filename: str):
        """
        Método genérico para plotagem e salvamento de gráficos de linha.
        """
        if df.empty:
            logger.warning(f"DataFrame vazio para o gráfico '{title}'. Imagem não será gerada.")
            return

        plt.figure(figsize=(10, 5))
        
        # Plotagem da linha com marcadores
        ax = sns.lineplot(data=df, x=x_col, y=y_col, marker='o', linewidth=2.5, color="#2E86C1")
        
        # Títulos e Labels
        plt.title(title, fontsize=14, fontweight='bold', pad=15)
        plt.xlabel("Data de Referência", fontsize=10)
        plt.ylabel("Total de Casos", fontsize=10)
        
        # Rotação do eixo X para datas não sobreporem
        plt.xticks(rotation=45, ha='right')
        
        # Ajuste de layout e salvamento
        plt.tight_layout()
        save_path = self.img_dir / filename
        plt.savefig(save_path, dpi=100)
        plt.close()
        
        logger.info(f"Gráfico gerado e salvo: {save_path.name}")

    def generate_charts(self):
        """
        Executa a geração dos dois gráficos obrigatórios:
        1. Evolução Diária (Últimos 30 dias a partir do último registro)
        2. Evolução Mensal (Últimos 12 meses a partir do último registro)
        """
        if not self.db_path.exists():
            logger.error("Banco de dados não encontrado para geração de gráficos.")
            return

        try:
            with sqlite3.connect(self.db_path) as conn:
                ref_date = self._get_max_date(conn)
                logger.info(f"Gerando gráficos com base na data de referência: {ref_date}")

                # Gráfico 1: Diário (30 Dias)
                query_daily = f"""
                    SELECT data_sintomas, COUNT(*) as total
                    FROM casos_srag
                    WHERE data_sintomas BETWEEN DATE('{ref_date}', '-29 days') AND '{ref_date}'
                    GROUP BY data_sintomas
                    ORDER BY data_sintomas;
                """
                df_daily = pd.read_sql_query(query_daily, conn, parse_dates=['data_sintomas'])
                self._plot_and_save(
                    df_daily, 'data_sintomas', 'total', 
                    'Casos Diários de SRAG (Últimos 30 dias)', 
                    'grafico_diario.png'
                )

                # Gráfico 2: Mensal (12 Meses)
                query_monthly = f"""
                    SELECT STRFTIME('%Y-%m', data_sintomas) as mes, COUNT(*) as total
                    FROM casos_srag
                    WHERE data_sintomas BETWEEN DATE('{ref_date}', '-12 months') AND '{ref_date}'
                    GROUP BY mes
                    ORDER BY mes;
                """
                df_monthly = pd.read_sql_query(query_monthly, conn)
                self._plot_and_save(
                    df_monthly, 'mes', 'total', 
                    'Casos Mensais de SRAG (Últimos 12 meses)', 
                    'grafico_mensal.png'
                )

        except Exception as e:
            logger.error(f"Falha crítica na geração de gráficos: {e}")
            raise

# Função utilitária para acesso externo
def run_plotter():
    generator = ChartGenerator()
    generator.generate_charts()