
# Mini Market – Streamlit + SQLite

Primeira versão operacional do Mini Market para Team Building.

## 1. Instalação

```bash
pip install -r requirements.txt
```

## 2. Executar

```bash
streamlit run app.py
```

O arquivo `mini_market.db` será criado automaticamente.

## 3. O que esta versão já faz

- Grupos com saldo inicial e saldo atual
- Produtos com preço e estoque
- Carrinho
- Validação de saldo
- Validação de estoque
- Baixa de estoque
- Baixa de saldo
- Registro da compra
- Histórico
- Transação SQLite para evitar atualização parcial
- Tela administrativa básica

## 4. Próxima etapa

Substituir os dados de teste pela leitura das listas reais do SharePoint:

- Mini Market Groups
- Mini Market Team Building
- Mini Market Purchases

Depois podemos implementar:

- sincronização SharePoint → SQLite no início
- sincronização SQLite → SharePoint durante/depois da atividade
- e-mail automático para o administrador
- QR Code para acesso pelo celular
- modo administrador
- relatório Excel
- controle de início/fim da atividade
