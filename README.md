# CLI de Testes E2E com orquestração AWS Step Functions e IA na geração de cenários para sistemas na AWS

Esta ferramenta é uma Command-Line Interface (CLI) projetada para simplificar e acelerar o processo de testes End-to-End (E2E) orquestrados com AWS Step Functions para sistemas em microsserviços AWS.

Utilizando o poder de modelos de linguagem (LLMs) como GPT, Gemini e Llama, a CLI pode **gerar automaticamente cenários de teste**, permitindo que as equipes de desenvolvimento se concentrem na lógica de negócios em vez de na criação manual e repetitiva de testes.

## Principais Funcionalidades

- **Geração de Testes com IA**: Analisa o código-fonte do seu projeto (Lambdas, SAM templates, etc.) para gerar cenários de teste relevantes, incluindo casos de sucesso e de falha.
- **Execução de Testes na Nuvem**: Executa os cenários de teste diretamente contra as State Machines implantadas na sua conta AWS.
- **Modo Interativo**: Uma interface amigável para selecionar suítes e cenários de teste para execução.
- **Execução Paralela**: Roda múltiplos testes simultaneamente para acelerar o feedback.
- **Suporte a Múltiplos Provedores de IA**: Compatível com OpenAI, Google Gemini e Groq.

## Estrutura do Projeto de Testes

A CLI opera sobre uma estrutura de diretórios padronizada. Todos os testes devem residir no diretório `tests/`.

O nome de cada subdiretório dentro de `tests/` deve corresponder **exatamente** ao nome da State Machine na AWS que ele testa.

```
meu-projeto/
├── tests/
│   ├── MinhaPrimeiraStateMachine/  <-- Nome da suíte (e da State Machine)
│   │   └── cases/                  <-- Diretório para os cenários
│   │       ├── cenario_sucesso.json
│   │       └── cenario_falha_input_invalido.json
│   │
│   └── OutraStateMachine/
│       └── cases/
│           ├── caso_borda_1.json
│           └── ...
│
├── cli.py
├── config.yaml
└── ... (código fonte do seu projeto SAM)
```

### Formato do Arquivo de Cenário (`.json`)

Cada arquivo de cenário é um JSON que define o input do teste e, opcionalmente, o resultado esperado.

```json
{
  "description": "Um resumo claro do que este cenário testa.",
  "input": {
    "userId": "123",
    "productId": "abc",
    "quantity": 2
  },
  "expected": {
    "statusCode": 400
  }
}
```

## Instalação e Configuração

### 1. Pré-requisitos

- Python 3.8+
- Conta AWS com credenciais configuradas localmente (via `aws configure` ou variáveis de ambiente).
- SAM CLI (para implantar seu projeto serverless).

### 2. Instalação das Dependências

Clone o repositório e instale as bibliotecas Python necessárias. É recomendado usar um ambiente virtual.

```bash
git clone <url-do-seu-repositorio>
cd <nome-do-repositorio>
python -m venv .venv
source .venv/bin/activate  # No Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configuração da IA

Crie um arquivo `config.yaml` na raiz do projeto para configurar as chaves de API dos provedores de IA.

```yaml
# Define qual provedor usar se nenhum for especificado com a flag --provider
default_provider: openai

providers:
  # Configuração para a API da OpenAI
  openai:
    # A chave pode ser colocada aqui ou lida da variável de ambiente OPENAI_API_KEY
    api_key: "sk-proj-xxxxxxxxxxx"

  # Configuração para a API do Google Gemini
  gemini:
    # A chave pode ser obtida no Google AI Studio e lida da variável de ambiente GOOGLE_API_KEY
    api_key: "xxxxxxxxxxx"
  
  # Configuração para a API da Groq (Llama)
  groq:
    api_key: "gsk_xxxxxxxxxx"

  # Configuração para a API da Anthropic (Claude)
  claude:
    api_key: "xxxxxxxxxxx"
```

## Como Usar a CLI

### `generate`: Gerar Cenários de Teste

Este comando usa a IA para criar arquivos de cenário `.json` com base no código do seu projeto.

```bash
# Exibe comandos disponíveis
python cli.py

# Gera testes para um projeto em um diretório específico
python cli.py generate path/to/your/sam-project

# Usa o modo interativo para selecionar quais arquivos incluir no contexto da IA
python cli.py generate path/to/your/sam-project --interactive

# Especifica um provedor de IA diferente do padrão
python cli.py generate path/to/your/sam-project --provider gemini
```

Os cenários gerados serão salvos em `tests/NOME_DA_STATE_MACHINE_NA_AWS/cases/`.

### `run`: Executar Testes

Este comando executa os testes definidos nos arquivos `.json` contra as State Machines na AWS.

```bash
# Executa todas as suítes de teste em todos os cenários
python cli.py run

# Executa todos as suítes de testes em todos os cenários em paralelo para maior velocidade
python cli.py run --parallel

# Executa uma suíte específica (ex: para a State Machine "ProcessOrderFlow")
python cli.py run ProcessOrderFlow

# Executa um cenário específico dentro de uma suíte específica
python cli.py run ProcessOrderFlow --scenario cenario_sucesso

# Inicia o modo interativo para selecionar o que executar
python cli.py run --interactive
```

> É possível combinar diferentes tags como `--paralel` e `--interactive` no mesmo comando

### `list`: Listar Suítes e Cenários

Mostra uma lista de todas as suítes e cenários de teste disponíveis.

```bash
python cli.py list
```

**Exemplo de Saída:**
```
Suítes e cenários de teste disponíveis:
Suite: MinhaPrimeiraStateMachine (Alvo SFN: MinhaPrimeiraStateMachine)
  - cenario_sucesso
  - cenario_falha_input_invalido
Suite: OutraStateMachine (Alvo SFN: OutraStateMachine)
  - caso_borda_1
```

## Contribuição

Contribuições são bem-vindas! Sinta-se à vontade para abrir uma issue ou enviar um Pull Request.

1.  Faça um Fork do projeto.
2.  Crie uma branch para sua feature (`git checkout -b feature/nova-feature`).
3.  Faça o commit de suas mudanças (`git commit -m 'Adiciona nova feature'`).
4.  Faça o push para a branch (`git push origin feature/nova-feature`).
5.  Abra um Pull Request.