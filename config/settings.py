import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Centraliza as configurações do projeto, variáveis de ambiente e caminhos.
    """
    
    #  Caminhos do Projeto 

    PROJECT_ROOT: Path = Path(__file__).parent.parent
    
    DATA_DIR: Path = PROJECT_ROOT / "data"
    IMG_DIR: Path = PROJECT_ROOT / "img"
    LOG_DIR: Path = PROJECT_ROOT / "logs"
    DOCS_DIR: Path = PROJECT_ROOT / "docs"

    #  Caminhos de Arquivos Específicos 
    DB_PATH: Path = DATA_DIR / "srag_data.db"
    DICIONARIO_DADOS_PATH: Path = DATA_DIR / "dicionario_dados.json"
    
    #  Credenciais (Carregadas automaticamente do .env) 
    OPENAI_API_KEY: str
    TAVILY_API_KEY: str

    class Config:
        # Define que as variáveis serão lidas do arquivo .env na raiz
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore" # Ignora variáveis extras no .env que não estejam listadas aqui

# Instância global para ser importada em outros arquivos
settings = Settings()

# Garante que os diretórios fundamentais existam antes de qualquer coisa
os.makedirs(settings.DATA_DIR, exist_ok=True)
os.makedirs(settings.IMG_DIR, exist_ok=True)
os.makedirs(settings.LOG_DIR, exist_ok=True)