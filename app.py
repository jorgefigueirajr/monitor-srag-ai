import streamlit as st
import sqlite3
import pandas as pd
from langchain_core.messages import HumanMessage

from config.settings import settings
from src.etl.pipeline import verify_and_run_etl
from src.visualization.plotter import run_plotter
from src.intelligence.graph import get_agent_graph

# Configuração da página
st.set_page_config(
    page_title="Monitor de Vigilância SRAG",
    page_icon="🏥",
    layout="wide"
)

def get_latest_db_date():
    """
    Consulta o banco de dados para recuperar a data mais recente registrada.
    Isso permite alinhar o 'relógio' do Agente com a realidade dos dados.
    Evitando que gerar análises "rasas ou genéricas" na condição de não
    termos dados mais recentes com data atual real.
    """
    try:
        # Conecta ao banco em modo somente leitura
        conn = sqlite3.connect(f"file:{settings.DB_PATH}?mode=ro", uri=True)
        
        # Pega a maior data da coluna principal
        query = "SELECT MAX(data_sintomas) FROM casos_srag"
        max_date = pd.read_sql_query(query, conn).iloc[0, 0]
        
        conn.close()
        
        # Se o banco estiver vazio ou retornar None, usa fallback
        return max_date if max_date else "2024-01-01"
    except Exception as e:
        # Em caso de erro (ex: banco não existe ainda), retorna data segura
        return "2024-01-01"

def main():
    st.title("Sistema de Vigilância em Saúde | Monitoramento de SRAG")
    st.markdown("---")

    if st.button("Iniciar Análise Completa", type="primary"):
        
        with st.status("Executando pipeline de inteligência...", expanded=True) as status:
            
            # 1. Camada de Dados (ETL)
            st.write("🔄 Verificando e atualizando dados...")
            try:
                verify_and_run_etl()
                # Recupera a data REAL após a atualização do banco
                data_referencia = get_latest_db_date()
                st.write(f"✅ Dados sincronizados até: **{data_referencia}**")
            except Exception as e:
                st.error(f"Erro no ETL: {e}")
                status.update(state="error")
                return

            # 2. Camada de Visualização
            st.write("📊 Gerando gráficos...")
            try:
                run_plotter()
            except Exception as e:
                st.error(f"Erro nos gráficos: {e}")
                status.update(state="error")
                return

            # 3. Camada de Inteligência (Agente AI)
            st.write("🤖 Inicializando Agente Especialista...")
            try:
                agent = get_agent_graph()
                
                prompt_dinamico = f"""
                DATA DE REFERÊNCIA DO SISTEMA ("HOJE"): {data_referencia}
                
                Instruções Obrigatórias:
                1. Considere que hoje é estritamente {data_referencia}.
                2. Use a ferramenta SQL para calcular métricas dos "últimos 30 dias" 
                   contados a partir de {data_referencia} para trás.
                3. Busque notícias contextualizadas com o ano de {data_referencia[:4]}.
                4. Gere o relatório preenchendo as métricas com os valores exatos encontrados.
                """
                
                # Invocação do Agente
                result = agent.invoke({"messages": [HumanMessage(content=prompt_dinamico)]})
                final_response = result["messages"][-1].content
                
                st.write("✅ Relatório gerado com sucesso.")
            except Exception as e:
                st.error(f"Falha no Agente AI: {e}")
                status.update(state="error")
                return

            status.update(label="Processamento Concluído", state="complete", expanded=False)

        # --- Exibição dos Resultados ---
        st.divider()
        col_text, col_viz = st.columns([1.2, 0.8])

        with col_text:
            st.subheader("Relatório Técnico")
            st.markdown(final_response)

        with col_viz:
            st.subheader("Painel Visual")
            img_daily = settings.IMG_DIR / "grafico_diario.png"
            img_monthly = settings.IMG_DIR / "grafico_mensal.png"

            if img_daily.exists():
                st.image(str(img_daily), caption="Evolução Diária (Recente)", use_container_width=True)
            if img_monthly.exists():
                st.image(str(img_monthly), caption="Evolução Mensal (Histórico)", use_container_width=True)

if __name__ == "__main__":
    main()