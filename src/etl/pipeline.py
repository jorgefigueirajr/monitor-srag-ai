import logging
from typing import List

from config.settings import settings
from src.etl.downloader import run_downloader
from src.etl.processor import run_processor

logger = logging.getLogger(__name__)

def verify_and_run_etl(force_rebuild: bool = False):
    """
    Verifica a integridade do ambiente de dados (ETL).
    
    Lógica de Execução:
    1. Verifica se o banco de dados SQLite já existe.
    2. Se não existir (ou force_rebuild=True), verifica se há arquivos .parquet brutos.
    3. Se não houver arquivos brutos, inicia o Download.
    4. Executa o Processador para limpar os dados e popular o banco.
    """
    
    db_exists = settings.DB_PATH.exists()
    
    if db_exists and not force_rebuild:
        logger.info("Verificação ETL: Banco de dados encontrado e pronto para uso.")
        return

    logger.info("Verificação ETL: Banco de dados ausente ou reconstrução forçada iniciada.")

    # Passo 1: Garantir arquivos brutos (Download)
    # Verifica se existem arquivos .parquet na pasta de dados
    parquet_files = list(settings.DATA_DIR.glob("*.parquet"))
    
    if not parquet_files:
        logger.warning("Arquivos brutos (.parquet) não encontrados localmente.")
        logger.info("Disparando módulo de download (OpenDataSUS)...")
        try:
            run_downloader()
        except Exception as e:
            logger.critical(f"Falha crítica no download dos dados: {e}")
            raise
    else:
        logger.info(f"{len(parquet_files)} arquivos brutos encontrados. Etapa de download ignorada.")

    # Passo 2: Processamento e Carga (ETL)
    logger.info("Disparando módulo de processamento (Limpeza -> SQLite)...")
    try:
        run_processor()
    except Exception as e:
        logger.critical(f"Falha crítica no processamento dos dados: {e}")
        raise
    
    logger.info("Pipeline ETL finalizado com sucesso. Ambiente pronto.")