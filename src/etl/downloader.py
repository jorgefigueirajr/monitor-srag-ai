import asyncio
import aiohttp
import aiofiles
import logging
import json
from bs4 import BeautifulSoup
from pathlib import Path
from typing import List, Optional

from config.settings import settings

# Configuração de log para este módulo
logger = logging.getLogger(__name__)

class DataDownloader:
    """
    Gerencia o processo de download assíncrono de arquivos do Portal de Dados Abertos do SUS.
    Identifica os arquivos de dados mais recentes disponíveis e realiza o download paralelo 
    para o diretório local configurado.
    """

    BASE_URL = "https://dadosabertos.saude.gov.br"
    DATASET_URL = f"{BASE_URL}/dataset/srag-2021-a-2024"
    MAX_CONCURRENT_DOWNLOADS = 5

    def __init__(self):
        self.download_dir = settings.DATA_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def _fetch_html(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        """Realiza uma requisição GET e retorna o conteúdo HTML."""
        try:
            async with session.get(url, timeout=30) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as e:
            logger.error(f"Erro ao acessar URL {url}: {e}")
            return None

    async def _extract_parquet_links_from_json(self, session: aiohttp.ClientSession) -> List[str]:
        """
        Extrai links diretos de arquivos .parquet lendo o script __NEXT_DATA__ do portal.
        """
        html = await self._fetch_html(session, self.DATASET_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        
        # O portal usa Next.js, os dados estão em um JSON dentro desta tag script
        next_data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        
        if not next_data_tag:
            logger.error("Tag __NEXT_DATA__ não encontrada. A estrutura do site pode ter mudado.")
            return []

        try:
            data = json.loads(next_data_tag.string)
            # Navega no JSON: props -> pageProps -> resources
            resources = data.get("props", {}).get("pageProps", {}).get("resources", [])
            
            parquet_links = []
            
            for res in resources:
                res_format = res.get("format", "").upper()
                res_url = res.get("url", "")
                
                # Filtra apenas arquivos Parquet (pelo formato ou extensão)
                if res_format == "PARQUET" or res_url.lower().endswith(".parquet"):
                    parquet_links.append(res_url)
            
            logger.info(f"Total de arquivos .parquet identificados via JSON: {len(parquet_links)}")
            return parquet_links

        except json.JSONDecodeError:
            logger.error("Erro ao decodificar o JSON do portal.")
            return []
        except Exception as e:
            logger.error(f"Erro inesperado ao extrair links: {e}")
            return []

    async def _download_file(self, session: aiohttp.ClientSession, url: str):
        """Baixa um único arquivo e salva no diretório de dados."""
        # Extrai o nome do arquivo da URL (ex: INFLUD21-26-06-2025.parquet)
        filename = url.split("/")[-1]
        filepath = self.download_dir / filename

        if filepath.exists():
            logger.info(f"Arquivo já existente, ignorando download: {filename}")
            return

        try:
            logger.info(f"Iniciando download: {filename}")
            async with session.get(url) as response:
                response.raise_for_status()
                async with aiofiles.open(filepath, "wb") as f:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        await f.write(chunk)
            logger.info(f"Download concluído: {filename}")
        except Exception as e:
            logger.error(f"Falha ao baixar {filename}: {e}")

    async def run(self):
        """Executa o fluxo completo de extração."""
        logger.info(f"Iniciando extração de dados em: {self.DATASET_URL}")
        
        connector = aiohttp.TCPConnector(limit=self.MAX_CONCURRENT_DOWNLOADS)
        async with aiohttp.ClientSession(connector=connector) as session:
    
            download_links = await self._extract_parquet_links_from_json(session)
            
            if not download_links:
                logger.warning("Nenhum arquivo .parquet encontrado. Verifique a URL ou o seletor.")
                return

            tasks = [self._download_file(session, link) for link in download_links]
            await asyncio.gather(*tasks)
            
        logger.info("Processo de extração finalizado.")

# Função de entrada para execução direta ou importação
def run_downloader():
    downloader = DataDownloader()
    asyncio.run(downloader.run())