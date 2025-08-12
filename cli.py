import click
from typing import List, Dict, Tuple, Any
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

# Attempt to import questionary for interactive mode
try:
    import questionary
except ImportError:
    questionary = None

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

def log_message(message, level="INFO", err=False, console=True):
    """Escreve mensagens no console e/ou em um arquivo de log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Remove ANSI color codes for clean log files
    clean_message = click.unstyle(str(message))
    log_entry = f"[{timestamp}] [{level}] {clean_message}"
    
    # Print to console (stderr for errors).
    if console:
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
        # Cache results to avoid multiple API calls for the same SFN name
        if not hasattr(find_state_machine_arn, "cache"):
            find_state_machine_arn.cache = {}
        
        if name in find_state_machine_arn.cache:
            arn = find_state_machine_arn.cache[name]
            if arn:
                log_message(f"State Machine encontrada no cache: {name}")
            return arn

        paginator = stepfunctions_client.get_paginator('list_state_machines')
        for page in paginator.paginate():
            for sm in page['stateMachines']:
                if sm['name'] == name:
                    log_message(f"State Machine encontrada na AWS: {sm['name']} ({sm['stateMachineArn']})")
                    find_state_machine_arn.cache[name] = sm['stateMachineArn']
                    return sm['stateMachineArn']
        
        log_message(f"Erro: Nenhuma State Machine com o nome '{name}' foi encontrada.", level="ERROR", err=True)
        find_state_machine_arn.cache[name] = None
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

        validation_results = {}
        validation_errors = []

        key_mappings = {
            'statusCode': ('apiResult', 'StatusCode'),
            'statusInDb': ('verificationData', 'Item', 'status', 'S')
        }

        for key, path in key_mappings.items():
            if key in expected_output:
                current_level = actual_output
                found = True
                for step in path:
                    if isinstance(current_level, dict) and step in current_level:
                        current_level = current_level[step]
                    else:
                        validation_errors.append(f"Não foi possível encontrar o caminho '...{'.'.join(path)}' no output.")
                        found = False
                        break
                if found:
                    validation_results[key] = current_level

        if validation_errors:
            messages.extend(validation_errors)
            messages.append("Verifique o arquivo de log para ver o output completo da Step Function e depurar o erro.")
            return False, messages

        if validation_results != expected_output:
            messages.append("Validação Falhou: Output normalizado não corresponde ao esperado.")
            messages.append(f"Esperado: {json.dumps(expected_output, indent=2)}")
            messages.append(f"Recebido (normalizado): {json.dumps(validation_results, indent=2)}")
            return False, messages

        messages.append("Validação bem-sucedida: Output corresponde ao esperado.")

    return True, messages

def monitor_sfn_execution(execution_arn: str, scenario_name: str, scenario_config: dict, analysis_enabled: bool, analysis_provider: str) -> bool:
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

    # Performance Measurement
    if execution_details.get('startDate') and execution_details.get('stopDate'):
        sfn_duration = execution_details['stopDate'] - execution_details['startDate']
        log_message(f"Duração da Execução SFN: {sfn_duration.total_seconds():.2f} segundos")

    try:
        output = json.loads(execution_details.get('output', '{}'))
        log_message(f"Output completo da SFN: {json.dumps(output, indent=2)}", console=False, level="DEBUG")
    except (json.JSONDecodeError, TypeError):
        log_message(f"Output completo da SFN (não JSON): {execution_details.get('output')}", console=False, level="DEBUG")

    final_status = execution_details.get('status', 'UNKNOWN')

    if final_status == 'SUCCEEDED':
        log_message(click.style(f"Status AWS: SUCCEEDED", fg='green'))
    elif final_status == 'FAILED':
        log_message(click.style(f"Status AWS: FAILED", fg='red'))
        log_message(f"Causa: {execution_details.get('cause', 'Não especificada.')}")
        log_message(f"Erro: {execution_details.get('error', 'Não especificado.')}")
        
        if analysis_enabled:
            _invoke_ai_analysis(scenario_config, execution_details, analysis_provider)

    else:
        log_message(click.style(f"Status AWS: {final_status}", fg='yellow'))

    log_message(click.style("--- Validação do Cenário ---", fg='cyan'))
    is_pass, validation_messages = validate_execution_result(execution_details, scenario_config)
    for msg in validation_messages:
        log_message(msg)

    final_verdict = click.style("Resultado Final: PASSOU ✅", fg='green') if is_pass else click.style("Resultado Final: FALHOU ❌", fg='red')
    log_message(f"{final_verdict}\n" + click.style("-----------------------------------------\n", fg='cyan'))
    return is_pass

def _run_single_test(state_machine_arn: str, scenario_path: Path, wait: bool, analysis_enabled: bool, analysis_provider: str) -> bool:
    """Helper function to load, start, and monitor a single test case."""
    scenario_name = scenario_path.stem
    log_message(click.style(f"Executando cenário: {scenario_name}", bold=True))

    test_scenario_config = load_scenario(scenario_path)
    if not test_scenario_config:
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
            return monitor_sfn_execution(execution_arn, scenario_name, test_scenario_config, analysis_enabled, analysis_provider)
        else:
            log_message("Teste iniciado em modo 'no-wait'. A CLI não acompanhará a execução.")
            return True

    except ClientError as e:
        log_message(f"Erro AWS ao iniciar execução da Step Functions: {e}", level="ERROR", err=True)
        return False
    except Exception as e:
        log_message(f"Erro inesperado ao executar teste: {e}", level="ERROR", err=True)
        return False

def _run_and_summarize_tests(test_jobs: List[Dict], parallel: bool, wait: bool, analysis_enabled: bool, analysis_provider: str):
    """Dispatches test jobs for execution, either sequentially or in parallel, and summarizes results."""
    results = {'passed': 0, 'failed': 0}
    
    if not test_jobs:
        log_message("Nenhum teste para executar.", level="WARNING")
        return

    run_start_time = time.monotonic()

    if parallel:
        log_message("Executando testes em modo PARALELO.", level="INFO")
        with ThreadPoolExecutor() as executor:
            future_to_job = {
                executor.submit(
                    _run_single_test, 
                    job['state_machine_arn'], 
                    job['scenario_path'], 
                    wait,
                    analysis_enabled,
                    analysis_provider
                ): job for job in test_jobs
            }
            
            for future in as_completed(future_to_job):
                try:
                    is_pass = future.result()
                    if is_pass:
                        results['passed'] += 1
                    else:
                        results['failed'] += 1
                except Exception as exc:
                    job = future_to_job[future]
                    scenario_name = job['scenario_path'].stem
                    log_message(f"Cenário '{scenario_name}' gerou uma exceção: {exc}", level="ERROR", err=True)
                    results['failed'] += 1
    else:
        log_message("Executando testes em modo SEQUENCIAL.", level="INFO")
        for job in test_jobs:
            is_pass = _run_single_test(job['state_machine_arn'], job['scenario_path'], wait, analysis_enabled, analysis_provider)
            if is_pass:
                results['passed'] += 1
            else:
                results['failed'] += 1
    
    run_end_time = time.monotonic()
    total_duration = run_end_time - run_start_time

    log_message(click.style("\n--- Resumo Final da Execução ---", fg='cyan', bold=True))
    log_message(click.style(f"Testes Passaram: {results['passed']}", fg='green'))
    log_message(click.style(f"Testes Falharam: {results['failed']}", fg='red'))
    log_message(click.style(f"Tempo Total de Execução (CLI): {total_duration:.2f} segundos", bold=True))
    log_message(click.style("--------------------------\n", fg='cyan', bold=True))

    if results['failed'] > 0:
        sys.exit(1)

def _run_interactive_mode(wait: bool, parallel: bool, analysis_enabled: bool, analysis_provider: str):
    """Guides the user through an interactive session to select suites and scenarios."""
    if not questionary:
        log_message("Erro: O modo interativo requer a biblioteca 'questionary'.", level="ERROR", err=True)
        log_message("Instale com: pip install questionary", level="ERROR", err=True)
        sys.exit(1)

    root_path = Path(TEST_SUITES_DIR)
    available_suites = [d for d in root_path.iterdir() if d.is_dir()]
    if not available_suites:
        log_message("Nenhuma suíte de teste encontrada no diretório 'tests'.", level="WARNING")
        return

    try:
        selected_suite_names = questionary.checkbox(
            'Selecione as suítes de teste que deseja executar (use a barra de espaço):',
            choices=sorted([s.name for s in available_suites])
        ).ask()

        if not selected_suite_names:
            log_message("Nenhuma suíte selecionada. Encerrando.", level="INFO")
            return

        test_jobs = []
        skipped_suites = 0
        for suite_name in selected_suite_names:
            suite_path = root_path / suite_name
            state_machine_arn = find_state_machine_arn(suite_name)
            if not state_machine_arn:
                log_message(f"Pulando suíte '{suite_name}' pois a State Machine não foi encontrada.", level="WARNING")
                skipped_suites += 1
                continue

            cases_dir = suite_path / "cases"
            if not cases_dir.is_dir():
                log_message(f"Aviso: Nenhuma pasta 'cases' encontrada para a suíte '{suite_name}'.", level="WARNING")
                continue

            scenarios = sorted([f.stem for f in cases_dir.glob("*.json")])
            if not scenarios:
                log_message(f"Aviso: Nenhum cenário encontrado para a suíte '{suite_name}'.", level="WARNING")
                continue
            
            all_scenarios_choice = "== TODOS OS CENÁRIOS =="
            
            selected_scenarios = questionary.checkbox(
                f"Selecione os cenários para a suíte '{suite_name}':",
                choices=[all_scenarios_choice] + scenarios
            ).ask()

            if not selected_scenarios:
                log_message(f"Nenhum cenário selecionado para '{suite_name}'. Pulando.", level="INFO")
                continue
            
            scenarios_to_run = scenarios if all_scenarios_choice in selected_scenarios else selected_scenarios
            
            for scenario_name in scenarios_to_run:
                test_jobs.append({
                    'state_machine_arn': state_machine_arn,
                    'scenario_path': cases_dir / f"{scenario_name}.json",
                })
        
        if skipped_suites > 0:
            log_message(f"{skipped_suites} suíte(s) pulada(s) por não encontrar a SFN correspondente.")

        _run_and_summarize_tests(test_jobs, parallel, wait, analysis_enabled, analysis_provider)

    except (KeyboardInterrupt, TypeError):
        log_message("\nOperação cancelada pelo usuário.", level="INFO")
        sys.exit(0)


# --- CLI Commands ---

@click.group()
def cli():
    """CLI para gerar e orquestrar testes E2E em microsserviços AWS."""
    pass

@cli.command()
@click.argument('suites_to_run', nargs=-1, required=False)
@click.option('--scenario', '-s', 'scenarios_to_run', multiple=True, help='Executa cenários específicos pelo nome (sem a extensão .json).')
@click.option('--interactive', '-i', is_flag=True, help='Inicia a CLI em modo interativo para selecionar suítes e cenários.')
@click.option('--parallel', is_flag=True, help='Executa os testes em paralelo para maior velocidade.')
@click.option('--analyze-failures', 'analysis_enabled', is_flag=True, help='Ativa a IA para analisar e sugerir correções para testes que falham.')
@click.option('--provider', 'analysis_provider', default=None, help='Provedor de IA a ser usado para geração ou análise (ex: openai, gemini, azure, groq, claude, github).')
@click.option('--wait/--no-wait', default=True, help='Espera a conclusão do teste e mostra o resultado. Padrão: --wait.')
def run(suites_to_run: Tuple[str], scenarios_to_run: Tuple[str], wait: bool, interactive: bool, parallel: bool, analysis_enabled: bool, analysis_provider: str):
    """
    Executa suítes de teste E2E a partir do diretório 'tests'.

    MODO INTERATIVO:
      python cli.py run -i

    MODO PADRÃO:
    - Executar todas as suítes com análise de falhas:
      python cli.py run --analyze-failures

    - Executar uma suíte específica em paralelo:
      python cli.py run ProcessOrderFlow --parallel
    """
    if interactive:
        _run_interactive_mode(wait, parallel, analysis_enabled, analysis_provider)
        return

    root_path = Path(TEST_SUITES_DIR)
    if not root_path.is_dir():
        log_message(f"Erro: O diretório de suítes '{TEST_SUITES_DIR}' não foi encontrado.", level="ERROR", err=True)
        sys.exit(1)

    suite_paths_to_run = []
    if not suites_to_run:
        suite_paths_to_run = [d for d in root_path.iterdir() if d.is_dir()]
    else:
        for suite_name in suites_to_run:
            suite_path = root_path / suite_name
            if suite_path.is_dir():
                suite_paths_to_run.append(suite_path)
            else:
                log_message(f"Aviso: Suíte '{suite_name}' não encontrada em '{root_path}'.", level="WARNING")

    if not suite_paths_to_run:
        log_message("Nenhuma suíte de teste válida para executar.", level="WARNING")
        return

    test_jobs = []
    skipped_suites = 0
    for suite_path in suite_paths_to_run:
        state_machine_name = suite_path.name
        state_machine_arn = find_state_machine_arn(state_machine_name)
        if not state_machine_arn:
            log_message(f"Pulando suíte '{suite_path.name}' pois a SFN não foi encontrada.", level="WARNING")
            skipped_suites += 1
            continue
        
        cases_dir = suite_path / "cases"
        if not cases_dir.is_dir():
            log_message(f"Aviso: Nenhuma pasta 'cases' encontrada para a suíte '{suite_path.name}'.", level="WARNING")
            continue

        scenarios_in_dir = cases_dir.glob("*.json")
        scenarios_to_execute_paths = []
        if scenarios_to_run:
            for s_name in scenarios_to_run:
                path = cases_dir / f"{s_name}.json"
                if path.exists():
                    scenarios_to_execute_paths.append(path)
                else:
                     log_message(f"Aviso: Cenário '{s_name}' não encontrado em '{cases_dir}'.", level="WARNING")
        else:
            scenarios_to_execute_paths = sorted(list(scenarios_in_dir))

        for s_path in scenarios_to_execute_paths:
            test_jobs.append({
                'state_machine_arn': state_machine_arn,
                'scenario_path': s_path,
            })

    if skipped_suites > 0:
        log_message(f"{skipped_suites} suíte(s) pulada(s) por não encontrar a SFN correspondente.")

    _run_and_summarize_tests(test_jobs, parallel, wait, analysis_enabled, analysis_provider)


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
        target_sfn = suite_path.name
        
        cases_dir = suite_path / "cases"
        if cases_dir.is_dir():
            scenarios = sorted([f.stem for f in cases_dir.glob("*.json")])
            if scenarios:
                found_any = True
                click.echo(click.style(f"Suite: {suite_path.name}", fg='yellow') + f" (Alvo SFN: {target_sfn})")
                for scenario_name in scenarios:
                    click.echo(f"  - {scenario_name}")

    if not found_any:
        log_message("Nenhum cenário de teste foi encontrado.")
        log_message("Verifique se a estrutura 'tests/NOME_DA_STATE_MACHINE/cases/*.json' existe.")

# --- AI-Powered Generation & Analysis ---

def _get_llm_instance(provider_name: str, config: Dict[str, Any]):
    """Initializes and returns a LangChain LLM instance based on the provider."""
    try:
        from langchain_openai import OpenAI, AzureChatOpenAI
        from langchain_google_genai import GoogleGenerativeAI
        from langchain_groq import ChatGroq
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        log_message(
            "Erro: Para usar a funcionalidade de IA, instale as dependências:\n"
            "pip install pyyaml langchain langchain-openai langchain-google-genai langchain-groq langchain-anthropic",
            level="ERROR", err=True
        )
        return None

    provider_name = provider_name or config.get('provider')
    log_message(f"Usando provedor de IA: {provider_name}")

    if provider_name == 'openai':
        api_key = config.get('api_key') or os.getenv('OPENAI_API_KEY')
        if not api_key:
            log_message("Erro: Chave de API da OpenAI não encontrada. Defina em 'config.yaml' ou na variável de ambiente OPENAI_API_KEY.", level="ERROR", err=True)
            return None
        return OpenAI(temperature=0.2, max_tokens=2048, api_key=api_key)
    
    elif provider_name == 'azure':
        required_keys = ['api_key', 'endpoint', 'deployment_name', 'api_version']
        if not all(key in config for key in required_keys):
            log_message(f"Erro: Para o provedor Azure, as chaves {required_keys} são necessárias em '{CONFIG_FILE}'.", level="ERROR", err=True)
            return None
        return AzureChatOpenAI(
            temperature=0.2,
            max_tokens=2048,
            openai_api_key=config['api_key'],
            azure_endpoint=config['endpoint'],
            deployment_name=config['deployment_name'],
            openai_api_version=config['api_version']
        )
    
    elif provider_name == 'github':
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            log_message("Erro: A variável de ambiente GITHUB_TOKEN é necessária para o provedor 'github'.", level="ERROR", err=True)
            return None
        
        # Use defaults from the user's snippet, but allow overrides from config.yaml
        endpoint = config.get('endpoint', "https://models.github.ai/inference")
        model_name = config.get('model_name', "deepseek/DeepSeek-V3-0324")
        api_version = config.get('api_version', "2024-05-01-preview")

        return AzureChatOpenAI(
            temperature=0.2,
            max_tokens=2048,
            openai_api_key=token,
            azure_endpoint=endpoint,
            deployment_name=model_name,
            openai_api_version=api_version
        )

    elif provider_name == 'gemini':
        api_key = config.get('api_key') or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            log_message("Erro: Chave de API do Google não encontrada. Defina em 'config.yaml' ou na variável de ambiente GOOGLE_API_KEY.", level="ERROR", err=True)
            return None
        return GoogleGenerativeAI(model="gemini-pro", google_api_key=api_key, temperature=0.2)

    elif provider_name == 'groq':
        api_key = config.get('api_key') or os.getenv('GROQ_API_KEY')
        if not api_key:
            log_message("Erro: Chave de API da Groq não encontrada. Defina em 'config.yaml' ou na variável de ambiente GROQ_API_KEY.", level="ERROR", err=True)
            return None
        model_name = config.get('model_name', "llama3-8b-8192")
        return ChatGroq(temperature=0, model_name=model_name, groq_api_key=api_key)

    elif provider_name == 'claude':
        api_key = config.get('api_key') or os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            log_message("Erro: Chave de API da Anthropic não encontrada. Defina em 'config.yaml' ou na variável de ambiente ANTHROPIC_API_KEY.", level="ERROR", err=True)
            return None
        model_name = config.get('model_name', "claude-3-sonnet-20240229")
        return ChatAnthropic(model=model_name, anthropic_api_key=api_key)
    
    else:
        log_message(f"Erro: Provedor de IA '{provider_name}' não é suportado.", level="ERROR", err=True)
        return None

def _invoke_ai_analysis(scenario_config: Dict, execution_details: Dict, provider: str):
    """Analyzes a failed test run using an AI."""
    log_message(click.style("--- Análise de Falha por IA Ativada ---", fg='magenta', bold=True))
    
    config = load_ai_config(provider)
    if not config:
        log_message("Não foi possível carregar a configuração de IA para análise. Pulando.", level="WARNING")
        return

    provider_name = provider or config.get('default_provider')
    provider_config = config.get('providers', {}).get(provider_name, {})
    llm = _get_llm_instance(provider_name, provider_config)

    if not llm:
        log_message("Não foi possível inicializar o modelo de IA para análise. Pulando.", level="WARNING")
        return

    from langchain_core.prompts import PromptTemplate

    prompt = PromptTemplate(
        input_variables=["scenario_input", "expected_result", "actual_error", "actual_cause"],
        template="""
Você é um engenheiro de software sênior e especialista em AWS. Sua tarefa é analisar a falha de um teste E2E de uma Step Function.

**Contexto do Teste:**
Um teste automatizado foi executado com o seguinte input e expectativas:

- **Input Enviado:**
```json
{scenario_input}
```

- **Resultado Esperado:**
```json
{expected_result}
```

**Resultado da Falha:**
O teste falhou com os seguintes detalhes da execução na AWS:

- **Tipo de Erro:** {actual_error}
- **Causa da Falha:**
```
{actual_cause}
```

**Sua Análise:**
Com base nos dados acima, forneça uma análise concisa da falha.

1.  **Diagnóstico Provável:** Qual a causa raiz mais provável do problema? Seja direto e técnico.
2.  **Pontos de Verificação:** Quais são os 2 ou 3 pontos principais que o desenvolvedor deve investigar para corrigir o problema? (ex: "Verificar a permissão (IAM Role) da Lambda X", "Analisar os logs da Lambda Y em busca do erro Z", "Confirmar se o formato do evento para o EventBridge está correto").
3.  **Possível Solução:** Se a causa for óbvia, sugira uma possível solução ou um trecho de código para correção.

Seja claro, objetivo e forneça insights práticos para acelerar a depuração.
"""
    )

    scenario_input = json.dumps(scenario_config, indent=2)
    expected_result = "Sucesso com output específico" if "expected" in scenario_config else f"Falha controlada com erro '{scenario_config.get('error', {}).get('Error')}'"
    actual_error = execution_details.get('error', 'N/A')
    actual_cause = execution_details.get('cause', 'N/A')

    chain = prompt | llm
    
    log_message(click.style("A IA está analisando a falha...", fg='magenta'))
    try:
        response = chain.invoke({
            "scenario_input": scenario_input,
            "expected_result": expected_result,
            "actual_error": actual_error,
            "actual_cause": actual_cause
        })
        
        response_content = response if isinstance(response, str) else response.content
        
        log_message(click.style("--- Análise da IA ---", fg='magenta', bold=True))
        log_message(response_content)
        log_message(click.style("---------------------", fg='magenta', bold=True))

    except Exception as e:
        log_message(f"Erro ao invocar a IA para análise: {e}", level="ERROR", err=True)


def load_ai_config(provider_name: str = None):
    """Carrega as configurações de IA de um arquivo config.yaml."""
    config_path = Path(CONFIG_FILE)
    if not config_path.exists():
        log_message(f"Aviso: Arquivo de configuração '{CONFIG_FILE}' não encontrado. Usando apenas variáveis de ambiente para OpenAI.", level="WARNING")
        return {"provider": provider_name or "openai", "providers": {}}

    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            log_message(f"Erro ao ler o arquivo de configuração '{CONFIG_FILE}': {e}", level="ERROR", err=True)
            return None

    if not provider_name and 'default_provider' not in config:
        log_message(f"Erro: 'default_provider' não definido em '{CONFIG_FILE}' e nenhum provedor foi especificado via --provider.", level="ERROR", err=True)
        return None
    
    # Ensure providers key exists
    if 'providers' not in config:
        config['providers'] = {}

    return config

def _select_context_files(project_path: str) -> List[Path]:
    """Interactively prompts the user to select files and folders for the AI context."""
    if not questionary:
        log_message("Erro: O modo interativo requer a biblioteca 'questionary'.", level="ERROR", err=True)
        log_message("Instale com: pip install questionary", level="ERROR", err=True)
        sys.exit(1)

    p_path = Path(project_path)
    # List all files, ignoring common noise like .git, __pycache__, etc.
    all_files = [
        f.relative_to(p_path) for f in p_path.rglob('*') 
        if f.is_file() and not any(part in f.parts for part in ['.git', '__pycache__', 'node_modules', '.venv'])
    ]
    
    # Sort files to ensure consistent ordering
    all_files.sort()

    try:
        selected_files_str = questionary.checkbox(
            'Selecione os arquivos para incluir no contexto da IA (use a barra de espaço):',
            choices=[str(f) for f in all_files]
        ).ask()

        if not selected_files_str:
            return []

        return [p_path / f for f in selected_files_str]

    except (KeyboardInterrupt, TypeError):
        log_message("\nSeleção de contexto cancelada.", level="INFO")
        return []

def scenarios_generate(projeto_path: str, provider: str = None, interactive: bool = False):
    """Gera cenários de teste com IA usando LangChain."""
    config = load_ai_config(provider)
    if not config:
        return []

    # If a specific provider is passed, use it. Otherwise, use the default.
    provider_name = provider or config.get('default_provider')
    provider_config = config.get('providers', {}).get(provider_name, {})

    llm = _get_llm_instance(provider_name, provider_config)
    if not llm:
        return []

    from langchain_core.prompts import PromptTemplate
    
    file_paths_for_context = []
    if interactive:
        file_paths_for_context = _select_context_files(projeto_path)
        if not file_paths_for_context:
            log_message("Nenhum arquivo selecionado para o contexto. Encerrando.", level="WARNING")
            return []
    else:
        # Default behavior: grab all relevant files
        for root, _, files in os.walk(projeto_path):
            # Exclude common noise directories
            if any(part in root for part in ['.git', '__pycache__', 'node_modules', '.venv']):
                continue
            for f in files:
                if f.endswith(('.py', '.yaml', '.yml', '.json', '.ts', '.js', 'requirements.txt', 'package.json', 'Dockerfile', '.md')):
                    file_paths_for_context.append(Path(root) / f)

    context_parts = []
    log_message("Construindo contexto com os seguintes arquivos:")
    for file_path in file_paths_for_context:
        try:
            relative_path = file_path.relative_to(projeto_path)
            log_message(f"  - {relative_path}")
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file_content:
                context_parts.append(f"--- File: {relative_path} ---\n{file_content.read(4000)}\n") # Increased limit slightly
        except Exception as e:
            log_message(f"Não foi possível ler o arquivo {file_path}: {e}", level="WARNING")
            
    context = "\n".join(context_parts)
    
    prompt = PromptTemplate(
        input_variables=["contexto"],
        template="""
Você é um especialista em testes de software (QA) criando cenários de teste para um sistema na AWS.
Com base no contexto do projeto fornecido abaixo, gere uma lista de cenários de teste com a máxima cobertura.

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
    log_message(click.style("Enviando requisição para a IA para gerar cenários...", fg='magenta'))
    response = chain.invoke({"contexto": context})
    response_content = response if isinstance(response, str) else response.content
    
    try:
        # Robust JSON extraction
        start_index = response_content.find('[')
        end_index = response_content.rfind(']')
        if start_index != -1 and end_index != -1 and end_index > start_index:
            json_str = response_content[start_index : end_index + 1]
            scenarios = json.loads(json_str)
            if not isinstance(scenarios, list):
                 raise json.JSONDecodeError("O JSON extraído não é uma lista.", json_str, 0)
            return scenarios
        raise ValueError("Nenhum array JSON válido foi encontrado na resposta da IA.")
    except (json.JSONDecodeError, ValueError) as e:
        log_message("Falha ao extrair ou interpretar o JSON da resposta da IA.", level="ERROR", err=True)
        log_message(f"Erro: {e}", level="DEBUG")
        log_message("Resposta bruta recebida:\n" + response_content, level="DEBUG")
        return []

@cli.command()
@click.argument('project_path', type=click.Path(exists=True, file_okay=False))
@click.option('--provider', default=None, help='Provedor de IA a ser usado (ex: openai, gemini, azure, groq, claude, github).')
@click.option('--interactive', '-i', is_flag=True, help='Selecionar interativamente os arquivos de contexto para a IA.')
def generate(project_path, provider, interactive):
    """
    Gera cenários de teste para um projeto usando IA.

    Os cenários serão salvos em: tests/NOME_DO_PROJETO/cases/
    O nome do diretório será usado como o nome da State Machine alvo.
    """
    log_message(f"Gerando cenários para o projeto em '{project_path}'...")
    scenarios = scenarios_generate(project_path, provider=provider, interactive=interactive)
    if not scenarios:
        log_message("Nenhum cenário foi gerado.", level="WARNING")
        return
    
    suite_name = Path(project_path).name
    suite_dir = Path(TEST_SUITES_DIR) / suite_name
    cases_dir = suite_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    log_message(click.style(f"\nCenários gerados para a suíte '{suite_name}':", bold=True))
    for i, scenario_data in enumerate(scenarios):
        desc = scenario_data.get("description", f"cenario_{i+1}")
        # Sanitize description for use as a filename
        desc_slug = desc.lower().replace(" ", "_")
        filename = "".join(c for c in desc_slug if c.isalnum() or c == '_')[:50] + ".json"
        filepath = cases_dir / filename

        # Prepare the final JSON content for the file
        file_content = {
            "description": desc,
            "input": scenario_data.get("input", {}),
        }
        if "expected" in scenario_data:
            file_content["expected"] = scenario_data["expected"]
        if "error" in scenario_data:
            file_content["error"] = scenario_data["error"]

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(file_content, f, indent=2, ensure_ascii=False)
        
        click.echo(f"- {desc}")
        click.echo(f"  └─ Salvo em: {filepath}")

    log_message(f"\n{len(scenarios)} cenários foram salvos com sucesso em '{cases_dir}'.")
    log_message(click.style(f"Lembrete: A suíte '{suite_name}' irá procurar por uma State Machine com o nome '{suite_name}' na AWS.", fg='magenta'))


if __name__ == '__main__':
    Path(TEST_SUITES_DIR).mkdir(exist_ok=True)
    cli()
