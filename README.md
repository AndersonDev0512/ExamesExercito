# Exames Exército

Painel em Streamlit para acompanhar os exames exigidos pelo edital da inspeção de saúde militar: agenda, status, prazos, riscos de atraso, valores, contatos e o anexo de exames do edital. Tema claro e layout pensado para uso no celular.

## Estrutura

```
ExamesExercito/
├── .streamlit/
│   └── config.toml      # tema claro e configurações do servidor
├── .gitignore
├── app.py               # interface e funções reutilizáveis
├── static/              # páginas do Anexo C do edital (imagens)
├── data.json            # todos os dados do painel
├── README.md
└── requirements.txt
```

## Abas

| Aba | O que mostra |
|---|---|
| **Visão geral** | Prazo interno (10/11), conferência (11/11), apresentação (12/11), subtotal, agendados, pendentes, resultados recebidos, risco de atraso, próximos compromissos, alertas, prioridades e resumo financeiro |
| **Agenda** | Calendário visual até a apresentação e compromissos em ordem cronológica, com horário, clínica, final do contato, endereço, valor, status, orientações e documentos. Filtros por data, clínica, status e tipo |
| **Exames** | Tabela com status e risco coloridos, pesquisa em todas as colunas (sem diferenciar acentos), filtros por status e grupo, e a separação entre SUS e particular |
| **Financeiro** | Total geral, confirmado, orçamentos, estimado, pago, não pago, valor por exame e por grupo, comparativo entre clínicas e economia |
| **Contatos** | Nome com os 4 últimos dígitos, telefone e botão de WhatsApp (`https://wa.me/55NUMERO`), somente para números cadastrados |
| **Edital PDF** | Páginas do Anexo C do edital (relação de exames, laudos e avaliações) em imagem, legíveis no celular |
| **Configurações** | Atualiza status, datas, valor, pagamento, protocolo, código de acompanhamento e observações; adiciona compromissos; exporta e importa o JSON |

## Regras de cálculo

- **Pacotes não são somados duas vezes.** Exames com `"pacote"` preenchido aparecem com o valor individual, mas o total usa só o valor do pacote. Exemplo: os R$ 1.260,00 da Ultramedical já incluem radiologia, ultrassom das mamas, ECG e colpocitológico.
- **Ficam fora do total:** exames com status `SUS`, `Descartado` ou `Não exigido`.
- **Tipos de valor (`valor_tipo`):**
  - `confirmado`, `orcamento` e `estimado` entram no total;
  - `opcao` (por exemplo, a panorâmica da FAODO) só entra quando escolhida;
  - `a_cotar` indica que ainda não há valor.
- **Risco de atraso:**
  - *Crítico:* resultado previsto ou compromisso marcado depois do prazo interno;
  - *Alto:* exame ainda não agendado faltando `dias_alerta` dias ou menos;
  - *Atenção:* prazo do resultado ainda não confirmado.
- **Ordem de chegada:** exames com `"ordem_chegada": true` e sem compromisso na agenda aparecem na agenda no dia atual; o resultado previsto é hoje + `prazo_dias_uteis` (média), e o app mostra a data-limite para fazê-los.
- **Validação dos dados:** o app confere datas, horários, status, referências entre contatos/pacotes/agenda, se o final do contato bate com o telefone, se a soma dos itens bate com o valor do pacote e se os subtotais fecham com o total. Erros e avisos aparecem no topo da página.

## Executar localmente (Windows / PowerShell)

```powershell
cd C:\Users\anderson.rodrigues\Documents\GitHub\ExamesExercito
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

O navegador abre em `http://localhost:8501`. Para simular outra data nos alertas, acrescente `?hoje=05/11/2026` à URL.

## Publicar no Streamlit Community Cloud

1. Envie o repositório ao GitHub (`git push`).
2. Acesse https://share.streamlit.io e clique em **Create app**.
3. Escolha o repositório `ExamesExercito`, a branch `master` e o arquivo principal `app.py`.
4. Em **Advanced settings**, selecione Python 3.11 ou 3.12.
5. Clique em **Deploy**. As dependências vêm do `requirements.txt` e o tema, do `.streamlit/config.toml`.

Cada `git push` na branch atualiza o app automaticamente.

## Atualizar os dados

**Os dados ficam em `data.json`.** No Streamlit Cloud, o disco é temporário: o que for gravado pelo app se perde quando ele reinicia ou é reimplantado. O fluxo recomendado é:

1. Faça as alterações na aba **Configurações**.
2. Clique em **Exportar JSON** (também disponível na barra lateral).
3. Substitua o `data.json` do repositório pelo arquivo baixado e faça commit/push.

Rodando localmente, o botão **Gravar no data.json** salva direto no arquivo.

### Formato principal do `data.json`

- `meta`: candidata, cidade, `prazo_resultados`, `conferencia`, `apresentacao`, `dias_alerta`.
- `contatos`: `id`, `categoria`, `nome`, `final` (4 últimos dígitos), `telefone` (ou `null` se não houver número completo), `valor`, `situacao`, `observacoes`.
- `pacotes`: orçamentos consolidados (`id`, `nome`, `contato`, `valor`, `valor_tipo`, `pago`).
- `agenda`: `data` (dd/mm/aaaa), `horario` (HH:MM), `tipo`, `contato`, `profissional`, `endereco`, `valor`, `exames` (ids), `orientacoes`, `documentos`.
- `exames`: `id`, `ordem`, `grupo`, `nome`, `exigencia`, `contato`, `valor`, `valor_tipo`, `pacote`, `prazo_resultado`, `status`, `pendencias`, `observacoes`, `pago`, `data_realizacao`, `data_resultado`, `protocolo`, `codigo_acompanhamento`.
- `comparativos`: opções de preço por categoria, com a escolhida.
- `documentos`: documentos exibidos na aba Edital PDF (`nome`, `descricao`, `imagens`).
- `prioridades`: lista exibida na Visão geral.

Status permitidos: Não iniciado, Em cotação, Aguardando resposta, Quase fechado, Escolhido, Fechado, Agendado, Realizado, Resultado recebido, Descartado, SUS, Não exigido.

## Edital PDF

As páginas do Anexo C ficam como imagens em `static/` e aparecem na aba **Edital PDF**. Para trocar ou acrescentar páginas, gere novas imagens (PNG) do PDF, coloque em `static/` e liste os caminhos em `documentos[].imagens` no `data.json`.

## Segurança

- Não coloque senhas, tokens ou segredos no repositório. Se precisar, use `.streamlit/secrets.toml`, que está no `.gitignore`.
- PDFs e planilhas (laudos, orçamentos) são ignorados pelo Git para não publicar documentos pessoais por engano.
- Se o repositório for público, lembre que `data.json` contém nome, telefones de prestadores e a agenda.
