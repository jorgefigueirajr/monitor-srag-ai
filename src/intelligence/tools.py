import sqlite3
import logging
from typing import List, Dict

from langchain_core.tools import Tool
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent, SQLDatabaseToolkit
from langchain_community.tools import TavilySearchResults
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import settings

logger = logging.getLogger(__name__)

class ToolFactory:
    """
    Classe responsável por criar e configurar as ferramentas (Tools) que o Agente utilizará.
    Centraliza a lógica de conexão com serviços externos e implementação de RAG.
    """

    @staticmethod
    def _get_db_max_date(db_path: str) -> str:
        """
        Consulta auxiliar para obter a data máxima real dos dados.
        Isso impede alucinações temporais do modelo ao calcular "últimos 30 dias".
        """
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(data_sintomas) FROM casos_srag")
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
        except Exception as e:
            logger.warning(f"Não foi possível obter a data máxima do DB: {e}")
        
        return "data desconhecida"

    @staticmethod
    def _hybrid_search(query: str, raw_docs: List[Dict]) -> str:
        """
        Implementa estratégia de RAG Híbrido (Busca Semântica + Lexical).
        Combina FAISS (vetorial) com BM25 (palavra-chave) para melhor recuperação.
        """
        if not raw_docs:
            return "Nenhuma notícia encontrada."

        # 1. Preparação dos Documentos
        documents = [
            Document(page_content=d['content'], metadata={'source': d['url'], 'title': d['title']})
            for d in raw_docs if d.get('content')
        ]
        
        if not documents:
            return "Conteúdo das notícias vazio ou ilegível."

        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        chunks = splitter.split_documents(documents)

        if not chunks:
            return "Não foi possível segmentar o texto das notícias."

        # 2. Busca Semântica (Vetorial - Entendimento do Significado)
        try:
            embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
            vectorstore = FAISS.from_documents(chunks, embeddings)
            semantic_retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
            semantic_docs = semantic_retriever.invoke(query)
        except Exception as e:
            logger.error(f"Erro na busca semântica: {e}")
            semantic_docs = []

        # 3. Busca Lexical (BM25 - Termos Exatos)
        try:
            bm25_retriever = BM25Retriever.from_documents(chunks)
            bm25_retriever.k = 3
            lexical_docs = bm25_retriever.invoke(query)
        except Exception as e:
            logger.error(f"Erro na busca lexical: {e}")
            lexical_docs = []

        # 4. Fusão e Deduplicação
        # Prioriza documentos que apareceram em ambas as buscas ou os melhores de cada
        all_docs = semantic_docs + lexical_docs
        unique_docs = {doc.page_content: doc for doc in all_docs}.values()

        # Formatação do Contexto para o LLM
        context_str = "\n\n---\n\n".join(
            f"Fonte: {d.metadata.get('title')}\nConteúdo: {d.page_content}" 
            for d in unique_docs
        )
        return context_str

    @staticmethod
    def create_sql_tool() -> Tool:
        """
        Cria a ferramenta SQL com Guardrails (Segurança e Contexto Temporal).
        """
        if not settings.DB_PATH.exists():
             raise FileNotFoundError(f"Banco de dados não encontrado em: {settings.DB_PATH}")

        db = SQLDatabase.from_uri(f"sqlite:///{settings.DB_PATH}")
        llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=settings.OPENAI_API_KEY)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)

        # Contexto Temporal 
        max_date = ToolFactory._get_db_max_date(str(settings.DB_PATH))

        system_prompt = f"""
        Você é um especialista em SQL para dados de saúde pública (SRAG).
        
        GUARDRAILS DE SEGURANÇA E CONTEXTO:
        1. A data de referência ("hoje") para todos os cálculos é estritamente **{max_date}**. 
           - NUNCA use `now()` ou `CURRENT_DATE` do SQL, pois o banco é estático.
           - Se o usuário pedir "últimos 30 dias", calcule 30 dias antes de {max_date}.
        2. A tabela principal é `casos_srag`.
        3. PERMISSÃO SOMENTE LEITURA. Comandos de modificação (INSERT, DELETE, DROP) são PROIBIDOS.
        4. Retorne apenas o código SQL ou o resultado da query.
        """

        agent_executor = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            verbose=False,
            agent_type="openai-tools",
            prefix=system_prompt,
            handle_parsing_errors=True
        )

        return Tool(
            name="consultar_banco_sql",
            description="Use para obter métricas exatas, contagens e estatísticas do banco de dados.",
            func=lambda q: agent_executor.invoke({"input": q})['output']
        )

    @staticmethod
    def create_news_rag_tool() -> Tool:
        """
        Cria a ferramenta de pesquisa de notícias na web.
        """
        tavily = TavilySearchResults(
            max_results=5, 
            include_raw_content=True,
            tavily_api_key=settings.TAVILY_API_KEY
        )

        def search_process(query: str):
            logger.info(f"Executando busca de notícias para: {query}")
            try:
                raw_results = tavily.invoke(query)
                return ToolFactory._hybrid_search(query, raw_results)
            except Exception as e:
                logger.error(f"Erro na busca Tavily: {e}")
                return "Erro ao buscar contexto externo."

        return Tool(
            name="pesquisar_noticias_contexto",
            description="Use para buscar notícias recentes sobre saúde, SRAG e vacinação para contextualizar as métricas.",
            func=search_process
        )