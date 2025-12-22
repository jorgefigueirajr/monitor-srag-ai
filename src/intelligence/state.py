from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """
    Define a estrutura de dados (State) que trafega pelo grafo do agente.
    
    Atributos:
        messages: Lista acumulativa de mensagens (Human, AI, Tool).
                  O reducer 'add_messages' garante que novas mensagens sejam
                  anexadas ao histórico existente, mantendo o contexto.
    """
    messages: Annotated[list, add_messages]