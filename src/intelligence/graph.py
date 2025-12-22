import logging
from typing import Literal

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode

from config.settings import settings
from config.prompts import SYSTEM_PROMPT_REPORT
from src.intelligence.state import AgentState
from src.intelligence.tools import ToolFactory

logger = logging.getLogger(__name__)

def get_agent_graph():
    """
    Constrói e compila o Grafo de Estado (StateGraph) que orquestra o fluxo do Agente.
    Define os nós de raciocínio, execução de ferramentas e geração de relatório.
    """
    
    # 1. Inicialização de Ferramentas e Modelo
    sql_tool = ToolFactory.create_sql_tool()
    rag_tool = ToolFactory.create_news_rag_tool()
    available_tools = [sql_tool, rag_tool]

    # Configuração do modelo LLM otimizado para orquestração
    llm = ChatOpenAI(
        model="gpt-4o", 
        temperature=0, 
        api_key=settings.OPENAI_API_KEY
    )
    
    # Vincula as ferramentas ao modelo para que ele saiba que pode utilizá-las
    llm_with_tools = llm.bind_tools(available_tools)

    # 2. Definição dos Nós do Grafo

    def agent_reasoning_node(state: AgentState):
        """
        Nó Central: O modelo analisa o histórico de mensagens e decide o próximo passo
        (chamar uma ferramenta ou finalizar o raciocínio).
        """
        messages = state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def report_generation_node(state: AgentState):
        """
        Nó Final: Consolida as informações coletadas e gera o texto final.
        Insere uma SystemMessage no início do contexto para definir a persona técnica
        e as regras de formatação do relatório.
        """
        logger.info("Iniciando a síntese do relatório final...")
        messages = state["messages"]
        
        # Define a instrução de sistema (Persona e Formato)
        system_instruction = SystemMessage(content=SYSTEM_PROMPT_REPORT)
        
        # Constrói o contexto final: Instrução de Sistema + Histórico da Conversa
        # A instrução vem primeiro para garantir prioridade na definição do comportamento
        final_context = [system_instruction] + messages
        
        # Invoca o modelo sem ferramentas, focado apenas na geração de texto
        response = llm.invoke(final_context)
        return {"messages": [response]}

    def router(state: AgentState) -> Literal["tools_execution", "final_report"]:
        """
        Lógica de Roteamento: Verifica a saída do modelo.
        Se houver solicitação de ferramentas (tool_calls), encaminha para execução.
        Caso contrário, encaminha para a geração do relatório final.
        """
        last_message = state["messages"][-1]
        
        if last_message.tool_calls:
            return "tools_execution"
        return "final_report"

    # 3. Construção do Workflow
    workflow = StateGraph(AgentState)

    # Adiciona os nós ao grafo
    workflow.add_node("agent_brain", agent_reasoning_node)
    workflow.add_node("tools_execution", ToolNode(available_tools))
    workflow.add_node("final_report", report_generation_node)

    # Define o ponto de entrada
    workflow.add_edge(START, "agent_brain")

    # Define as transições condicionais baseadas no router
    workflow.add_conditional_edges(
        "agent_brain",
        router,
        {
            "tools_execution": "tools_execution",
            "final_report": "final_report"
        }
    )

    # Define o ciclo de retorno: após executar uma ferramenta, volta para o cérebro
    workflow.add_edge("tools_execution", "agent_brain")

    # Define o encerramento do fluxo
    workflow.add_edge("final_report", END)

    # Compila o grafo para execução
    return workflow.compile()