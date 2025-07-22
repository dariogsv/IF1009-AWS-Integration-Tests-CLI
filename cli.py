import click
import boto3
import json
import os
import time
import uuid
import sys
from datetime import datetime

# --- Configurações da CLI ---
# Caminho para o diretório de arquivos de cenários de teste
TEST_SCENARIOS_DIR = "tests"

# Nome do arquivo de log da CLI (para depuração interna da CLI)
CLI_LOG_FILE = "cli_debug.log"

# Inicializa clientes AWS
sfn_client = boto3.client('stepfunctions')
logs_client = boto3.client('logs')

# --- Funções Auxiliares ---
def _log_message(message, level="INFO"):
    """Escreve mensagens no console e em um arquivo de log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{level}] {message}"
    click.echo(message) # Imprime no console
    with open(CLI_LOG_FILE, "a") as f:
        f.write(log_entry + "\n")

def _load_scenario(scenario_name):
    """Carrega um cenário de teste a partir de um arquivo JSON."""
    scenario_file = os.path.join(TEST_SCENARIOS_DIR, f"{scenario_name}.json")
    if not os.path.exists(scenario_file):
        _log_message(f"Erro: Cenário de teste '{scenario_name}' não encontrado em {TEST_SCENARIOS_DIR}.")
        return None
    try:
        with open(scenario_file, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        _log_message(f"Erro ao ler arquivo de cenário '{scenario_name}.json': JSON inválido. {e}", level="ERROR")
        return None
    except Exception as e:
        _log_message(f"Erro inesperado ao carregar cenário '{scenario_name}': {e}", level="ERROR")
        return None

def _get_sfn_execution_details(execution_arn):
    """Obtém detalhes de uma execução da Step Functions."""
    try:
        response = sfn_client.describe_execution(executionArn=execution_arn)
        return response
    except sfn_client.exceptions.ExecutionDoesNotExist:
        _log_message(f"Erro: Execução {execution_arn} não existe.", level="ERROR")
        return None
    except ClientError as e:
        _log_message(f"Erro AWS ao descrever execução {execution_arn}: {e}", level="ERROR")
        return None
    except Exception as e:
        _log_message(f"Erro inesperado ao descrever execução {execution_arn}: {e}", level="ERROR")
        return None

def _get_sfn_execution_history(execution_arn):
    """Obtém o histórico de eventos de uma execução da Step Functions."""
    try:
        response = sfn_client.get_execution_history(executionArn=execution_arn, maxResults=100)
        events = response['events']
        # Pode haver mais páginas de eventos, se necessário implemente paginação aqui
        return events
    except ClientError as e:
        _log_message(f"Erro AWS ao obter histórico da execução {execution_arn}: {e}", level="ERROR")
        return []
    except Exception as e:
        _log_message(f"Erro inesperado ao obter histórico da execução {execution_arn}: {e}", level="ERROR")
        return []

def _get_lambda_logs(log_group_name, log_stream_name):
    """Obtém logs de um stream de log específico de uma função Lambda."""
    messages = []
    try:
        response = logs_client.get_log_events(
            logGroupName=log_group_name,
            logStreamName=log_stream_name,
            startFromHead=True
        )
        for event in response.get('events', []):
            messages.append(event['message'])
        return messages
    except ClientError as e:
        _log_message(f"Erro AWS ao obter logs de {log_group_name}/{log_stream_name}: {e}", level="ERROR")
        return []
    except Exception as e:
        _log_message(f"Erro inesperado ao obter logs: {e}", level="ERROR")
        return []

# --- Comandos da CLI ---

@click.group()
def cli():
    """CLI para orquestrar testes E2E em microsserviços AWS usando Step Functions."""
    pass

@cli.command()
@click.argument('scenario_name')
@click.option('--state-machine-arn', required=True, help='ARN da Step Functions genérica de teste (E2ETestFramework-GenericE2ETestFlow).')
@click.option('--wait', is_flag=True, default=True, help='Esperar a conclusão do teste e mostrar o resultado final.')
def run(scenario_name, state_machine_arn, wait):
    """Executa um cenário de teste E2E."""
    _log_message(f"Iniciando execução para o cenário: {scenario_name}")

    test_scenario_config = _load_scenario(scenario_name)
    if not test_scenario_config:
        return

    # Adiciona um ID único para esta execução do teste
    test_run_id = str(uuid.uuid4())
    test_scenario_config['testRunId'] = test_run_id

    # Nome da execução da SFN (curto para legibilidade)
    execution_name = f"{scenario_name}-{test_run_id[:8]}-{datetime.now().strftime('%H%M%S')}"

    try:
        start_response = sfn_client.start_execution(
            stateMachineArn=state_machine_arn,
            input=json.dumps(test_scenario_config),
            name=execution_name
        )
        execution_arn = start_response['executionArn']
        _log_message(click.style(f"\n--- Teste E2E Iniciado ---", fg='cyan'))
        _log_message(f"Cenário: {scenario_name}")
        _log_message(f"ID da Execução do Teste: {test_run_id}")
        _log_message(f"ARN da Execução da Step Functions: {execution_arn}")
        _log_message(f"Ver console AWS para detalhes: https://console.aws.amazon.com/states/home?#/executions/details/{execution_arn}")
        _log_message(click.style(f"---------------------------\n", fg='cyan'))

        if wait:
            _log_message(f"Aguardando a conclusão do teste...")
            status = 'RUNNING'
            spinner = ['|', '/', '-', '\\']
            spin_idx = 0
            
            # Loop de polling
            while status in ['RUNNING', 'PENDING']:
                sys.stdout.write(f"\rStatus: {status} {spinner[spin_idx]} ")
                sys.stdout.flush()
                spin_idx = (spin_idx + 1) % len(spinner)
                time.sleep(5) # Polling a cada 5 segundos
                
                execution_details = _get_sfn_execution_details(execution_arn)
                if execution_details:
                    status = execution_details['status']
                else:
                    status = 'UNKNOWN' # Para sair do loop em caso de erro

            sys.stdout.write("\n") # Nova linha após o spinner

            # Exibir resultado final como uma ferramenta convencional
            _log_message(click.style(f"\n--- Resultados do Teste: {scenario_name} ---", fg='cyan'))
            _log_message(f"Execução: {execution_arn}")
            
            if status == 'SUCCEEDED':
                _log_message(click.style(f"Resultado: PASSOU ✅", fg='green'))
                output = execution_details.get('output', '{}')
                _log_message(f"Output da Step Functions: {json.dumps(json.loads(output), indent=2)}")
            elif status == 'FAILED':
                _log_message(click.style(f"Resultado: FALHOU ❌", fg='red'))
                _log_message(f"Causa: {execution_details.get('cause', 'Não especificada.')}")
                _log_message(f"Erro: {execution_details.get('error', 'Não especificado.')}")
                _log_message(f"Output Final (parcial): {execution_details.get('output', 'N/A')}")
            elif status == 'ABORTED':
                _log_message(click.style(f"Resultado: ABORTADO ⚠️", fg='yellow'))
            else:
                _log_message(click.style(f"Resultado: {status} (status inesperado) ❓", fg='yellow'))
            _log_message(click.style(f"-----------------------------------------\n", fg='cyan'))

        else:
            _log_message(f"Teste iniciado. Use 'suacli status {execution_arn}' para verificar o progresso.")

    except ClientError as e:
        _log_message(f"Erro AWS ao iniciar execução da Step Functions: {e}", level="ERROR")
    except Exception as e:
        _log_message(f"Erro inesperado ao executar teste: {e}", level="ERROR")

@cli.command()
@click.argument('execution_arn')
def status(execution_arn):
    """Verifica o status de uma execução de teste E2E."""
    _log_message(f"Verificando status para execução: {execution_arn}")
    details = _get_sfn_execution_details(execution_arn)
    if details:
        _log_message(click.style(f"\n--- Status da Execução ---", fg='cyan'))
        _log_message(f"ARN: {details['executionArn']}")
        _log_message(f"Status: {details['status']}")
        _log_message(f"Data de Início: {details['startDate']}")
        if 'stopDate' in details:
            _log_message(f"Data de Fim: {details['stopDate']}")
        if details['status'] == 'FAILED':
            _log_message(f"Causa: {details.get('cause', 'Não especificada.')}")
            _log_message(f"Erro: {details.get('error', 'Não especificado.')}")
        _log_message(f"Ver console AWS para detalhes: https://console.aws.amazon.com/states/home?#/executions/details/{execution_arn}")
        _log_message(click.style(f"---------------------------\n", fg='cyan'))

@cli.command()
@click.argument('execution_arn')
def logs(execution_arn):
    """Obtém o histórico de logs detalhado de uma execução de teste E2E."""
    _log_message(f"Obtendo histórico de logs para execução: {execution_arn}")
    history_events = _get_sfn_execution_history(execution_arn)

    if not history_events:
        _log_message("Nenhum histórico de eventos encontrado para esta execução.")
        return

    _log_message(click.style(f"\n--- Histórico de Logs da Execução: {execution_arn} ---", fg='cyan'))
    for event in history_events:
        event_id = event['eventId']
        event_type = event['type']
        event_timestamp = event['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"[{event_timestamp}] [{event_id}] {event_type}"
        
        # Tenta obter detalhes específicos de TaskStateEntered/Exited
        if 'stateEnteredEventDetails' in event:
            state_name = event['stateEnteredEventDetails'].get('stateName')
            message += f" - Entrou no estado: {state_name}"
            # O input do estado
            # input_data = json.loads(event['stateEnteredEventDetails'].get('input', '{}'))
            # message += f"\n  Input: {json.dumps(input_data, indent=2)}"
        elif 'stateExitedEventDetails' in event:
            state_name = event['stateExitedEventDetails'].get('stateName')
            message += f" - Saiu do estado: {state_name}"
            # O output do estado
            # output_data = json.loads(event['stateExitedEventDetails'].get('output', '{}'))
            # message += f"\n  Output: {json.dumps(output_data, indent=2)}"
        elif 'taskFailedEventDetails' in event:
            message += f" - FALHA DA TAREFA: {event['taskFailedEventDetails'].get('error', 'Desconhecido')}"
            message += f"\n  Causa: {event['taskFailedEventDetails'].get('cause', 'N/A')}"
        elif 'lambdaFunctionSucceededEventDetails' in event:
            # Para logs mais detalhados da Lambda, precisaria do LogStreamName
            # Este ARN pode vir do event['lambdaFunctionSucceededEventDetails']['output'] ou outro local
            # Esta parte é mais complexa e talvez seja melhor orientar para o CloudWatch.
            # No entanto, podemos mostrar o output da Lambda se disponível
            try:
                lambda_output = json.loads(event['lambdaFunctionSucceededEventDetails'].get('output', '{}'))
                message += f"\n  Output da Lambda: {json.dumps(lambda_output, indent=2)}"
            except Exception:
                pass # Não é um JSON válido
        
        click.echo(message)
    
    _log_message(click.style(f"-----------------------------------------\n", fg='cyan'))
    _log_message(click.style("Para logs detalhados das Lambdas, visite o CloudWatch Logs:", fg='yellow'))
    _log_message(click.style(f"https://console.aws.amazon.com/cloudwatch/home?#/logStream?logGroupName=/aws/vendedlogs/states/{execution_arn.split(':')[-1]}-L-", fg='yellow')) # Exemplo de link CloudWatch para logs da SFN
    _log_message(click.style(f"-----------------------------------------\n", fg='cyan'))


@cli.command()
def list_scenarios():
    """Lista todos os cenários de teste disponíveis."""
    _log_message("Cenários de teste disponíveis:")
    if not os.path.exists(TEST_SCENARIOS_DIR):
        _log_message(f"Diretório de cenários '{TEST_SCENARIOS_DIR}' não encontrado.")
        return
    
    found_scenarios = False
    for filename in os.listdir(TEST_SCENARIOS_DIR):
        if filename.endswith(".json"):
            scenario_name = os.path.splitext(filename)[0]
            _log_message(f"- {scenario_name}")
            found_scenarios = True
    
    if not found_scenarios:
        _log_message("Nenhum arquivo .json de cenário encontrado.")


# Você pode adicionar comandos 'setup' e 'cleanup' se desenvolver as Step Functions para eles.
# @cli.command()
# def setup():
#     """Prepara o ambiente e dados para os testes."""
#     _log_message("Comando 'setup' ainda não implementado.")

# @cli.command()
# def cleanup():
#     """Limpa dados e recursos temporários após os testes."""
#     _log_message("Comando 'cleanup' ainda não implementado.")


if __name__ == '__main__':
    if not os.path.exists(TEST_SCENARIOS_DIR):
        os.makedirs(TEST_SCENARIOS_DIR) # Cria o diretório de cenários se não existir
    cli()