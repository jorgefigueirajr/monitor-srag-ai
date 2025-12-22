import json
import re
import sqlite3
import logging
import pandas as pd
from typing import List

from config.settings import settings

logger = logging.getLogger(__name__)

class DataProcessor:
    """
    Gerencia o pipeline de tratamento de dados: carregamento, normalização,
    aplicação de regras de negócio e persistência em banco de dados otimizado.
    """

    def __init__(self):
        self.data_dir = settings.DATA_DIR
        self.db_path = settings.DB_PATH
        self.json_path = settings.DICIONARIO_DADOS_PATH
        
        # Lista de colunas estritamente necessárias para a análise.
        # Carregar apenas estas colunas economiza memória e evita processamento inútil.
        self.load_columns = [
            "DT_SIN_PRI", "SG_UF", "CS_SEXO", "DT_NASC",
            "UTI", "DT_ENTUTI", "DT_SAIDUTI", "EVOLUCAO",
            "VACINA_COV", "DOSE_1_COV",
            # Colunas auxiliares para mapeamento do dicionário de dados
            "DT_NOTIFIC", "ID_MUNICIP", "CO_MUN_NOT" 
        ]

    def _get_parquet_files(self) -> List[str]:
        """Identifica arquivos de dados brutos no diretório."""
        return [str(f) for f in self.data_dir.glob("*.parquet")]

    def _normalize_name(self, name: str) -> str:
        """
        Padroniza nomes de colunas removendo caracteres especiais e sufixos.
        Ex: 'Município (IBGE)' -> 'municipio'
        """
        name = name.lower().replace('(ibge)', '').replace('(cnes)', '').replace('código', '')
        name = re.sub(r'^\d+-?\s*', '', name)
        name = re.sub(r'[^a-z0-9\s_]', '', name)
        return re.sub(r'\s+', '_', name).strip('_')

    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Renomeia as colunas técnicas (siglas) para nomes legíveis utilizando
        o mapeamento do arquivo JSON de dicionário de dados.
        """
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data_dict = json.load(f).get('dicionario_de_dados_sivep_gripe', [])

        rename_map = {}
        for item in data_dict:
            old_names_str = item.get("nome_coluna_dbf")
            if not old_names_str or old_names_str == 'N/A':
                continue

            new_base_name = self._normalize_name(item["nome_campo_ficha"])
            old_names = [n.strip() for n in old_names_str.split(' OU ')]

            for old_name in old_names:
                if old_name in df.columns:
                    # Resolve conflitos de nomes (código vs descrição)
                    final_name = new_base_name
                    if len(old_names) > 1:
                        final_name += "_codigo" if old_name.startswith("CO_") else "_nome"
                    rename_map[old_name] = final_name

        return df.rename(columns=rename_map)

    def _transform_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica limpeza, tipagem e seleção final dos dados.
        Reduz o dataset apenas ao essencial para otimizar o consumo de tokens da IA.
        """
        logger.info("Executando transformações e regras de negócio...")

        # 1. Cálculo de Idade (Data Sintomas - Data Nascimento)
        df['idade'] = (
            pd.to_datetime(df['data_de_1s_sintomas'], errors='coerce', format='mixed') -
            pd.to_datetime(df['data_de_nascimento'], errors='coerce', format='mixed')
        ).dt.days / 365.25

        # 2. Normalização de Valores Categóricos (Legibilidade)
        df['evolucao'] = df['evoluo_do_caso'].map({'1': 'Cura', '1.0': 'Cura', '2': 'Óbito', '2.0': 'Óbito'})
        df['uti'] = df['internado_em_uti'].map({'1': 'Sim', '1.0': 'Sim', '2': 'Não', '2.0': 'Não'})
        df['vacina_covid'] = df['recebeu_vacina_covid19'].map({'1': 'Sim', '2': 'Não'})
        df['sexo'] = df['sexo'].map({'M': 'Masculino', 'F': 'Feminino', 'I': 'Ignorado'})

        # 3. Filtragem Vertical (Seleção de Colunas)
        # Mantemos apenas as colunas mapeadas abaixo para criar um schema de banco enxuto.
        # Isso é crucial para que o Agente SQL não exceda o limite de tokens.
        selected_columns_map = {
            'data_de_1s_sintomas': 'data_sintomas',
            'uf_residncia': 'uf',
            'sexo': 'sexo',
            'idade': 'idade',
            'uti': 'uti',
            'data_da_entrada_na_uti': 'data_entrada_uti',
            'data_da_sada_da_uti': 'data_saida_uti',
            'evolucao': 'evolucao',
            'vacina_covid': 'vacina_covid',
            'data_1_dose_da_vacina_covid19': 'data_dose1_covid'
        }

        # Aplica renomeação final e descarta o resto
        df = df.rename(columns=selected_columns_map)
        cols_to_keep = list(selected_columns_map.values())
        df = df[cols_to_keep]

        # 4. Limpeza de Dados Inconsistentes
        # Remove registros que não possuem informações para análise temporal ou geográfica
        critical_cols = ["data_sintomas", "uf", "idade", "evolucao", "uti"]
        df = df.dropna(subset=critical_cols)
        df['idade'] = df['idade'].astype(int)

        # 5. Padronização de Datas
        # Converte para string ISO (YYYY-MM-DD), formato padrão para o SQLite
        date_cols = ["data_sintomas", "data_entrada_uti", "data_saida_uti", "data_dose1_covid"]
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')

        return df

    def run(self):
        """Orquestra o fluxo completo: Leitura -> Renomeação -> Transformação -> Carga."""
        files = self._get_parquet_files()
        
        dfs = []
        for f in files:
            try:
                # carrega apenas as colunas de interesse 
                try:
                    dfs.append(pd.read_parquet(f, columns=[c for c in self.load_columns]))
                except:
                    # Fallback: carrega tudo se houver divergência de schema entre anos
                    dfs.append(pd.read_parquet(f)) 
            except Exception as e:
                logger.error(f"Erro ao ler arquivo {f}: {e}")
        
        if not dfs:
            logger.warning("Nenhum dado carregado. Verifique os arquivos Parquet.")
            return

        # Concatena todos os anos em um único DataFrame
        df_raw = pd.concat(dfs, ignore_index=True).astype(str)
        
        # Executa o pipeline
        df_renamed = self._rename_columns(df_raw)
        df_final = self._transform_data(df_renamed)

        # Persistência no SQLite (Substitui tabela existente)
        with sqlite3.connect(self.db_path) as conn:
            df_final.to_sql("casos_srag", conn, if_exists="replace", index=False)
        
        logger.info(f"Pipeline concluído. Banco gerado com {len(df_final):,} registros e {len(df_final.columns)} colunas.")

def run_processor():
    DataProcessor().run()