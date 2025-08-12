import click
from typing import List, Dict
from botocore.exceptions import ClientError
import boto3
import json
import os
import time
import uuid
import sys
import yaml
from pathlib import Path
from datetime import datetime

# --- CLI Settings ---
# Root directory for all test suites.
TEST_SUITES_DIR = "tests"

# CLI log file name (for internal debugging).
CLI_LOG_FILE = "cli_debug.log"

# AI Configuration file.
CONFIG_FILE = "config.yaml"

# Initialize AWS clients.
try:
    stepfunctions_client = boto3.client('stepfunctions')
    cloudwatch_logs_client = boto3.client('logs')
except Exception as e:
    click.echo(f"Erro ao inicializar clientes AWS. Verifique suas credenciais e configuração. Detalhe: {e}", err=True)
    sys.exit(1)

# --- Helper Functions ---

def log_message(message, level="INFO", err=False):
    """Escreve mensagens no console e em um arquivo de log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{level}] {message}"
    
    # Print to console (stderr for errors).
    click.echo(message, err=err)
    
    # Append to log file.
    with open(CLI_LOG_FILE, "a", encoding='utf-8') as f:
        f.write(log_entry + "\n")

def load_scenario(scenario_path: Path):
    """Carrega um cenário de teste a partir de um arquivo JSON."""
    if not scenario_path.exists():
        log_message(f"Erro: Arquivo de cenário de teste '{scenario_path}' não encontrado.", level="ERROR", err=True)
        return None
    try:
        with open(scenario_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log_message(f"Erro ao ler arquivo de cenário '{scenario_path.name}': JSON inválido. {e}", level="ERROR", err=True)
        return None
    except Exception as e:
        log_message(f"Erro inesperado ao carregar cenário '{scenario_path.name}': {e}", level="ERROR", err=True)
        return None

def find_state_machine_arn(name: str) -> str:
    """Busca o ARN de uma State Machine pelo nome exato."""
    log_message(f"Buscando ARN para a State Machine com nome exato: '{name}'...")
    try:
        paginator = stepfunctions_client.get_paginator('list_state_machines')
        for page in paginator.paginate():
            for sm in page['stateMachines']:
                if sm['name'] == name:
                    log_message(f"State Machine encontrada: {sm['name']} ({sm['stateMachineArn']})")
                    return sm['stateMachineArn']
        log_message(f"Erro: Nenhuma State Machine com o nome '{name}' foi encontrada.", level="ERROR", err=True)
        return None
    except ClientError as e:
        log_message(f"Erro AWS ao listar State Machines: {e}", level="ERROR", err=True)
        return None

def get_sfn_execution_details(execution_arn):
    """Obtém detalhes de uma execução da Step Functions."""
    try:
        response = stepfunctions_client.describe_execution(executionArn=execution_arn)
        return response
    except ClientError as e:
        if e.response['Error']['Code'] == 'ThrottlingException':
            time.sleep(2)
            return get_sfn_execution_details(execution_arn)
        log_message(f"Erro AWS ao descrever execução {execution_arn}: {e}", level="ERROR", err=True)
        return None
    except Exception as e:
        log_message(f"Erro inesperado ao descrever execução {execution_arn}: {e}", level="ERROR", err=True)
        return None

def validate_execution_result(execution_details: dict, scenario_config: dict) -> (bool, list):
    """Valida o resultado da execução da Step Function contra as expectativas do cenário."""
    messages = []
    final_status = execution_details.get('status')

    if 'error' in scenario_config:
        expected_error_block = scenario_config['error']
        if final_status != 'FAILED':
            messages.append(f"Validação Falhou: Status esperado 'FAILED', mas foi '{final_status}'.")
            return False, messages

        actual_error = execution_details.get('error')
        if expected_error_block.get('Error') and expected_error_block.get('Error') != actual_error:
            messages.append(f"Validação Falhou: Tipo de erro esperado '{expected_error_block.get('Error')}', mas foi '{actual_error}'.")
            return False, messages

        expected_cause = expected_error_block.get('Cause')
        actual_cause = execution_details.get('cause', '')
        if expected_cause and expected_cause not in actual_cause:
            messages.append(f"Validação Falhou: Causa esperada '{expected_cause}' não encontrada em '{actual_cause}'.")
            return False, messages

        messages.append("Validação bem-sucedida: O teste falhou como esperado.")
        return True, messages

    if final_status != 'SUCCEEDED':
        messages.append(f"Validação Falhou: Status esperado 'SUCCEEDED', mas foi '{final_status}'.")
        error_info = f"Erro: {execution_details.get('error')}, Causa: {execution_details.get('cause')}"
        messages.append(error_info)
        return False, messages

    if 'expected' in scenario_config:
        expected_output = scenario_config['expected']
        try:
            actual_output = json.loads(execution_details.get('output', '{}'))
        except json.JSONDecodeError:
            messages.append("Validação Falhou: Output da Step Function não é um JSON válido.")
            return False, messages

        if actual_output != expected_output:
            messages.append(f"Validação Falhou: Output real não corresponde ao output esperado.\nEsperado: {json.dumps(expected_output, indent=2)}\nRecebido: {json.dumps(actual_output, indent=2)}")
            return False, messages
        messages.append("Validação bem-sucedida: Output corresponde ao esperado.")

    return True, messages

def monitor_sfn_execution(execution_arn: str, scenario_name: str, scenario_config: dict) -> bool:
    """Aguarda a conclusão da execução, exibe o resultado e retorna o status de validação."""
    log_message(f"Aguardando a conclusão do teste '{scenario_name}'...")
    status = 'RUNNING'
    spinner = ['|', '/', '-', '\\']
    spin_idx = 0
    execution_details = None

    while status == 'RUNNING':
        sys.stdout.write(f"\rStatus: {status} {spinner[spin_idx]} ")
        sys.stdout.flush()
        spin_idx = (spin_idx + 1) % len(spinner)
        time.sleep(3)
        execution_details = get_sfn_execution_details(execution_arn)
        if execution_details:
            status = execution_details['status']
        else:
            status = 'UNKNOWN'
            break

    sys.stdout.write("\n")

    log_message(click.style(f"\n--- Resultados do Teste: {scenario_name} ---", fg='cyan'))
    log_message(f"Execução: {execution_arn}")

    if not execution_details:
        log_message(click.style("Não foi possível obter os detalhes finais da execução.", fg='red'), err=True)
        return False

    final_status = execution_details.get('status', 'UNKNOWN')

    if final_status == 'SUCCEEDED':
        log_message(click.style(f"Status AWS: SUCCEEDED", fg='green'))
        try:
            output = json.loads(execution_details.get('output', '{}'))
            log_message(f"Output da Step Functions: {json.dumps(output, indent=2)}")
        except json.JSONDecodeError:
            log_message(f"Output (não JSON): {execution_details.get('output')}")
    elif final_status == 'FAILED':
        log_message(click.style(f"Status AWS: FAILED", fg='red'))
        log_message(f"Causa: {execution_details.get('cause', 'Não especificada.')}")
        log_message(f"Erro: {execution_details.get('error', 'Não especificado.')}")
    else:
        log_message(click.style(f"Status AWS: {final_status}", fg='yellow'))

    log_message(click.style("--- Validação do Cenário ---", fg='cyan'))
    is_pass, validation_messages = validate_execution_result(execution_details, scenario_config)
    for msg in validation_messages:
        log_message(msg)

    final_verdict = click.style("Resultado Final: PASSOU ✅", fg='green') if is_pass else click.style("Resultado Final: FALHOU ❌", fg='red')
    log_message(f"{final_verdict}\n" + click.style("-----------------------------------------\n", fg='cyan'))
    return is_pass

def _run_single_test(state_machine_arn: str, scenario_path: Path, wait: bool) -> bool:
    """Helper function to load, start, and monitor a single test case."""
    scenario_name = scenario_path.stem
    log_message(click.style(f"Executando cenário: {scenario_name}", bold=True))

    test_scenario_config = load_scenario(scenario_path)
    if not test_scenario_config:
        return False

    if 'input' not in test_scenario_config:
        log_message(f"Erro: O arquivo de cenário '{scenario_path.name}' deve conter uma chave 'input' no nível raiz.", level="ERROR", err=True)
        return False
    sfn_input = test_scenario_config

    test_run_id = str(uuid.uuid4())
    if isinstance(sfn_input, dict):
        sfn_input['testRunId'] = test_run_id

    execution_name = f"{scenario_name.replace('_', '-')}-{test_run_id[:8]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    try:
        start_response = stepfunctions_client.start_execution(
            stateMachineArn=state_machine_arn,
            input=json.dumps(sfn_input),
            name=execution_name
        )
        execution_arn = start_response['executionArn']
        log_message(f"ID da Execução do Teste: {test_run_id}")
        log_message(f"ARN da Execução SFN: {execution_arn}")
        log_message(f"Link para o console AWS: https://console.aws.amazon.com/states/home?#/executions/details/{execution_arn}")

        if wait:
            return monitor_sfn_execution(execution_arn, scenario_name, test_scenario_config)
        else:
            log_message("Teste iniciado em modo 'no-wait'. A CLI não acompanhará a execução.")
            return True

    except ClientError as e:
        log_message(f"Erro AWS ao iniciar execução da Step Functions: {e}", level="ERROR", err=True)
        return False
    except Exception as e:
        log_message(f"Erro inesperado ao executar teste: {e}", level="ERROR", err=True)
        return False

# --- CLI Commands ---

@click.group()
def cli():
    """CLI para gerar e orquestrar testes E2E em microsserviços AWS."""
    pass

@cli.command()
@click.argument('suites_to_run', nargs=-1)
@click.option('--wait/--no-wait', default=True, help='Esperar a conclusão do teste e mostrar o resultado. Padrão: --wait.')
def run(suites_to_run: List[str], wait: bool):
    """
    Executa suítes de teste E2E a partir do diretório 'tests'.

    A CLI usa o nome do diretório da suíte como o nome da State Machine alvo.
    Ex: A suíte 'tests/ProcessOrderFlow' irá executar a SFN 'ProcessOrderFlow'.

    - Para executar suítes específicas (ex: ProcessOrderFlow):
      python cli.py run ProcessOrderFlow

    - Para executar todas as suítes encontradas em 'tests':
      python cli.py run
    """
    root_path = Path(TEST_SUITES_DIR)
    if not root_path.is_dir():
        log_message(f"Erro: O diretório de suítes '{TEST_SUITES_DIR}' não foi encontrado.", level="ERROR", err=True)
        sys.exit(1)

    if suites_to_run:
        suite_paths = [root_path / suite for suite in suites_to_run]
        for sp in suite_paths:
            if not sp.is_dir():
                log_message(f"Aviso: Suíte '{sp.name}' não encontrada em '{root_path}'.", level="WARNING")
    else:
        suite_paths = [d for d in root_path.iterdir() if d.is_dir()]

    if not suite_paths:
        log_message("Nenhuma suíte de teste encontrada para executar.", level="WARNING")
        return

    log_message(f"Suítes a serem executadas: {[s.name for s in suite_paths if s.is_dir()]}")
    results = {'passed': 0, 'failed': 0, 'skipped': 0}

    for suite_path in suite_paths:
        if not suite_path.is_dir(): continue

        log_message(click.style(f"\n--- Iniciando Suíte de Teste: {suite_path.name} ---", fg='yellow', bold=True))
        
        # CONVENTION: The suite directory name is the State Machine name.
        state_machine_name = suite_path.name
        state_machine_arn = find_state_machine_arn(state_machine_name)
        if not state_machine_arn:
            log_message(f"Pulando suíte '{suite_path.name}' pois a State Machine '{state_machine_name}' não foi encontrada na AWS.", level="WARNING")
            results['skipped'] += 1
            continue

        inputs_dir = suite_path / "cases"
        if not inputs_dir.is_dir():
            log_message(f"Aviso: Nenhuma pasta 'cases' encontrada para a suíte '{suite_path.name}'. Pulando.", level="WARNING")
            results['skipped'] += 1
            continue

        scenario_files = sorted(list(inputs_dir.glob("*.json")))
        if not scenario_files:
            log_message(f"Aviso: Nenhum arquivo de cenário .json encontrado em '{inputs_dir}'.", level="WARNING")
            continue

        for scenario_path in scenario_files:
            is_pass = _run_single_test(state_machine_arn, scenario_path, wait)
            if is_pass:
                results['passed'] += 1
            else:
                results['failed'] += 1
    
    log_message(click.style("--- Resumo da Execução ---", fg='cyan', bold=True))
    log_message(click.style(f"Testes Passaram: {results['passed']}", fg='green'))
    log_message(click.style(f"Testes Falharam: {results['failed']}", fg='red'))
    if results['skipped'] > 0:
        log_message(click.style(f"Suítes Puladas: {results['skipped']}", fg='yellow'))
    log_message(click.style("--------------------------", fg='cyan', bold=True))

    if results['failed'] > 0:
        sys.exit(1)

@cli.command(name="list")
def list_scenarios():
    """Lista todas as suítes e cenários de teste disponíveis."""
    log_message("Suítes e cenários de teste disponíveis:", level="INFO")
    root_path = Path(TEST_SUITES_DIR)
    if not root_path.is_dir():
        log_message(f"Diretório de suítes '{TEST_SUITES_DIR}' não encontrado.", level="WARNING")
        return

    found_any = False
    suites = sorted([d for d in root_path.iterdir() if d.is_dir()])
    for suite_path in suites:
        # CONVENTION: The target SFN is the directory name.
        target_sfn = suite_path.name
        
        inputs_dir = suite_path / "cases"
        if inputs_dir.is_dir():
            scenarios = sorted([f.stem for f in inputs_dir.glob("*.json")])
            if scenarios:
                found_any = True
                click.echo(click.style(f"Suite: {suite_path.name}", fg='yellow') + f" (Alvo SFN: {target_sfn})")
                for scenario_name in scenarios:
                    click.echo(f"  - {scenario_name}")

    if not found_any:
        log_message("Nenhum cenário de teste foi encontrado.")
        log_message("Verifique se a estrutura 'tests/NOME_DA_STATE_MACHINE/inputs/*.json' existe.")

# --- AI-Powered Generation (unchanged) ---
def load_ai_config(provider_name: str = None):
    """Carrega as configurações de IA de um arquivo config.yaml."""
    config_path = Path(CONFIG_FILE)
    if not config_path.exists():
        log_message(f"Aviso: Arquivo de configuração '{CONFIG_FILE}' não encontrado. Usando apenas variáveis de ambiente para OpenAI.", level="WARNING")
        return {"provider": provider_name or "openai"}

    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            log_message(f"Erro ao ler o arquivo de configuração '{CONFIG_FILE}': {e}", level="ERROR", err=True)
            return None

    if not provider_name:
        provider_name = config.get('default_provider')
        if not provider_name:
            log_message(f"Erro: 'default_provider' não definido em '{CONFIG_FILE}' e nenhum provedor foi especificado via --provider.", level="ERROR", err=True)
            return None

    provider_config = config.get('providers', {}).get(provider_name, {})
    provider_config['provider'] = provider_name
    return provider_config

def scenarios_generate(projeto_path: str, provider: str = None):
    """Gera cenários de teste com IA usando LangChain."""
    try:
        from langchain_openai import OpenAI, AzureChatOpenAI
        from langchain_google_genai import GoogleGenerativeAI
        from langchain_core.prompts import PromptTemplate
        from langchain_core.messages import AIMessage
    except ImportError:
        log_message(
            "Erro: Para usar esta funcionalidade, instale as dependências de IA:\n"
            "pip install pyyaml langchain langchain-openai langchain-google-genai",
            level="ERROR", err=True
        )
        return []

    config = load_ai_config(provider)
    if not config:
        return []

    llm = None
    provider_name = config.get('provider')
    log_message(f"Usando provedor de IA: {provider_name}")

    # Configure LLM based on provider
    if provider_name == 'openai':
        api_key = config.get('api_key') or os.getenv('OPENAI_API_KEY')
        if not api_key:
            log_message("Erro: Chave de API da OpenAI não encontrada. Defina em 'config.yaml' ou na variável de ambiente OPENAI_API_KEY.", level="ERROR", err=True)
            return []
        llm = OpenAI(temperature=0.2, max_tokens=2048, api_key=api_key)
    elif provider_name == 'azure':
        pass 
    elif provider_name == 'gemini':
        api_key = config.get('api_key') or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            log_message("Erro: Chave de API do Google não encontrada. Defina em 'config.yaml' ou na variável de ambiente GOOGLE_API_KEY.", level="ERROR", err=True)
            return []
        llm = GoogleGenerativeAI(model="gemini-pro", google_api_key=api_key, temperature=0.2)
    else:
        log_message(f"Erro: Provedor de IA '{provider_name}' não é suportado.", level="ERROR", err=True)
        return []

    context_files = []
    for root, _, files in os.walk(projeto_path):
        for f in files:
            if f.endswith(('.py', '.yaml', '.json', '.ts', '.js')):
                try:
                    with open(os.path.join(root, f), 'r', encoding='utf-8') as file_content:
                        context_files.append(f"--- File: {f} ---\n{file_content.read(2000)}\n")
                except:
                    pass 
    
    context = "\n".join(context_files)
    prompt = PromptTemplate(
        input_variables=["contexto"],
        template="""
Você é um especialista em testes de software (QA) criando cenários de teste para um sistema na AWS.
Com base no contexto do projeto fornecido abaixo, gere uma lista de até 5 cenários de teste.

Contexto do Projeto:
{contexto}

Cada cenário deve ser um objeto JSON completo com as seguintes chaves:
- "description": uma string clara e concisa descrevendo o objetivo do teste.
- "input": um objeto JSON que será o input para a Step Function alvo da suíte de teste.
- "expected": (Opcional) um objeto JSON representando o output esperado se o teste for bem-sucedido.
- "error": (Opcional) um objeto JSON com as chaves "Error" e "Cause" se o teste espera uma falha.

Sua resposta DEVE ser um único e válido array JSON. NÃO inclua nenhum texto antes ou depois do array.
"""
    )
    
    chain = prompt | llm
    response = chain.invoke({"contexto": context})
    response_content = response if isinstance(response, str) else response.content
    
    try:
        clean_response = response_content.strip().removeprefix("```json").removesuffix("```").strip()
        scenarios = json.loads(clean_response)
        if not isinstance(scenarios, list):
            raise json.JSONDecodeError("A resposta da IA não é uma lista JSON.", clean_response, 0)
        return scenarios
    except json.JSONDecodeError as e:
        log_message("Falha ao interpretar resposta da IA como JSON.", level="ERROR", err=True)
        log_message(f"Erro: {e}", level="DEBUG")
        log_message("Resposta bruta recebida:\n" + response_content, level="DEBUG")
        return []

@cli.command()
@click.argument('project_path', type=click.Path(exists=True, file_okay=False))
@click.option('--provider', default=None, help='Provedor de IA a ser usado (ex: openai, gemini).')
def generate(project_path, provider):
    """
    Gera cenários de teste para um projeto usando IA.

    Os cenários serão salvos em: tests/NOME_DO_PROJETO/inputs/
    O nome do diretório será usado como o nome da State Machine alvo.
    """
    log_message(f"Gerando cenários para o projeto em '{project_path}'...")
    scenarios = scenarios_generate(project_path, provider=provider)
    if not scenarios:
        log_message("Nenhum cenário foi gerado.", level="WARNING")
        return
    
    suite_name = Path(project_path).name
    suite_dir = Path(TEST_SUITES_DIR) / suite_name
    inputs_dir = suite_dir / "cases"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    log_message(click.style(f"\nCenários gerados para a suíte '{suite_name}':", bold=True))
    for i, scenario_data in enumerate(scenarios):
        desc_slug = scenario_data.get("description", f"cenario_{i+1}").lower().replace(" ", "_")
        filename = "".join(c for c in desc_slug if c.isalnum() or c == '_')[:50] + ".json"
        filepath = inputs_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(scenario_data, f, indent=2, ensure_ascii=False)
        
        click.echo(f"- {scenario_data.get('description')}")
        click.echo(f"  └─ Salvo em: {filepath}")

    log_message(f"\n{len(scenarios)} cenários foram salvos com sucesso em '{inputs_dir}'.")
    log_message(click.style(f"Lembrete: A suíte '{suite_name}' irá procurar por uma State Machine com o nome '{suite_name}' na AWS.", fg='magenta'))


if __name__ == '__main__':
    Path(TEST_SUITES_DIR).mkdir(exist_ok=True)
    cli()
