import asyncio
import aiohttp
import aiofiles
import logging
from bs4 import BeautifulSoup
from pathlib import Path
from typing import List, Optional

from config.settings import settings

# Configuração de log para este módulo
logger = logging.getLogger(__name__)

class DataDownloader:
    """
    Gerencia o processo de download assíncrono de arquivos do OpenDataSUS.
    Responsável por varrer a página do dataset, identificar arquivos .parquet
    e baixá-los para o diretório local configurado.
    """

    BASE_URL = "https://opendatasus.saude.gov.br"
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

    async def _get_resource_pages(self, session: aiohttp.ClientSession) -> List[str]:
        """Identifica os links das páginas de recursos dentro do dataset principal."""
        html = await self._fetch_html(session, self.DATASET_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        resource_links = []
        
        # Seleciona elementos <a> com a classe 'heading' que contêm href
        for anchor in soup.select("a.heading[href]"):
            href = anchor["href"]
            full_link = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            resource_links.append(full_link)

        logger.info(f"Encontradas {len(resource_links)} páginas de recursos.")
        return resource_links

    async def _extract_parquet_links(self, session: aiohttp.ClientSession, resource_urls: List[str]) -> List[str]:
        """Percorre as páginas de recursos e extrai os links diretos para arquivos .parquet."""
        parquet_links = []
        
        for url in resource_urls:
            html = await self._fetch_html(session, url)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                if href.lower().endswith(".parquet"):
                    full_link = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    parquet_links.append(full_link)
        
        logger.info(f"Total de arquivos .parquet identificados: {len(parquet_links)}")
        return parquet_links

    async def _download_file(self, session: aiohttp.ClientSession, url: str):
        """Baixa um único arquivo e salva no diretório de dados."""
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
        logger.info("Iniciando processo de extração de dados do OpenDataSUS.")
        
        connector = aiohttp.TCPConnector(limit=self.MAX_CONCURRENT_DOWNLOADS)
        async with aiohttp.ClientSession(connector=connector) as session:
            resource_pages = await self._get_resource_pages(session)
            if not resource_pages:
                logger.warning("Nenhuma página de recurso encontrada. Abortando.")
                return

            download_links = await self._extract_parquet_links(session, resource_pages)
            if not download_links:
                logger.warning("Nenhum arquivo .parquet encontrado para download.")
                return

            tasks = [self._download_file(session, link) for link in download_links]
            await asyncio.gather(*tasks)
            
        logger.info("Processo de extração finalizado.")

# Função de entrada para execução direta ou importação
def run_downloader():
    downloader = DataDownloader()
    asyncio.run(downloader.run())