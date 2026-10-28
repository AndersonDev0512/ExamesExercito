# Exames Exército

Painel em Streamlit para acompanhar exames, agenda, valores, prestadores e pendências da inspeção militar.

## Estrutura
- `app.py`: aplicação principal
- `data.json`: dados editáveis do painel
- `requirements.txt`: dependências
- `.streamlit/config.toml`: tema branco
- `.gitignore`: arquivos ignorados pelo Git

## Executar localmente
```powershell
cd C:\Users\anderson.rodrigues\Documents\GitHub\ExamesExercito
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Publicar no Streamlit Community Cloud
1. Envie o repositório ao GitHub.
2. Acesse https://share.streamlit.io.
3. Selecione o repositório e a branch principal.
4. Informe `app.py` como Main file path.
5. Clique em Deploy.

## Atualizar dados
Edite `data.json`. A aplicação carrega agenda, exames, contatos e valores desse arquivo.

## IFRAME
A aba `Painel digital` permite informar uma URL e abri-la dentro do painel. Alguns sites bloqueiam iframe; nesse caso, use o botão para abrir em nova guia.
