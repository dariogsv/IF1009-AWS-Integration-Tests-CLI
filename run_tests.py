import boto3
import json
import time
import os
from pathlib import Path
from typing import List
import click

sfn_client = boto3.client('stepfunctions')

def monitor_execution(execution_arn: str) -> str:
    """Espera a execução da Step Function terminar e retorna o status final."""
    while True:
        try:
            result = sfn_client.describe_execution(executionArn=execution_arn)
            status = result['status']
            if status in ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABORTED']:
                if status == 'FAILED':
                    history = sfn_client.get_execution_history(
                        executionArn=execution_arn,
                        reverseOrder=True,
                        maxResults=1
                    )
                    fail_details = history['events'][0].get('executionFailedEventDetails', {})
                    error = fail_details.get('error', 'UnknownError')
                    cause = fail_details.get('cause', 'UnknownCause')
                    click.secho(f"  ├─ Error: {error}", fg="red")
                    click.secho(f"  └─ Cause: {cause}", fg="red")
                return status
            time.sleep(3)  # Poll a cada 3 segundos
        except sfn_client.exceptions.ExecutionDoesNotExist:
            click.secho(f"Erro: Execução {execution_arn} não encontrada.", fg="red")
            return "FAILED"

@click.command()
@click.option('--sfn-arn', required=True, help='ARN da State Machine de teste a ser executada.')
@click.option('--tests-root-dir', default='tests', type=click.Path(exists=True), help='Diretório raiz contendo as suítes de teste.')
@click.argument('suites_to_run', nargs=-1)
def run(sfn_arn: str, tests_root_dir: str, suites_to_run: List[str]):
    """
    Orquestrador de testes que executa uma Step Function para cada cenário.

    Busca por suítes de teste em subdiretórios de 'tests'.
    Cada suíte deve ter um subdiretório 'cases' com arquivos .json de cenário.

    Para executar suítes específicas (ex: order_processing):
      python run_tests.py --sfn-arn <ARN> order_processing

    Para executar todas as suítes:
      python run_tests.py --sfn-arn <ARN>
    """
    root_path = Path(tests_root_dir)
    
    if suites_to_run:
        # O usuário especificou suítes para executar
        suite_paths = [root_path / suite for suite in suites_to_run]
        for path in suite_paths:
            if not path.is_dir():
                click.secho(f"Erro: Diretório da suíte de teste '{path}' não encontrado.", fg="red")
                return
    else:
        # Descobre todas as suítes (subdiretórios no diretório raiz)
        click.secho(f"Nenhuma suíte especificada. Buscando todas as suítes em '{root_path}'...", fg="blue")
        suite_paths = [d for d in root_path.iterdir() if d.is_dir()]

    if not suite_paths:
        click.secho(f"Nenhuma suíte de teste encontrada em '{tests_root_dir}'.", fg="yellow")
        return

    total_tests = 0
    failed_tests = 0

    for suite_path in suite_paths:
        click.secho(f"\n--- Executando Suíte: {suite_path.name} ---", fg="cyan", bold=True)
        cases_dir = suite_path / 'cases'
        if not cases_dir.is_dir():
            click.secho(f"  Aviso: Diretório 'cases' não encontrado para a suíte '{suite_path.name}'. Pulando.", fg="yellow")
            continue

        test_files = sorted(list(cases_dir.glob('*.json')))
        if not test_files:
            click.secho(f"  Aviso: Nenhum arquivo de caso de teste .json encontrado em '{cases_dir}'.", fg="yellow")
            continue
        
        click.secho(f"  Encontrados {len(test_files)} cenários de teste.", fg="blue")

        for test_file in test_files:
            total_tests += 1
            click.echo(f"▶️  Executando teste: {click.style(test_file.name, bold=True)}")
            with open(test_file, 'r', encoding='utf-8') as f:
                try:
                    # A SFN genérica espera um objeto com a chave "input"
                    sfn_input = {"input": json.load(f)}
                except json.JSONDecodeError:
                    click.secho(f"   Resultado: FAILED (JSON inválido no arquivo de caso de teste)\n", fg="red")
                    failed_tests += 1
                    continue

            response = sfn_client.start_execution(
                stateMachineArn=sfn_arn,
                input=json.dumps(sfn_input)
            )
            status = monitor_execution(response['executionArn'])
            fg_color = "green" if status == 'SUCCEEDED' else "red"
            if status != 'SUCCEEDED':
                failed_tests += 1
            click.secho(f"   Resultado: {status}\n", fg=fg_color)

    click.secho(f"\n--- Resumo Final ---", fg="cyan", bold=True)
    click.secho(f"Total de testes executados: {total_tests}")
    if failed_tests > 0:
        click.secho(f"Testes que falharam: {failed_tests}", fg="red")
        # Exit with a non-zero code to indicate failure for CI/CD pipelines
        exit(1)
    else:
        click.secho("Todos os testes passaram com sucesso!", fg="green")

if __name__ == '__main__':
    run()
