import streamlit as st
import pandas as pd
import bcrypt
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Portal RH (Nuvem)", page_icon="☁️", layout="wide")

# =========================================================
# CONFIGURAÇÃO DO GOOGLE (SHEETS + DRIVE)
# =========================================================

# ID da Pasta no Google Drive onde os PDFs serão salvos
# (Pegue isso no link da pasta: drive.google.com/drive/folders/SEU_ID_AQUI)
PASTA_DRIVE_ID = "https://drive.google.com/drive/u/1/folders/1alcj0QrGah7w5h6eFgf4FoCf-2GJEEi_"  # <--- ALTERE AQUI!!!
NOME_PLANILHA = "SistemaRH_DB"

# Escopos de permissão
ESCOPOS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def conectar_google():
    """Conecta ao Google Sheets e Drive usando o JSON"""
    if os.path.exists("service_account.json"):
        creds = Credentials.from_service_account_file("service_account.json", scopes=ESCOPOS)
    else:
        # Para quando estiver no Streamlit Cloud (usando Secrets)
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=ESCOPOS)
    
    # Cliente Sheets
    client_sheets = gspread.authorize(creds)
    sheet = client_sheets.open(NOME_PLANILHA)
    
    # Cliente Drive
    service_drive = build('drive', 'v3', credentials=creds)
    
    return sheet, service_drivestreamlit

# --- FUNÇÕES DE BANCO DE DADOS (GOOGLE SHEETS) ---

def buscar_usuario(cpf_login):
    sheet, _ = conectar_google()
    worksheet = sheet.worksheet("Usuarios")
    
    # Pega todos os registros (é rápido para listas pequenas/médias)
    # Se crescer muito, usar find() do gspread é melhor
    todos = worksheet.get_all_records()
    df = pd.DataFrame(todos)
    
    # Converte CPF para string para garantir comparação
    df['CPF'] = df['CPF'].astype(str)
    usuario = df[df['CPF'] == str(cpf_login)]
    
    if not usuario.empty:
        return usuario.iloc[0].to_dict()
    return None

def criar_usuario_sheets(cpf, nome, senha):
    sheet, _ = conectar_google()
    worksheet = sheet.worksheet("Usuarios")
    
    # Verifica duplicidade
    todos_cpfs = [str(x) for x in worksheet.col_values(1)] # Coluna A é CPF
    if str(cpf) in todos_cpfs:
        return False, "CPF já cadastrado."
    
    hashed = bcrypt.hashpw(str(senha).encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Adiciona linha: CPF, Nome, Senha, IsAdmin (FALSE)
    worksheet.append_row([str(cpf), nome, hashed, "FALSE"])
    return True, "Sucesso"

def salvar_documento_nuvem(arquivo, cpf_dono, mes_ano):
    sheet, drive = conectar_google()
    
    try:
        # 1. UPLOAD PARA O GOOGLE DRIVE
        file_metadata = {
            'name': f"{cpf_dono}_{mes_ano.replace('/','-')}.pdf",
            'parents': [PASTA_DRIVE_ID]
        }
        
        # Prepara o arquivo da memória para envio
        media = MediaIoBaseUpload(arquivo, mimetype='application/pdf')
        
        file = drive.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        file_id = file.get('id')
        
        # 2. REGISTRO NO GOOGLE SHEETS
        ws_docs = sheet.worksheet("Documentos")
        # Colunas: Filename, MesAno, CPF_Dono, FileID
        ws_docs.append_row([arquivo.name, mes_ano, str(cpf_dono), file_id])
        
        return True, "Arquivo salvo na nuvem!"
        
    except Exception as e:
        return False, str(e)

def listar_docs_usuario(cpf):
    sheet, _ = conectar_google()
    ws_docs = sheet.worksheet("Documentos")
    todos = ws_docs.get_all_records()
    df = pd.DataFrame(todos)
    
    if df.empty: return []
    
    df['CPF_Dono'] = df['CPF_Dono'].astype(str)
    meus_docs = df[df['CPF_Dono'] == str(cpf)]
    return meus_docs.to_dict('records')

def baixar_arquivo_drive(file_id):
    _, drive = conectar_google()
    try:
        request = drive.files().get_media(fileId=file_id)
        file_io = io.BytesIO()
        downloader = request.execute() # Retorna o conteúdo binário
        return request.execute()
    except:
        # Método alternativo de download via API
        file_content = drive.files().get_media(fileId=file_id).execute()
        return file_content

# --- LÓGICA DO APP (INTERFACE) ---
import os
hide_streamlit_style = """<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;}</style>"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

if 'logado' not in st.session_state:
    st.session_state['logado'] = False
    st.session_state['usuario'] = None

# TELA DE LOGIN
if not st.session_state['logado']:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("☁️ Portal RH Nuvem")
        with st.form("login"):
            cpf = st.text_input("CPF")
            senha = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar"):
                try:
                    user_data = buscar_usuario(cpf)
                    if user_data:
                        # Verifica senha
                        stored_hash = user_data['Senha']
                        if bcrypt.checkpw(senha.encode('utf-8'), stored_hash.encode('utf-8')):
                            # Login sucesso
                            is_admin = str(user_data['IsAdmin']).upper() == "TRUE"
                            st.session_state['logado'] = True
                            st.session_state['usuario'] = {
                                'nome': user_data['Nome'], 
                                'cpf': user_data['CPF'], 
                                'admin': is_admin
                            }
                            st.rerun()
                        else:
                            st.error("Senha incorreta.")
                    else:
                        st.error("Usuário não encontrado.")
                except Exception as e:
                    st.error(f"Erro de conexão com Google: {e}")
                    st.info("Verifique se o service_account.json está na pasta e se a planilha foi compartilhada.")

# ÁREA LOGADA
else:
    dados = st.session_state['usuario']
    with st.sidebar:
        st.write(f"Olá, **{dados['nome']}**")
        if st.button("Sair"):
            st.session_state['logado'] = False
            st.rerun()

    # --- ADMIN ---
    if dados['admin']:
        st.title("Painel Gestão (Conectado ao Drive)")
        tab1, tab2 = st.tabs(["🚀 Enviar PDF", "➕ Criar Usuário"])
        
        with tab1:
            cpf_alvo = st.text_input("CPF do Funcionário")
            mes = st.text_input("Referência (Ex: Janeiro/2025)")
            arq = st.file_uploader("PDF", type="pdf")
            if st.button("Enviar para Nuvem"):
                if cpf_alvo and mes and arq:
                    ok, msg = salvar_documento_nuvem(arq, cpf_alvo, mes)
                    if ok: st.success(msg)
                    else: st.error(msg)
        
        with tab2:
            n_cpf = st.text_input("Novo CPF")
            n_nome = st.text_input("Nome")
            n_senha = st.text_input("Senha")
            if st.button("Cadastrar no Sheets"):
                ok, msg = criar_usuario_sheets(n_cpf, n_nome, n_senha)
                if ok: st.success(msg)
                else: st.error(msg)

    # --- SERVIDOR ---
    else:
        st.header("Meus Documentos (Vêm do Drive)")
        docs = listar_docs_usuario(dados['cpf'])
        
        if docs:
            for d in docs:
                col1, col2 = st.columns([4,1])
                with col1:
                    st.write(f"📄 **{d['MesAno']}** ({d['Filename']})")
                with col2:
                    # O download direto do drive via Streamlit é pesado.
                    # Aqui vamos gerar o link direto para abrir no Drive, que é mais rápido e seguro.
                    link_drive = f"https://drive.google.com/file/d/{d['FileID']}/view?usp=sharing"
                    st.link_button("Abrir PDF", link_drive)
                st.divider()
        else:
            st.info("Nenhum documento encontrado.")